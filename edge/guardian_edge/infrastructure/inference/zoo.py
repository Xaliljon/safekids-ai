"""Filesystem model zoo: the managed, OTA-ready model store.

Extends the registry layout (``<root>/<name>/<version>/``) with mutation:
validated atomic installs, activation pointers, and rollback.

Install pipeline (every step must pass; a refused install leaves no trace):

    parse manifest -> checksum required & verified -> license allowed
    -> runtime compatible -> stage copy -> atomic rename into place

Versions are immutable once installed; activation and rollback are pointer
switches in ``state.json`` — rolling back never re-downloads or deletes
anything (ADR-0009). The future OTA agent downloads a signed bundle,
verifies the signature (firmware layer), then drives this class.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

from guardian_edge.application.inference.compatibility import CompatibilityChecker
from guardian_edge.application.inference.licensing import LicensePolicy
from guardian_edge.domain.errors import (
    ModelInstallError,
    ModelLoadError,
    ModelRegistryError,
)
from guardian_edge.domain.model import ModelManifest, ModelVersion
from guardian_edge.infrastructure.inference.integrity import sha256_of
from guardian_edge.infrastructure.inference.manifest import MANIFEST_FILE_NAME, load_manifest
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.inference.state import ModelState, read_state, write_state

logger = logging.getLogger(__name__)

STAGING_DIR_NAME = ".staging"


class FileSystemModelZoo:
    """ModelZoo implementation over the registry's directory layout."""

    def __init__(
        self,
        root: Path,
        license_policy: LicensePolicy | None = None,
        compatibility: CompatibilityChecker | None = None,
    ) -> None:
        self._root = root
        self._registry = FileSystemModelRegistry(root)
        self._license_policy = license_policy or LicensePolicy()
        self._compatibility = compatibility or CompatibilityChecker()
        self._clean_stale_staging()

    # ------------------------------------------------------------- install

    def install(self, bundle_dir: Path, activate: bool = False) -> ModelManifest:
        manifest = self._validate_bundle(bundle_dir)
        name = manifest.model.name
        version = manifest.model.version
        destination = self._root / name / version
        if destination.exists():
            raise ModelInstallError(
                f"model {name} v{version} is already installed — versions are "
                f"immutable; ship a new version instead"
            )
        staging = self._root / STAGING_DIR_NAME / f"{name}-{version}-{uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            shutil.copy2(bundle_dir / MANIFEST_FILE_NAME, staging / MANIFEST_FILE_NAME)
            shutil.copy2(bundle_dir / manifest.file_name, staging / manifest.file_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(destination)  # atomic on one filesystem
        finally:
            shutil.rmtree(staging, ignore_errors=True)  # no-op after rename
        logger.info("zoo: installed model %s v%s", name, version)
        if activate:
            self.activate(name, version)
        return manifest

    def _validate_bundle(self, bundle_dir: Path) -> ModelManifest:
        manifest_path = bundle_dir / MANIFEST_FILE_NAME
        try:
            manifest = load_manifest(manifest_path)
        except ModelLoadError as exc:
            raise ModelInstallError(f"bundle '{bundle_dir}': {exc}") from exc
        identity = f"model {manifest.model.name} v{manifest.model.version}"
        if manifest.sha256 is None:
            raise ModelInstallError(
                f"{identity}: manifest declares no sha256 — unverifiable bundles "
                f"are never installed"
            )
        artifact = bundle_dir / manifest.file_name
        if not artifact.is_file():
            raise ModelInstallError(
                f"{identity}: bundle is missing artifact '{manifest.file_name}'"
            )
        actual = sha256_of(artifact)
        if actual != manifest.sha256.lower():
            raise ModelInstallError(
                f"{identity}: artifact checksum {actual} does not match manifest "
                f"{manifest.sha256.lower()} — bundle corrupt or tampered"
            )
        self._license_policy.check(manifest)
        self._compatibility.check(manifest)
        return manifest

    # ---------------------------------------------------------- activation

    def activate(self, name: str, version: str) -> None:
        self._registry.get(name, version)  # existence + checksum verification
        model_dir = self._root / name
        state = read_state(model_dir)
        if state.active == version:
            return
        write_state(model_dir, ModelState(active=version, previous=state.active))
        logger.info("zoo: model %s active version %s -> %s", name, state.active, version)

    def rollback(self, name: str) -> str:
        model_dir = self._model_dir(name)
        state = read_state(model_dir)
        if state.previous is None:
            raise ModelInstallError(f"model {name}: no previous version to roll back to")
        self._registry.get(name, state.previous)  # target must still verify
        write_state(model_dir, ModelState(active=state.previous, previous=state.active))
        logger.warning("zoo: model %s rolled back %s -> %s", name, state.active, state.previous)
        return state.previous

    def active_version(self, name: str) -> str | None:
        return read_state(self._model_dir(name)).active

    # ------------------------------------------------------------ contents

    def versions(self, name: str) -> list[str]:
        entries = [
            entry.name
            for entry in self._model_dir(name).iterdir()
            if entry.is_dir() and ModelVersion.try_parse(entry.name) is not None
        ]
        return sorted(entries, key=lambda text: ModelVersion.parse(text))

    def remove(self, name: str, version: str) -> None:
        model_dir = self._model_dir(name)
        version_dir = model_dir / version
        if not version_dir.is_dir():
            raise ModelRegistryError(f"model {name} has no version '{version}'")
        state = read_state(model_dir)
        if state.active == version:
            raise ModelInstallError(
                f"model {name} v{version} is active — activate or roll back to "
                f"another version before removing it"
            )
        shutil.rmtree(version_dir)
        if state.previous == version:
            write_state(model_dir, ModelState(active=state.active, previous=None))
        logger.info("zoo: removed model %s v%s", name, version)

    # ------------------------------------------------------------ internals

    def _model_dir(self, name: str) -> Path:
        model_dir = self._root / name
        if not model_dir.is_dir():
            raise ModelRegistryError(f"unknown model '{name}' (looked in '{self._root}')")
        return model_dir

    def _clean_stale_staging(self) -> None:
        """Remove debris from installs interrupted by a crash or power loss."""
        staging_root = self._root / STAGING_DIR_NAME
        if not staging_root.is_dir():
            return
        for entry in staging_root.iterdir():
            shutil.rmtree(entry, ignore_errors=True)
            logger.warning("zoo: cleaned stale staging directory %s", entry.name)
