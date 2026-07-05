"""Dataset registry: publish gates, versioning, verification."""

from pathlib import Path

import pytest
from dataset_fixtures import build_bundle_dir, make_manifest, make_record

from guardian_ai.datasets.errors import DatasetPublishError, DatasetRegistryError
from guardian_ai.datasets.manifest import SplitFile
from guardian_ai.datasets.registry import (
    STAGING_DIR_NAME,
    FileSystemDatasetRegistry,
)
from guardian_ai.datasets.taxonomy import GUARDIAN_TAXONOMY_V1, LabelDefinition, LabelTaxonomy


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "datasets"


@pytest.fixture
def registry(root: Path) -> FileSystemDatasetRegistry:
    return FileSystemDatasetRegistry(root)


def publish_ok(registry: FileSystemDatasetRegistry, tmp_path: Path, version: str = "1.0.0"):  # noqa: ANN201
    manifest = make_manifest(
        version=version,
        splits={
            "train": SplitFile(file_name="train.jsonl"),
            "val": SplitFile(file_name="val.jsonl"),
        },
    )
    bundle = build_bundle_dir(tmp_path / f"bundle-{version}", manifest=manifest)
    return registry.publish(bundle, GUARDIAN_TAXONOMY_V1)


class TestPublish:
    def test_publishes_and_finalizes_checksums_and_counts(
        self, registry: FileSystemDatasetRegistry, root: Path, tmp_path: Path
    ) -> None:
        manifest = publish_ok(registry, tmp_path)
        assert manifest.splits["train"].sha256 is not None
        assert manifest.splits["train"].samples == 4
        assert (root / "kindergarten-scenes" / "1.0.0" / "dataset.json").is_file()
        registered = registry.get("kindergarten-scenes")
        assert registered.manifest.splits["val"].samples == 2
        assert len(registered.load_split("train")) == 4

    def test_versions_are_immutable(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        publish_ok(registry, tmp_path)
        with pytest.raises(DatasetPublishError, match="immutable"):
            publish_ok(registry, tmp_path / "again")

    def test_quality_gate_blocks_leaky_dataset(
        self, registry: FileSystemDatasetRegistry, root: Path, tmp_path: Path
    ) -> None:
        leaked = make_record("images/leak.jpg")
        bundle = build_bundle_dir(
            tmp_path / "bundle",
            split_records={"train": [leaked], "val": [leaked]},
        )
        with pytest.raises(DatasetPublishError, match="quality gate"):
            registry.publish(bundle, GUARDIAN_TAXONOMY_V1)
        assert not (root / "kindergarten-scenes").exists(), "refused publish leaves no trace"

    def test_privacy_gate_blocks_identity_data(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        bundle = build_bundle_dir(
            tmp_path / "bundle",
            split_records={
                "train": [make_record("images/a.jpg", attributes={"child_id": "C-7"})],
                "val": [make_record("images/b.jpg")],
            },
        )
        with pytest.raises(DatasetPublishError, match="privacy gate"):
            registry.publish(bundle, GUARDIAN_TAXONOMY_V1)

    def test_taxonomy_binding_must_match(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        other_taxonomy = LabelTaxonomy(
            name="other", version="9.0.0", labels=(LabelDefinition("person"),)
        )
        bundle = build_bundle_dir(tmp_path / "bundle")
        with pytest.raises(DatasetPublishError, match="taxonomy"):
            registry.publish(bundle, other_taxonomy)

    def test_malformed_annotations_are_refused(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        bundle = build_bundle_dir(tmp_path / "bundle")
        (bundle / "annotations" / "train.jsonl").write_text("{broken\n", encoding="utf-8")
        with pytest.raises(DatasetPublishError, match="train.jsonl:1"):
            registry.publish(bundle, GUARDIAN_TAXONOMY_V1)


class TestReads:
    def test_get_without_version_resolves_latest_semver(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        publish_ok(registry, tmp_path, version="1.2.0")
        publish_ok(registry, tmp_path, version="1.10.0")
        assert registry.get("kindergarten-scenes").manifest.version == "1.10.0"

    def test_unknown_dataset_and_version_raise(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        with pytest.raises(DatasetRegistryError, match="unknown dataset"):
            registry.get("ghost")
        publish_ok(registry, tmp_path)
        with pytest.raises(DatasetRegistryError, match="no version"):
            registry.get("kindergarten-scenes", "9.9.9")

    def test_modified_annotations_fail_checksum_on_get(
        self, registry: FileSystemDatasetRegistry, root: Path, tmp_path: Path
    ) -> None:
        publish_ok(registry, tmp_path)
        published = root / "kindergarten-scenes" / "1.0.0" / "annotations" / "train.jsonl"
        published.write_text(published.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(DatasetRegistryError, match="checksum mismatch"):
            registry.get("kindergarten-scenes")

    def test_list_datasets_skips_staging(
        self, registry: FileSystemDatasetRegistry, root: Path, tmp_path: Path
    ) -> None:
        publish_ok(registry, tmp_path)
        debris = root / STAGING_DIR_NAME / "in-flight"
        build_bundle_dir(debris)
        names = {m.name for m in registry.list_datasets()}
        assert names == {"kindergarten-scenes"}

    def test_stale_staging_swept_on_startup(self, root: Path) -> None:
        debris = root / STAGING_DIR_NAME / "crashed-publish"
        debris.mkdir(parents=True)
        (debris / "partial.jsonl").write_text("partial", encoding="utf-8")
        FileSystemDatasetRegistry(root)
        assert not any((root / STAGING_DIR_NAME).iterdir())

    def test_load_split_unknown_name_raises(
        self, registry: FileSystemDatasetRegistry, tmp_path: Path
    ) -> None:
        publish_ok(registry, tmp_path)
        registered = registry.get("kindergarten-scenes")
        with pytest.raises(DatasetRegistryError, match="no split"):
            registered.load_split("holdout")
