"""Split grouping: the defect the candidate provenance review found by hand.

Splitting by clip put all four Le2i scenes in both train and val, so
``val_f1`` reached 1.0 at epoch 3 measuring same-room recognition. These
tests hold the mechanism that makes that impossible to reintroduce.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from acquisition_fixtures import (
    build_gmdcsa24_raw,
    build_le2i_raw,
    build_urfall_raw,
    make_manifest,
)

from guardian_ai.acquisition.annotations import ClipAnnotation
from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.importers.base import DatasetImporter
from guardian_ai.acquisition.importers.gmdcsa24 import Gmdcsa24Importer
from guardian_ai.acquisition.importers.le2i import Le2iImporter
from guardian_ai.acquisition.importers.urfall import UrFallImporter
from guardian_ai.acquisition.workspace import DatasetWorkspace


@pytest.fixture
def workspace(tmp_path: Path) -> DatasetWorkspace:
    return DatasetWorkspace.create(tmp_path / "ws", make_manifest())


def _add(workspace: DatasetWorkspace, clip_id: str, group: str | None) -> str:
    video = workspace.root / f"{clip_id}.mp4"
    video.write_bytes(b"not-really-a-video")
    return workspace.add_clip(
        clip_id,
        video,
        ClipAnnotation(clip_id=clip_id, fps=10.0, frame_count=1, width=64, height=64),
        {"source_dataset": "test"},
        split_group=group,
    )


def test_clips_sharing_a_group_land_in_the_same_split(workspace: DatasetWorkspace) -> None:
    splits = {
        clip: _add(workspace, clip, "home-01")
        for clip in ("le2i-home-01-a", "le2i-home-01-b", "le2i-home-01-c")
    }
    assert len(set(splits.values())) == 1


def test_different_groups_are_assigned_independently(workspace: DatasetWorkspace) -> None:
    for scene in ("coffee-room-01", "coffee-room-02", "home-01", "home-02"):
        _add(workspace, f"le2i-{scene}-a", scene)
    assert workspace.straddling_groups() == {}


def test_no_group_falls_back_to_the_clip_id(workspace: DatasetWorkspace) -> None:
    """Unchanged behaviour for sources where every clip is independent."""
    split = _add(workspace, "solo-clip", None)
    assert split in {"train", "val", "test"}
    assert workspace.split_groups() == {}


def test_straddling_groups_reports_a_leak(workspace: DatasetWorkspace) -> None:
    """Hand-write the pre-fix layout and confirm the check catches it."""
    _add(workspace, "le2i-home-01-a", "home-01")
    other = "val" if workspace.split_of("le2i-home-01-a") != "val" else "test"
    with (workspace.root / other / "clips.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"clip_id": "le2i-home-01-b", "split_group": "home-01"}) + "\n")
    assert workspace.straddling_groups() == {
        "home-01": sorted({workspace.split_of("le2i-home-01-a"), other})
    }


def test_group_survives_a_reopened_workspace(workspace: DatasetWorkspace) -> None:
    _add(workspace, "le2i-home-01-a", "home-01")
    reopened = DatasetWorkspace.open(workspace.root)
    assert reopened.split_groups() == {"le2i-home-01-a": "home-01"}


@pytest.mark.parametrize(
    ("importer", "build_raw"),
    [
        (Le2iImporter(), build_le2i_raw),
        (UrFallImporter(), build_urfall_raw),
        (Gmdcsa24Importer(), build_gmdcsa24_raw),
    ],
    ids=["le2i", "urfall", "gmdcsa24"],
)
def test_every_shipped_importer_declares_a_group(
    importer: DatasetImporter, build_raw: Callable[[Path], Path], tmp_path: Path
) -> None:
    """A fixed-camera corpus with no declared group silently reintroduces
    the leak, so its absence must fail here rather than in a metric nobody
    questions for three sprints."""
    clips = importer.discover(build_raw(tmp_path / "raw"))
    assert clips
    assert all(clip.split_group for clip in clips), importer.source


def test_le2i_groups_by_scene_not_by_clip(tmp_path: Path) -> None:
    """The specific fix. Two clips filmed in one room share a group."""
    clips = Le2iImporter().discover(build_le2i_raw(tmp_path / "raw"))
    for clip in clips:
        assert clip.split_group == clip.attributes["scene"]


# ------------------------------------------------------------- split pins


def test_pin_before_import_overrides_the_hash(workspace: DatasetWorkspace) -> None:
    """Holding a whole corpus out as test is an experiment design, not a
    split — a hash deciding it would throw away the only generalization
    measurement available."""
    workspace.pin_split_group("urfall", "test", reason="held-out domain", by="Lead")
    assert _add(workspace, "urfall-fall-01", "urfall") == "test"
    assert _add(workspace, "urfall-adl-01", "urfall") == "test"


def test_pin_after_import_moves_the_clips(workspace: DatasetWorkspace) -> None:
    """Split membership is a metadata list, so pinning works post-import.
    Pinned to whichever split the hash did *not* choose, so the move is real."""
    natural = _add(workspace, "urfall-fall-01", "urfall")
    _add(workspace, "urfall-adl-01", "urfall")
    target = next(name for name in ("test", "val", "train") if name != natural)

    moved = workspace.pin_split_group("urfall", target, reason="held-out domain", by="Lead")

    assert sorted(moved) == ["urfall-adl-01", "urfall-fall-01"]
    assert workspace.split_of("urfall-fall-01") == target
    assert workspace.split_of("urfall-adl-01") == target
    assert workspace.straddling_groups() == {}
    # The media never moved; only the membership list was rewritten.
    assert workspace.video_path("urfall-fall-01").is_file()


def test_pin_records_who_and_why(workspace: DatasetWorkspace) -> None:
    """An unexplained pin cannot be told apart from a mistake."""
    workspace.pin_split_group(
        "urfall", "test", reason="different lab, room and subjects", by="Lead Architect"
    )
    recorded = json.loads((workspace.root / "metadata" / "split-pins.json").read_text())
    assert recorded["pins"] == {"urfall": "test"}
    assert recorded["history"][0]["reason"] == "different lab, room and subjects"
    assert recorded["history"][0]["by"] == "Lead Architect"


def test_pin_refuses_without_a_reason_or_a_person(workspace: DatasetWorkspace) -> None:
    for reason, by in (("", "Lead"), ("held out", "  ")):
        with pytest.raises(AcquisitionError, match="reason and a person"):
            workspace.pin_split_group("urfall", "test", reason=reason, by=by)
    assert workspace.split_pins() == {}


def test_pin_refuses_an_unknown_split(workspace: DatasetWorkspace) -> None:
    with pytest.raises(AcquisitionError, match="unknown split"):
        workspace.pin_split_group("urfall", "holdout", reason="r", by="Lead")


def test_unpinned_groups_still_hash(workspace: DatasetWorkspace) -> None:
    """The exception must not become the rule."""
    workspace.pin_split_group("urfall", "test", reason="held-out domain", by="Lead")
    for scene in ("coffee-room-01", "coffee-room-02", "home-01", "home-02"):
        _add(workspace, f"le2i-{scene}-a", scene)
    le2i_splits = {
        workspace.split_of(f"le2i-{scene}-a")
        for scene in ("coffee-room-01", "coffee-room-02", "home-01", "home-02")
    }
    assert le2i_splits != {"test"}
    assert workspace.split_pins() == {"urfall": "test"}


def test_repinning_moves_again_and_keeps_the_history(workspace: DatasetWorkspace) -> None:
    _add(workspace, "urfall-fall-01", "urfall")
    workspace.pin_split_group("urfall", "val", reason="first call", by="Lead")
    workspace.pin_split_group("urfall", "test", reason="reconsidered", by="Lead")
    assert workspace.split_of("urfall-fall-01") == "test"
    recorded = json.loads((workspace.root / "metadata" / "split-pins.json").read_text())
    assert [entry["reason"] for entry in recorded["history"]] == ["first call", "reconsidered"]


def test_pins_and_leaks_are_reported_in_statistics(workspace: DatasetWorkspace) -> None:
    """A held-out corpus makes the test number mean something different, and
    a reader comparing two reports cannot know unless the report says so."""
    from guardian_ai.acquisition.statistics import compute_statistics

    workspace.pin_split_group("urfall", "test", reason="held-out domain", by="Lead")
    _add(workspace, "urfall-fall-01", "urfall")
    _add(workspace, "le2i-home-01-a", "home-01")

    statistics = compute_statistics(workspace)

    assert statistics["split_pins"] == {"urfall": "test"}
    assert statistics["split_groups"] == ["home-01", "urfall"]
    assert statistics["straddling_groups"] == {}
