"""Filesystem model registry.

Layout (one directory per model, one per version — ADR-0008):

    <root>/
      fall-detector/
        1.0.0/
          manifest.json
          model.onnx

The registry is the trust boundary for model artifacts: it resolves
versions, checks the artifact exists, and verifies its SHA-256 when the
manifest declares one — a corrupted or swapped model file must never reach
an engine (docs/03, security by default; models are versioned).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from guardian_edge.application.inference.ports import RegisteredModel
from guardian_edge.domain.errors import ModelLoadError, ModelRegistryError
from guardian_edge.domain.model import ModelManifest
from guardian_edge.infrastructure.inference.manifest import MANIFEST_FILE_NAME, load_manifest

logger = logging.getLogger(__name__)

_HASH_CHUNK_BYTES = 1 << 20  # 1 MiB


class FileSystemModelRegistry:
    """ModelRegistry implementation over a local models directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def list_models(self) -> list[ModelManifest]:
        """Manifests of every valid model version under the root.

        Invalid manifests are logged and skipped — one broken model must not
        hide the rest.
        """
        manifests: list[ModelManifest] = []
        if not self._root.is_dir():
            return manifests
        for manifest_path in sorted(self._root.glob(f"*/*/{MANIFEST_FILE_NAME}")):
            try:
                manifests.append(load_manifest(manifest_path))
            except ModelLoadError:
                logger.exception("registry: skipping invalid manifest %s", manifest_path)
        return manifests

    def get(self, name: str, version: str | None = None) -> RegisteredModel:
        """Resolve a model, verifying artifact presence and checksum."""
        version_dir = self._resolve_version_dir(name, version)
        manifest_path = version_dir / MANIFEST_FILE_NAME
        try:
            manifest = load_manifest(manifest_path)
        except ModelLoadError as exc:
            raise ModelRegistryError(str(exc)) from exc
        if manifest.model.name != name:
            raise ModelRegistryError(
                f"manifest at '{manifest_path}' declares model "
                f"'{manifest.model.name}', expected '{name}'"
            )
        artifact = version_dir / manifest.file_name
        if not artifact.is_file():
            raise ModelRegistryError(f"model artifact missing: '{artifact}'")
        self._verify_checksum(manifest, artifact)
        return RegisteredModel(manifest=manifest, path=artifact)

    def _resolve_version_dir(self, name: str, version: str | None) -> Path:
        model_dir = self._root / name
        if not model_dir.is_dir():
            raise ModelRegistryError(f"unknown model '{name}' (looked in '{self._root}')")
        if version is not None:
            version_dir = model_dir / version
            if not version_dir.is_dir():
                raise ModelRegistryError(f"model '{name}' has no version '{version}'")
            return version_dir
        versions = [entry for entry in model_dir.iterdir() if entry.is_dir()]
        if not versions:
            raise ModelRegistryError(f"model '{name}' has no versions")
        return max(versions, key=lambda entry: _version_key(entry.name))

    def _verify_checksum(self, manifest: ModelManifest, artifact: Path) -> None:
        if manifest.sha256 is None:
            logger.warning(
                "model %s v%s declares no sha256; loading unverified",
                manifest.model.name,
                manifest.model.version,
            )
            return
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != manifest.sha256.lower():
            raise ModelRegistryError(
                f"model {manifest.model.name} v{manifest.model.version}: checksum mismatch "
                f"(artifact {actual}, manifest {manifest.sha256.lower()}) — refusing to load"
            )


def _version_key(version: str) -> tuple[int, ...]:
    """Order semantic-style versions numerically; non-numeric parts sort lowest."""
    return tuple(int(part) if part.isdigit() else -1 for part in version.split("."))
