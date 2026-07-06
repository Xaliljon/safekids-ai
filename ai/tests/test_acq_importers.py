"""Importers: documented raw layouts in, guardian_dataset_v1 out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from acquisition_fixtures import (
    build_gmdcsa24_raw,
    build_le2i_raw,
    build_urfall_raw,
    make_manifest,
)

from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers import available_importers, get_importer
from guardian_ai.acquisition.importers.base import run_import
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.workspace import DatasetWorkspace


def make_workspace(tmp_path: Path) -> DatasetWorkspace:
    return DatasetWorkspace.create(tmp_path / "ws", make_manifest())


def test_registry_of_importers() -> None:
    assert available_importers() == ["gmdcsa24", "le2i", "urfall"]
    with pytest.raises(ImporterError, match="unknown dataset source"):
        get_importer("kinetics")


def test_urfall_import(tmp_path: Path) -> None:
    raw = build_urfall_raw(tmp_path / "raw")
    workspace = make_workspace(tmp_path)
    result = run_import(get_importer("urfall"), raw, workspace)
    assert sorted(result.imported) == ["urfall-adl-01-cam0", "urfall-fall-01-cam0"]

    fall = workspace.annotation("urfall-fall-01-cam0")
    labels = [event.label for event in fall.events]
    assert "fall" in labels and "lying" in labels
    # CSV frames are 30fps; the normalized clip is 15fps — spans must be mapped
    fall_event = next(event for event in fall.events if event.label == "fall")
    assert 0 <= fall_event.start_frame <= fall_event.end_frame < fall.frame_count

    adl = workspace.annotation("urfall-adl-01-cam0")
    assert adl.events == ()  # -1 labels only -> no events
    assert ReviewWorkflow(workspace.root).state() is ReviewState.IMPORTED


def test_urfall_rejects_broken_csv_and_missing_media(tmp_path: Path) -> None:
    raw = build_urfall_raw(tmp_path / "raw")
    (raw / "urfall-cam0-falls.csv").write_text("fall-01-cam0,notanumber,1\n")
    with pytest.raises(ImporterError, match="malformed CSV"):
        run_import(get_importer("urfall"), raw, make_workspace(tmp_path))

    raw2 = build_urfall_raw(tmp_path / "raw2")
    (raw2 / "videos" / "fall-01-cam0.mp4").unlink()
    with pytest.raises(ImporterError, match="no video"):
        run_import(get_importer("urfall"), raw2, make_workspace(tmp_path / "b"))


def test_le2i_import_boxes_and_fall(tmp_path: Path) -> None:
    raw = build_le2i_raw(tmp_path / "raw")
    workspace = make_workspace(tmp_path)
    result = run_import(get_importer("le2i"), raw, workspace)
    assert result.imported == ["le2i-coffee-room-video-1"]
    annotation = workspace.annotation(result.imported[0])
    assert annotation.events and annotation.events[0].label == "fall"
    assert annotation.frames, "pixel boxes must convert to normalized person boxes"
    for frame in annotation.frames:
        for box in frame.boxes:
            assert box.label == "person"
            x, y, w, h = box.box
            assert x >= 0 and y >= 0 and x + w <= 1.0 + 1e-6 and y + h <= 1.0 + 1e-6


def test_le2i_rejects_missing_annotation_file(tmp_path: Path) -> None:
    raw = build_le2i_raw(tmp_path / "raw")
    (raw / "Coffee_room" / "Annotation_files" / "video (1).txt").unlink()
    with pytest.raises(ImporterError, match="Annotation_files"):
        run_import(get_importer("le2i"), raw, make_workspace(tmp_path))


def test_gmdcsa24_import(tmp_path: Path) -> None:
    raw = build_gmdcsa24_raw(tmp_path / "raw")
    workspace = make_workspace(tmp_path)
    result = run_import(get_importer("gmdcsa24"), raw, workspace)
    assert sorted(result.imported) == [
        "gmdcsa24-adl-subject1-a1",
        "gmdcsa24-fall-subject1-f1",
    ]
    fall = workspace.annotation("gmdcsa24-fall-subject1-f1")
    assert fall.events[0].label == "fall"


def test_gmdcsa24_rejects_unannotated_fall_clip(tmp_path: Path) -> None:
    raw = build_gmdcsa24_raw(tmp_path / "raw")
    (raw / "annotations.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ImporterError, match="unannotated falls are rejected"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path))


def test_gmdcsa24_rejects_bad_segments(tmp_path: Path) -> None:
    raw = build_gmdcsa24_raw(tmp_path / "raw")
    (raw / "annotations.json").write_text(
        json.dumps({"Fall/Subject1/F1.mp4": [{"label": "sprinting", "start_s": 0, "end_s": 1}]})
    )
    with pytest.raises(ImporterError, match="not a Guardian event label"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path))


def test_import_refuses_missing_and_empty_raw(tmp_path: Path) -> None:
    with pytest.raises(ImporterError, match="missing"):
        run_import(get_importer("urfall"), tmp_path / "absent", make_workspace(tmp_path))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ImporterError):
        run_import(get_importer("urfall"), empty, make_workspace(tmp_path / "b"))


def test_metadata_records_provenance(tmp_path: Path) -> None:
    raw = build_urfall_raw(tmp_path / "raw")
    workspace = make_workspace(tmp_path)
    run_import(get_importer("urfall"), raw, workspace)
    metadata = workspace.metadata("urfall-fall-01-cam0")
    assert metadata["source_dataset"] == "urfall"
    assert "license_note" in metadata
    assert metadata["normalized"]["fps"] == 15
    assert metadata["attr_camera_angle"] == "side"


def test_le2i_rejects_malformed_annotation_lines(tmp_path: Path) -> None:
    raw = build_le2i_raw(tmp_path / "raw")
    annotation = raw / "Coffee_room" / "Annotation_files" / "video (1).txt"
    annotation.write_text("16\n21\n5,1,2,3\n")  # 4 fields, not 5
    with pytest.raises(ImporterError, match="malformed box line"):
        run_import(get_importer("le2i"), raw, make_workspace(tmp_path))

    annotation.write_text("16\n21\n5,a,b,c,d\n")
    with pytest.raises(ImporterError, match="non-numeric box line"):
        run_import(get_importer("le2i"), raw, make_workspace(tmp_path / "b"))

    annotation.write_text("16\n")  # missing the end line
    with pytest.raises(ImporterError, match="start/end"):
        run_import(get_importer("le2i"), raw, make_workspace(tmp_path / "c"))

    annotation.write_text("start\nend\n")
    with pytest.raises(ImporterError, match="non-numeric fall frames"):
        run_import(get_importer("le2i"), raw, make_workspace(tmp_path / "d"))


def test_le2i_no_fall_when_zero_markers(tmp_path: Path) -> None:
    raw = build_le2i_raw(tmp_path / "raw")
    annotation = raw / "Coffee_room" / "Annotation_files" / "video (1).txt"
    lines = annotation.read_text().splitlines()
    lines[0], lines[1] = "0", "0"  # Le2i convention: no fall in this clip
    annotation.write_text("\n".join(lines) + "\n")
    workspace = make_workspace(tmp_path)
    run_import(get_importer("le2i"), raw, workspace)
    assert workspace.annotation("le2i-coffee-room-video-1").events == ()


def test_gmdcsa24_rejects_broken_annotations_json(tmp_path: Path) -> None:
    raw = build_gmdcsa24_raw(tmp_path / "raw")
    (raw / "annotations.json").write_text("{broken")
    with pytest.raises(ImporterError, match="not valid JSON"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path))

    (raw / "annotations.json").write_text("[1, 2]")
    with pytest.raises(ImporterError, match="must map"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path / "b"))


def test_gmdcsa24_rejects_invalid_segment_times_and_shape(tmp_path: Path) -> None:
    raw = build_gmdcsa24_raw(tmp_path / "raw")
    (raw / "annotations.json").write_text(
        json.dumps({"Fall/Subject1/F1.mp4": [{"label": "fall", "start_s": 2.0, "end_s": 1.0}]})
    )
    with pytest.raises(ImporterError, match="invalid"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path))

    (raw / "annotations.json").write_text(json.dumps({"Fall/Subject1/F1.mp4": [{"label": "fall"}]}))
    with pytest.raises(ImporterError, match="malformed segment"):
        run_import(get_importer("gmdcsa24"), raw, make_workspace(tmp_path / "b"))
