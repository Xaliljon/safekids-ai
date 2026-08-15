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
