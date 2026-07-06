"""Guardian video annotation format: malformed input is rejected, always."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from guardian_ai.acquisition.annotations import (
    ClipAnnotation,
    EventSpan,
    FrameAnnotation,
    FrameBox,
    annotation_from_dict,
    load_annotation,
    save_annotation,
    validate_annotation,
)
from guardian_ai.acquisition.errors import AnnotationFormatError

VALID = ClipAnnotation(
    clip_id="clip-001",
    fps=15.0,
    width=640,
    height=480,
    frame_count=60,
    frames=(FrameAnnotation(index=3, boxes=(FrameBox("person", (0.1, 0.1, 0.3, 0.5)),)),),
    events=(EventSpan("fall", 10, 20, 0.9),),
)


def test_valid_annotation_passes() -> None:
    validate_annotation(VALID)


def test_roundtrip_save_load(tmp_path: Path) -> None:
    path = tmp_path / "clip-001.json"
    save_annotation(VALID, path)
    loaded = load_annotation(path)
    assert loaded == VALID


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (dict(clip_id="  "), "clip_id"),
        (dict(fps=0.0), "fps"),
        (dict(fps=float("nan")), "fps"),
        (dict(width=0), "width"),
        (dict(frame_count=0), "frame_count"),
        (dict(events=(EventSpan("fall", 50, 70),)), "invalid timestamps"),
        (dict(events=(EventSpan("fall", 20, 10),)), "starts after"),
        (dict(events=(EventSpan("fall", -1, 10),)), "invalid timestamps"),
        (dict(events=(EventSpan("person", 1, 2),)), "not an event label"),
        (dict(events=(EventSpan("fall", 1, 2, confidence=1.5),)), "confidence"),
    ],
)
def test_malformed_clip_fields_rejected(mutation: dict, message: str) -> None:
    with pytest.raises(AnnotationFormatError, match=message):
        validate_annotation(replace(VALID, **mutation))


@pytest.mark.parametrize(
    ("box", "message"),
    [
        (FrameBox("fall", (0.1, 0.1, 0.2, 0.2)), "not a box label"),
        (FrameBox("person", (0.9, 0.1, 0.3, 0.2)), "escapes"),
        (FrameBox("person", (-0.1, 0.1, 0.3, 0.2)), "escapes"),
        (FrameBox("person", (0.1, 0.1, 0.0, 0.2)), "broken box"),
        (FrameBox("person", (0.1, 0.1, float("inf"), 0.2)), "non-finite"),
        (FrameBox("person", (0.1, 0.1, 0.2, 0.2), confidence=2.0), "confidence"),
    ],
)
def test_broken_boxes_rejected(box: FrameBox, message: str) -> None:
    broken = replace(VALID, frames=(FrameAnnotation(index=1, boxes=(box,)),))
    with pytest.raises(AnnotationFormatError, match=message):
        validate_annotation(broken)


def test_frame_index_bounds_and_duplicates() -> None:
    with pytest.raises(AnnotationFormatError, match="outside clip"):
        validate_annotation(replace(VALID, frames=(FrameAnnotation(index=60),)))
    with pytest.raises(AnnotationFormatError, match="duplicate frame"):
        validate_annotation(
            replace(VALID, frames=(FrameAnnotation(index=1), FrameAnnotation(index=1)))
        )


def test_save_refuses_malformed(tmp_path: Path) -> None:
    with pytest.raises(AnnotationFormatError):
        save_annotation(replace(VALID, fps=-1.0), tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()


def test_from_dict_rejects_wrong_schema_and_garbage() -> None:
    with pytest.raises(AnnotationFormatError, match="schema"):
        annotation_from_dict({"schema": "coco/1"})
    with pytest.raises(AnnotationFormatError, match="malformed"):
        annotation_from_dict({"schema": "guardian-video-annotation/1", "clip_id": "x"})


def test_load_rejects_unreadable(tmp_path: Path) -> None:
    with pytest.raises(AnnotationFormatError, match="cannot read"):
        load_annotation(tmp_path / "absent.json")
    (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(AnnotationFormatError, match="cannot read"):
        load_annotation(tmp_path / "broken.json")


def test_to_dict_from_dict_roundtrip_with_track() -> None:
    tracked = replace(
        VALID,
        frames=(
            FrameAnnotation(
                index=2,
                boxes=(FrameBox("child", (0.2, 0.2, 0.2, 0.2), 0.8, track="t-7"),),
            ),
        ),
    )
    assert annotation_from_dict(tracked.to_dict()) == tracked
