"""Pilot evidence import (lineage!) + the review workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acquisition_fixtures import build_evidence_export, make_manifest

from guardian_ai.acquisition.errors import ImporterError, WorkflowError
from guardian_ai.acquisition.pilot import LINEAGE_KEYS, import_pilot_evidence, lineage_of
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.workspace import DatasetWorkspace


def make_workspace(tmp_path: Path) -> DatasetWorkspace:
    return DatasetWorkspace.create(tmp_path / "ws", make_manifest())


class TestPilotImport:
    def test_import_preserves_full_lineage(self, tmp_path: Path) -> None:
        export, record = build_evidence_export(tmp_path / "export")
        workspace = make_workspace(tmp_path)
        imported = import_pilot_evidence(export, workspace)
        assert imported == [f"pilot-{record['incident_id'][:8]}"]

        lineage = lineage_of(workspace, imported[0])
        for key in LINEAGE_KEYS:  # incident/track/detection/frame/correlation
            assert lineage[key] == record[key]

        annotation = workspace.annotation(imported[0])
        assert annotation.events == ()  # a candidate, not ground truth
        assert annotation.attributes["needs_annotation"] == "true"
        assert ReviewWorkflow(workspace.root).state() is ReviewState.IMPORTED

    def test_rejects_record_without_lineage(self, tmp_path: Path) -> None:
        export, record = build_evidence_export(tmp_path / "export")
        metadata_path = export / record["incident_id"] / "metadata.json"
        broken = json.loads(metadata_path.read_text())
        del broken["correlation_id"]
        metadata_path.write_text(json.dumps(broken))
        with pytest.raises(ImporterError, match="lineage"):
            import_pilot_evidence(export, make_workspace(tmp_path))

    def test_rejects_missing_clip(self, tmp_path: Path) -> None:
        export, record = build_evidence_export(tmp_path / "export")
        (export / record["incident_id"] / "clip.mp4").unlink()
        with pytest.raises(ImporterError, match="clip.mp4"):
            import_pilot_evidence(export, make_workspace(tmp_path))

    def test_rejects_empty_export(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ImporterError, match="no evidence exports"):
            import_pilot_evidence(empty, make_workspace(tmp_path))

    def test_lineage_of_refuses_open_dataset_clips(self, tmp_path: Path) -> None:
        export, _ = build_evidence_export(tmp_path / "export")
        workspace = make_workspace(tmp_path)
        clip_id = import_pilot_evidence(export, workspace)[0]
        metadata = workspace.metadata(clip_id)
        del metadata["lineage"]
        workspace.metadata_path(clip_id).write_text(json.dumps(metadata))
        with pytest.raises(ImporterError, match="no pilot lineage"):
            lineage_of(workspace, clip_id)


class TestReviewWorkflow:
    def test_full_chain_with_audit_trail(self, tmp_path: Path) -> None:
        workflow = ReviewWorkflow(tmp_path)
        workflow.record(ReviewState.IMPORTED, by="importer:urfall")
        workflow.record(ReviewState.ANNOTATED, by="Annotator A", notes="two passes")
        workflow.record(ReviewState.REVIEWED, by="Reviewer R", notes="spot check ok")
        workflow.record(ReviewState.APPROVED, by="Khalil", notes="ship it")
        workflow.record(ReviewState.PUBLISHED, by="Khalil")

        assert workflow.state() is ReviewState.PUBLISHED
        history = workflow.history()
        assert [entry["state"] for entry in history] == [
            "imported",
            "annotated",
            "reviewed",
            "approved",
            "published",
        ]
        approval = workflow.approval()
        assert approval["by"] == "Khalil"  # reviewer name stored
        assert approval["utc"]  # approval time stored
        assert approval["notes"] == "ship it"  # review notes stored

    def test_no_skipping_states(self, tmp_path: Path) -> None:
        workflow = ReviewWorkflow(tmp_path)
        workflow.record(ReviewState.IMPORTED, by="i")
        with pytest.raises(WorkflowError, match="illegal transition"):
            workflow.record(ReviewState.APPROVED, by="hasty")

    def test_no_going_backwards_or_restarting(self, tmp_path: Path) -> None:
        workflow = ReviewWorkflow(tmp_path)
        workflow.record(ReviewState.IMPORTED, by="i")
        workflow.record(ReviewState.ANNOTATED, by="a")
        with pytest.raises(WorkflowError, match="illegal transition"):
            workflow.record(ReviewState.IMPORTED, by="again")

    def test_must_start_at_imported(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowError, match="starts at"):
            ReviewWorkflow(tmp_path).record(ReviewState.ANNOTATED, by="a")

    def test_anonymous_transitions_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowError, match="named actor"):
            ReviewWorkflow(tmp_path).record(ReviewState.IMPORTED, by="  ")

    def test_require_and_missing_approval(self, tmp_path: Path) -> None:
        workflow = ReviewWorkflow(tmp_path)
        with pytest.raises(WorkflowError, match="uninitialized"):
            workflow.require(ReviewState.APPROVED, action="publish")
        workflow.record(ReviewState.IMPORTED, by="i")
        with pytest.raises(WorkflowError, match="requires review state"):
            workflow.require(ReviewState.APPROVED, action="publish")
        with pytest.raises(WorkflowError, match="no approval"):
            workflow.approval()

    def test_corrupt_record_is_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "metadata" / "review.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        with pytest.raises(WorkflowError, match="corrupt"):
            ReviewWorkflow(tmp_path).state()
