"""Taxonomy v1 + guardian_dataset_v1 workspace layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acquisition_fixtures import (
    build_workspace,
    make_manifest,
    normalized_clip_annotation,
    write_video,
)

from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.taxonomy import (
    BOX_LABELS,
    EVENT_LABELS,
    GUARDIAN_VIDEO_TAXONOMY_V1,
    is_box_label,
    is_event_label,
)
from guardian_ai.acquisition.video import TARGET_FPS, TARGET_HEIGHT, TARGET_WIDTH
from guardian_ai.acquisition.workspace import SPLIT_NAMES, DatasetWorkspace, WorkspaceManifest
from guardian_ai.datasets.splits import assign_split


class TestTaxonomy:
    def test_exactly_the_mandated_nine_labels(self) -> None:
        assert GUARDIAN_VIDEO_TAXONOMY_V1.label_names() == frozenset(
            {
                "person",
                "child",
                "adult",
                "fall",
                "walking",
                "standing",
                "sitting",
                "lying",
                "unknown",
            }
        )

    def test_no_identity_or_face_labels(self) -> None:
        for label in GUARDIAN_VIDEO_TAXONOMY_V1.label_names():
            assert "face" not in label
            assert "identity" not in label
            assert "name" not in label

    def test_label_kinds_cover_the_taxonomy(self) -> None:
        assert GUARDIAN_VIDEO_TAXONOMY_V1.label_names() == BOX_LABELS | EVENT_LABELS
        assert is_box_label("child") and not is_box_label("fall")
        assert is_event_label("fall") and not is_event_label("adult")
        assert is_box_label("unknown") and is_event_label("unknown")


class TestWorkspace:
    def test_create_builds_the_exact_layout(self, tmp_path: Path) -> None:
        workspace = DatasetWorkspace.create(tmp_path / "ws", make_manifest())
        for name in ("train", "val", "test", "videos", "annotations", "metadata", "taxonomy"):
            assert (workspace.root / name).is_dir(), f"{name}/ missing"
        taxonomy = json.loads(
            (workspace.root / "taxonomy" / "taxonomy.json").read_text(encoding="utf-8")
        )
        assert taxonomy["name"] == "guardian-video-safety"
        assert len(taxonomy["labels"]) == 9

    def test_create_refuses_existing(self, tmp_path: Path) -> None:
        DatasetWorkspace.create(tmp_path / "ws", make_manifest())
        with pytest.raises(AcquisitionError, match="already exists"):
            DatasetWorkspace.create(tmp_path / "ws", make_manifest())

    def test_open_refuses_non_workspace(self, tmp_path: Path) -> None:
        with pytest.raises(AcquisitionError, match="not a guardian_dataset_v1"):
            DatasetWorkspace.open(tmp_path)

    def test_manifest_roundtrip(self, tmp_path: Path) -> None:
        manifest = WorkspaceManifest(
            name="pilot-data",
            description="d",
            collected_by="team",
            consent_reference="consent/1",
            contains_minors=True,
            anonymized=True,
            review_reference="ethics/7",
        )
        workspace = DatasetWorkspace.create(tmp_path / "ws", manifest)
        assert workspace.manifest == manifest

    def test_add_clip_registers_everything(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=2, review_to=None)
        ids = workspace.clip_ids()
        assert len(ids) == 2
        for clip_id in ids:
            assert workspace.video_path(clip_id).is_file()
            assert workspace.annotation_path(clip_id).is_file()
            assert workspace.metadata_path(clip_id).is_file()
            # split assignment is the ADR-0010 hash — recomputable forever
            assert workspace.split_of(clip_id) == assign_split(clip_id)

    def test_add_clip_refuses_duplicates_and_mismatch(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=1, review_to=None)
        clip_id = workspace.clip_ids()[0]
        video = write_video(
            tmp_path / "again.mp4",
            frames=30,
            size=(TARGET_WIDTH, TARGET_HEIGHT),
            fps=float(TARGET_FPS),
        )
        with pytest.raises(AcquisitionError, match="already in workspace"):
            workspace.add_clip(clip_id, video, normalized_clip_annotation(clip_id), {})
        with pytest.raises(AcquisitionError, match="does not match annotation"):
            workspace.add_clip("other", video, normalized_clip_annotation(clip_id), {})

    def test_split_membership_files(self, tmp_path: Path) -> None:
        workspace = build_workspace(tmp_path / "ws", clip_count=4, review_to=None)
        total = sum(len(workspace.clip_ids(split)) for split in SPLIT_NAMES)
        assert total == 4
