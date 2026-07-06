"""Statistics, the immutable registry, and the training-ready export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from acquisition_fixtures import approve_workspace, build_workspace, make_manifest

from guardian_ai.acquisition.errors import DatasetPublishError, DatasetRegistryError
from guardian_ai.acquisition.registry import VideoDatasetRegistry
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.statistics import compute_statistics, generate_dataset_report
from guardian_ai.acquisition.workspace import DatasetWorkspace


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> dict:
    base = tmp_path_factory.mktemp("registry-case")
    workspace = build_workspace(base / "ws", clip_count=3)
    approve_workspace(workspace, by="Khalil")
    registry = VideoDatasetRegistry(base / "registry")
    path = registry.publish(workspace, "guardian-dataset", "1.0.0")
    return {"workspace": workspace, "registry": registry, "path": path, "base": base}


class TestStatistics:
    def test_numbers_are_hand_checkable(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=2)
        statistics = compute_statistics(workspace)
        assert statistics["videos"] == 2
        # 30 frames at 15 fps = 2s per clip
        assert statistics["total_duration_s"] == pytest.approx(4.0)
        assert statistics["average_clip_duration_s"] == pytest.approx(2.0)
        # fall span 10..15 inclusive = 6 frames = 0.4s
        assert statistics["average_fall_duration_s"] == pytest.approx(0.4)
        assert statistics["event_labels"] == {"fall": 2, "lying": 2}
        assert statistics["class_balance"]["fall"] == pytest.approx(0.5)
        assert statistics["box_labels"] == {"person": 4}
        assert statistics["fps_distribution"] == {"15": 2}
        assert statistics["resolution_distribution"] == {"640x480": 2}
        assert statistics["camera_angles"] == {"side": 2}

    def test_report_pdf_is_generated(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=1)
        path = generate_dataset_report(workspace)
        assert path.name == "dataset-report.pdf"
        assert path.read_bytes()[:5] == b"%PDF-"


class TestRegistry:
    def test_publish_installs_immutable_version(self, published: dict) -> None:
        path = published["path"]
        assert (path / "version.json").is_file()
        assert (path / "checksums.json").is_file()
        assert (path / "metadata" / "quality-report.json").is_file()
        assert (path / "metadata" / "dataset-report.pdf").is_file()
        manifest = json.loads((path / "version.json").read_text())
        assert manifest["approved_by"] == "Khalil"
        assert manifest["statistics"]["videos"] == 3
        # the installed copy's workflow reached PUBLISHED
        assert ReviewWorkflow(path).state() is ReviewState.PUBLISHED

    def test_training_ready_export(self, published: dict) -> None:
        training = published["path"] / "training"
        data = yaml.safe_load((training / "data.yaml").read_text())
        assert data["names"] == ["adult", "child", "person", "unknown"]
        assert data["nc"] == 4
        images = list(training.glob("images/*/*.png"))
        labels = list(training.glob("labels/*/*.txt"))
        assert images and len(images) == len(labels)
        line = labels[0].read_text().strip().split()
        assert len(line) == 5  # class cx cy w h
        assert line[0] == str(data["names"].index("person"))
        for value in line[1:]:
            assert 0.0 <= float(value) <= 1.0

    def test_versions_are_immutable(self, published: dict) -> None:
        with pytest.raises(DatasetPublishError, match="immutable"):
            published["registry"].publish(published["workspace"], "guardian-dataset", "1.0.0")

    def test_get_latest_and_manifest(self, published: dict) -> None:
        registry = published["registry"]
        assert registry.get("guardian-dataset") == published["path"]
        assert registry.versions("guardian-dataset") == ["1.0.0"]
        assert registry.version_manifest("guardian-dataset")["version"] == "1.0.0"

    def test_get_verifies_checksums(self, published: dict) -> None:
        target = published["path"] / "dataset.json"
        original = target.read_text()
        target.write_text(original.replace("acquisition test dataset", "tampered"))
        try:
            with pytest.raises(DatasetRegistryError, match="checksum mismatch"):
                published["registry"].get("guardian-dataset", "1.0.0")
        finally:
            target.write_text(original)

    def test_unknown_dataset_is_loud(self, published: dict) -> None:
        with pytest.raises(DatasetRegistryError, match="no published versions"):
            published["registry"].get("nonexistent")


class TestPublishGates:
    def test_publish_requires_approval(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=1)  # IMPORTED only
        registry = VideoDatasetRegistry(tmp_path / "registry")
        with pytest.raises(Exception, match="requires review state"):
            registry.publish(workspace, "d", "1.0.0")

    def test_publish_requires_semver(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=1)
        approve_workspace(workspace)
        registry = VideoDatasetRegistry(tmp_path / "registry")
        with pytest.raises(DatasetPublishError, match="semantic version"):
            registry.publish(workspace, "d", "v1")

    def test_quality_gate_blocks_publish(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=2)
        approve_workspace(workspace)
        workspace.annotation_path(workspace.clip_ids()[0]).unlink()
        registry = VideoDatasetRegistry(tmp_path / "registry")
        with pytest.raises(DatasetPublishError, match="quality gate failed"):
            registry.publish(workspace, "d", "1.0.0")

    def test_privacy_gate_blocks_publish(self, tmp_path: Path) -> None:
        workspace = build_workspace(
            tmp_path / "ws", clip_count=1, manifest=make_manifest(consent="")
        )
        approve_workspace(workspace)
        registry = VideoDatasetRegistry(tmp_path / "registry")
        with pytest.raises(DatasetPublishError, match="privacy gate failed"):
            registry.publish(workspace, "d", "1.0.0")

    def test_refused_publish_leaves_no_trace(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=1)
        registry = VideoDatasetRegistry(tmp_path / "registry")
        with pytest.raises(Exception, match="requires review state"):
            registry.publish(workspace, "d", "1.0.0")
        assert not (tmp_path / "registry" / "d").exists()
        # a fresh registry sweeps stale staging
        VideoDatasetRegistry(tmp_path / "registry")
        assert not (tmp_path / "registry" / ".staging").exists()


def test_second_version_coexists(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path / "ws", clip_count=1)
    approve_workspace(workspace)
    registry = VideoDatasetRegistry(tmp_path / "registry")
    registry.publish(workspace, "guardian-dataset", "1.0.0")

    second = build_workspace(tmp_path / "ws2", clip_count=2)
    approve_workspace(second)
    registry.publish(second, "guardian-dataset", "1.1.0")
    assert registry.versions("guardian-dataset") == ["1.0.0", "1.1.0"]
    assert registry.get("guardian-dataset").name == "1.1.0"  # latest by semver
    assert isinstance(DatasetWorkspace.open(registry.get("guardian-dataset")), DatasetWorkspace)
