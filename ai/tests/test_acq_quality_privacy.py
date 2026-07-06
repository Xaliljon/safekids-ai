"""Quality + privacy gates over guardian_dataset_v1 workspaces."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from acquisition_fixtures import build_workspace, make_manifest, write_video

from guardian_ai.acquisition.privacy import check_privacy
from guardian_ai.acquisition.quality import (
    QUALITY_REPORT_FILE,
    validate_quality,
    write_quality_report,
)
from guardian_ai.acquisition.video import TARGET_FPS, TARGET_HEIGHT, TARGET_WIDTH
from guardian_ai.acquisition.workspace import DatasetWorkspace, WorkspaceManifest


@pytest.fixture()
def workspace(tmp_path: Path) -> DatasetWorkspace:
    return build_workspace(tmp_path / "ws", clip_count=3)


class TestQuality:
    def test_healthy_workspace_passes(self, workspace: DatasetWorkspace) -> None:
        report = validate_quality(workspace)
        assert report.ok, [issue.message for issue in report.errors]

    def test_report_file_is_written(self, workspace: DatasetWorkspace) -> None:
        report = validate_quality(workspace)
        path = write_quality_report(report, workspace)
        assert path.name == QUALITY_REPORT_FILE
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert "checked_utc" in payload

    def test_empty_workspace_is_an_error(self, tmp_path: Path) -> None:
        empty = DatasetWorkspace.create(tmp_path / "empty", make_manifest())
        report = validate_quality(empty)
        assert not report.ok
        assert "no clips" in report.errors[0].message

    def test_missing_annotation_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        workspace.annotation_path(clip_id).unlink()
        report = validate_quality(workspace)
        assert any("missing annotation" in issue.message for issue in report.errors)

    def test_missing_video_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        workspace.video_path(clip_id).unlink()
        report = validate_quality(workspace)
        assert any("missing video" in issue.message for issue in report.errors)

    def test_duplicate_videos_detected(self, workspace: DatasetWorkspace) -> None:
        ids = workspace.clip_ids()
        shutil.copyfile(workspace.video_path(ids[0]), workspace.video_path(ids[1]))
        report = validate_quality(workspace)
        assert any("duplicate video" in issue.message for issue in report.errors)

    def test_frozen_still_video_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        write_video(
            workspace.video_path(clip_id),
            frames=30,
            size=(TARGET_WIDTH, TARGET_HEIGHT),
            fps=float(TARGET_FPS),
            still=True,
        )
        report = validate_quality(workspace)
        assert any("duplicate frames" in issue.message for issue in report.errors)

    def test_invalid_timestamps_vs_video_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        raw = json.loads(workspace.annotation_path(clip_id).read_text())
        raw["frame_count"] = 999  # annotation claims frames the video lacks
        workspace.annotation_path(clip_id).write_text(json.dumps(raw))
        report = validate_quality(workspace)
        assert any("invalid timestamps" in issue.message for issue in report.errors)

    def test_malformed_annotation_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        raw = json.loads(workspace.annotation_path(clip_id).read_text())
        raw["events"][0]["start_frame"] = 25
        raw["events"][0]["end_frame"] = 10  # starts after it ends
        workspace.annotation_path(clip_id).write_text(json.dumps(raw))
        report = validate_quality(workspace)
        assert any("malformed annotation" in issue.message for issue in report.errors)

    def test_taxonomy_mismatch_detected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        raw = json.loads(workspace.annotation_path(clip_id).read_text())
        raw["taxonomy"]["version"] = "9.9.9"
        workspace.annotation_path(clip_id).write_text(json.dumps(raw))
        report = validate_quality(workspace)
        assert any("taxonomy mismatch" in issue.message for issue in report.errors)

    def test_unannotated_clip_is_a_warning(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        raw = json.loads(workspace.annotation_path(clip_id).read_text())
        raw["events"], raw["frames"] = [], []
        workspace.annotation_path(clip_id).write_text(json.dumps(raw))
        report = validate_quality(workspace)
        assert report.ok  # warning, not error
        assert any("no events and no boxes" in issue.message for issue in report.warnings)


class TestPrivacy:
    def test_clean_workspace_passes(self, workspace: DatasetWorkspace) -> None:
        report = check_privacy(workspace)
        assert report.ok, [violation.message for violation in report.violations]
        assert report.to_dict()["ok"] is True

    def test_dataset_and_taxonomy_names_are_not_person_names(
        self, workspace: DatasetWorkspace
    ) -> None:
        # "name" at dataset.json root / taxonomy.name is a title, allowed
        assert check_privacy(workspace).ok

    def test_missing_consent_is_a_violation(self, tmp_path: Path) -> None:
        workspace = build_workspace(
            tmp_path / "ws", clip_count=1, manifest=make_manifest(consent="  ")
        )
        report = check_privacy(workspace)
        assert any("consent" in violation.message for violation in report.violations)

    def test_minors_without_review_reference(self, tmp_path: Path) -> None:
        manifest = WorkspaceManifest(
            name="pilot",
            description="",
            collected_by="team",
            consent_reference="consent/1",
            contains_minors=True,
            anonymized=True,
            review_reference="",
        )
        workspace = build_workspace(tmp_path / "ws", clip_count=1, manifest=manifest)
        report = check_privacy(workspace)
        assert any("minors" in violation.message for violation in report.violations)

    @pytest.mark.parametrize(
        ("key", "value", "expect"),
        [
            ("child_name", "Anvar", "identity-bearing key"),
            ("email", "someone@example.com", "identity-bearing key"),
            ("gps", "41.2995,69.2401", "identity-bearing key"),
        ],
    )
    def test_forbidden_metadata_keys(
        self, workspace: DatasetWorkspace, key: str, value: str, expect: str
    ) -> None:
        clip_id = workspace.clip_ids()[0]
        metadata = workspace.metadata(clip_id)
        metadata[key] = value
        workspace.metadata_path(clip_id).write_text(json.dumps(metadata))
        report = check_privacy(workspace)
        assert any(expect in violation.message for violation in report.violations)

    @pytest.mark.parametrize(
        ("value", "expect"),
        [
            ("contact teacher@kindergarten.uz", "email address"),
            ("call +998 90 123 45 67", "phone number"),
            ("recorded at 41.29950,69.24010", "GPS coordinates"),
        ],
    )
    def test_identifier_patterns_in_values(
        self, workspace: DatasetWorkspace, value: str, expect: str
    ) -> None:
        clip_id = workspace.clip_ids()[0]
        metadata = workspace.metadata(clip_id)
        metadata["note"] = value
        workspace.metadata_path(clip_id).write_text(json.dumps(metadata))
        report = check_privacy(workspace)
        assert any(expect in violation.message for violation in report.violations)

    def test_face_identity_labels_rejected(self, workspace: DatasetWorkspace) -> None:
        clip_id = workspace.clip_ids()[0]
        raw = json.loads(workspace.annotation_path(clip_id).read_text())
        raw["frames"][0]["boxes"][0]["label"] = "face_id_7"
        workspace.annotation_path(clip_id).write_text(json.dumps(raw))
        report = check_privacy(workspace)
        assert any("identity label" in violation.message for violation in report.violations)
