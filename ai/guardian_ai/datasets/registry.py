"""Filesystem dataset registry: versioned, gated, immutable.

Layout (mirrors the model zoo, ADR-0009/ADR-0010):

    <root>/
      .staging/                     # in-flight publishes; never listed
      kindergarten-scenes/
        1.0.0/
          dataset.json
          annotations/
            train.jsonl
            val.jsonl
            test.jsonl

The registry manages *metadata* — manifests and annotations. Media files
stay in DVC-managed storage and are referenced by relative path (raw child
video never enters git or this registry; see datasets/README.md).

Publish gates (all must pass; a refused publish leaves no trace):
manifest valid -> taxonomy binding matches -> annotations parse ->
quality report has no errors -> privacy report has no violations.
Checksums and sample counts are computed and written into the finalized
manifest; ``get()`` re-verifies them.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from guardian_ai.datasets.annotations import SampleRecord, read_records
from guardian_ai.datasets.errors import (
    AnnotationError,
    DatasetPublishError,
    DatasetRegistryError,
    DatasetValidationError,
)
from guardian_ai.datasets.manifest import (
    DATASET_MANIFEST_NAME,
    DatasetManifest,
    SplitFile,
    load_manifest,
    save_manifest,
)
from guardian_ai.datasets.privacy import check_privacy
from guardian_ai.datasets.quality import validate_quality
from guardian_ai.datasets.taxonomy import LabelTaxonomy
from guardian_ai.datasets.versioning import DatasetVersion

logger = logging.getLogger(__name__)

ANNOTATIONS_DIR_NAME = "annotations"
STAGING_DIR_NAME = ".staging"
_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class RegisteredDataset:
    """A verified dataset version and where it lives."""

    manifest: DatasetManifest
    root: Path

    def load_split(self, split_name: str) -> list[SampleRecord]:
        split = self.manifest.splits.get(split_name)
        if split is None:
            raise DatasetRegistryError(
                f"dataset {self.manifest.name} has no split '{split_name}' "
                f"(has {sorted(self.manifest.splits)})"
            )
        return read_records(self.root / ANNOTATIONS_DIR_NAME / split.file_name)


class FileSystemDatasetRegistry:
    """Dataset registry over a local directory tree."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._clean_stale_staging()

    # -------------------------------------------------------------- reads

    def list_datasets(self) -> list[DatasetManifest]:
        manifests: list[DatasetManifest] = []
        if not self._root.is_dir():
            return manifests
        for manifest_path in sorted(self._root.glob(f"*/*/{DATASET_MANIFEST_NAME}")):
            if STAGING_DIR_NAME in manifest_path.parts:
                continue
            try:
                manifests.append(load_manifest(manifest_path))
            except DatasetValidationError:
                logger.exception("dataset registry: skipping invalid manifest %s", manifest_path)
        return manifests

    def get(self, name: str, version: str | None = None) -> RegisteredDataset:
        """Resolve a dataset (latest version when omitted) and verify checksums."""
        version_dir = self._resolve_version_dir(name, version)
        manifest = self._load_verified_manifest(version_dir, name)
        return RegisteredDataset(manifest=manifest, root=version_dir)

    # ------------------------------------------------------------ publish

    def publish(self, bundle_dir: Path, taxonomy: LabelTaxonomy) -> DatasetManifest:
        """Validate a dataset bundle through every gate and install it.

        The bundle holds ``dataset.json`` plus ``annotations/<split>.jsonl``
        files. Raises DatasetPublishError when any gate fails; a refused
        publish leaves no trace.
        """
        manifest, splits = self._validate_bundle(bundle_dir, taxonomy)
        destination = self._root / manifest.name / manifest.version
        if destination.exists():
            raise DatasetPublishError(
                f"dataset {manifest.name} v{manifest.version} already exists — "
                f"versions are immutable; publish a new version instead"
            )
        finalized = self._finalize_manifest(manifest, bundle_dir)
        staging = (
            self._root / STAGING_DIR_NAME / f"{manifest.name}-{manifest.version}-{uuid4().hex}"
        )
        (staging / ANNOTATIONS_DIR_NAME).mkdir(parents=True)
        try:
            save_manifest(staging / DATASET_MANIFEST_NAME, finalized)
            for split in finalized.splits.values():
                shutil.copy2(
                    bundle_dir / ANNOTATIONS_DIR_NAME / split.file_name,
                    staging / ANNOTATIONS_DIR_NAME / split.file_name,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        logger.info(
            "dataset registry: published %s v%s (%d splits)",
            finalized.name,
            finalized.version,
            len(finalized.splits),
        )
        return finalized

    # ---------------------------------------------------------- internals

    def _validate_bundle(
        self, bundle_dir: Path, taxonomy: LabelTaxonomy
    ) -> tuple[DatasetManifest, dict[str, list[SampleRecord]]]:
        try:
            manifest = load_manifest(bundle_dir / DATASET_MANIFEST_NAME)
        except DatasetValidationError as exc:
            raise DatasetPublishError(f"bundle '{bundle_dir}': {exc}") from exc
        if (manifest.taxonomy_name, manifest.taxonomy_version) != (taxonomy.name, taxonomy.version):
            raise DatasetPublishError(
                f"dataset {manifest.name}: bound to taxonomy {manifest.taxonomy_name} "
                f"v{manifest.taxonomy_version}, publishing against {taxonomy.name} "
                f"v{taxonomy.version}"
            )
        splits: dict[str, list[SampleRecord]] = {}
        for split_name, split in manifest.splits.items():
            split_path = bundle_dir / ANNOTATIONS_DIR_NAME / split.file_name
            try:
                splits[split_name] = read_records(split_path)
            except AnnotationError as exc:
                raise DatasetPublishError(str(exc)) from exc
        quality = validate_quality(splits, taxonomy)
        if not quality.ok:
            details = "; ".join(_issue_text(i.message, i.sample) for i in quality.errors)
            raise DatasetPublishError(f"dataset {manifest.name}: quality gate failed: {details}")
        for warning in quality.warnings:
            logger.warning(
                "dataset %s: %s", manifest.name, _issue_text(warning.message, warning.sample)
            )
        privacy = check_privacy(manifest, splits)
        if not privacy.ok:
            details = "; ".join(_issue_text(v.message, v.sample) for v in privacy.violations)
            raise DatasetPublishError(f"dataset {manifest.name}: privacy gate failed: {details}")
        return manifest, splits

    def _finalize_manifest(self, manifest: DatasetManifest, bundle_dir: Path) -> DatasetManifest:
        finalized_splits = {}
        for split_name, split in manifest.splits.items():
            split_path = bundle_dir / ANNOTATIONS_DIR_NAME / split.file_name
            finalized_splits[split_name] = SplitFile(
                file_name=split.file_name,
                sha256=_sha256_of(split_path),
                samples=sum(
                    1
                    for line in split_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ),
            )
        return DatasetManifest(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            taxonomy_name=manifest.taxonomy_name,
            taxonomy_version=manifest.taxonomy_version,
            created_utc=manifest.created_utc,
            provenance=manifest.provenance,
            privacy=manifest.privacy,
            splits=finalized_splits,
            license=manifest.license,
            metadata=manifest.metadata,
        )

    def _load_verified_manifest(self, version_dir: Path, name: str) -> DatasetManifest:
        try:
            manifest = load_manifest(version_dir / DATASET_MANIFEST_NAME)
        except DatasetValidationError as exc:
            raise DatasetRegistryError(str(exc)) from exc
        if manifest.name != name:
            raise DatasetRegistryError(
                f"manifest in '{version_dir}' declares dataset '{manifest.name}', expected '{name}'"
            )
        for split_name, split in manifest.splits.items():
            split_path = version_dir / ANNOTATIONS_DIR_NAME / split.file_name
            if not split_path.is_file():
                raise DatasetRegistryError(
                    f"dataset {name}: split '{split_name}' file missing: {split_path}"
                )
            if split.sha256 is not None and _sha256_of(split_path) != split.sha256.lower():
                raise DatasetRegistryError(
                    f"dataset {name}: split '{split_name}' checksum mismatch — "
                    f"annotations were modified after publication"
                )
        return manifest

    def _resolve_version_dir(self, name: str, version: str | None) -> Path:
        dataset_dir = self._root / name
        if not dataset_dir.is_dir():
            raise DatasetRegistryError(f"unknown dataset '{name}' (looked in '{self._root}')")
        if version is not None:
            version_dir = dataset_dir / version
            if not version_dir.is_dir():
                raise DatasetRegistryError(f"dataset '{name}' has no version '{version}'")
            return version_dir
        versions = [
            entry
            for entry in dataset_dir.iterdir()
            if entry.is_dir() and DatasetVersion.try_parse(entry.name) is not None
        ]
        if not versions:
            raise DatasetRegistryError(f"dataset '{name}' has no versions")
        return max(versions, key=lambda entry: DatasetVersion.parse(entry.name))

    def _clean_stale_staging(self) -> None:
        staging_root = self._root / STAGING_DIR_NAME
        if not staging_root.is_dir():
            return
        for entry in staging_root.iterdir():
            shutil.rmtree(entry, ignore_errors=True)
            logger.warning("dataset registry: cleaned stale staging %s", entry.name)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _issue_text(message: str, sample: str | None) -> str:
    return f"{message} [{sample}]" if sample else message
