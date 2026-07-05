"""Annotation format: validation and JSONL round-trip."""

from pathlib import Path

import pytest
from dataset_fixtures import make_record

from guardian_ai.datasets.annotations import (
    Annotation,
    BoundingBox,
    SampleRecord,
    read_records,
    write_records,
)
from guardian_ai.datasets.errors import AnnotationError


def test_jsonl_round_trip(tmp_path: Path) -> None:
    records = [
        make_record("images/a.jpg", labels=("child", "adult")),
        make_record("images/b.jpg", labels=(), attributes={"scene": "playground"}),
    ]
    path = tmp_path / "train.jsonl"
    write_records(path, records)
    loaded = read_records(path)
    assert loaded == records


def test_parse_error_carries_line_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    good = '{"path": "images/a.jpg", "width": 100, "height": 100, "annotations": []}'
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    with pytest.raises(AnnotationError, match="bad.jsonl:2"):
        read_records(path)


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "train.jsonl"
    write_records(path, [make_record()])
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert len(read_records(path)) == 1


@pytest.mark.parametrize(
    ("x", "y", "width", "height"),
    [(-0.1, 0.0, 0.5, 0.5), (0.0, 0.0, 0.0, 0.5), (0.8, 0.0, 0.3, 0.5)],
)
def test_rejects_invalid_boxes(x: float, y: float, width: float, height: float) -> None:
    with pytest.raises(AnnotationError):
        BoundingBox(x=x, y=y, width=width, height=height)


def test_rejects_blank_label() -> None:
    with pytest.raises(AnnotationError):
        Annotation(label=" ", box=BoundingBox(x=0.1, y=0.1, width=0.2, height=0.2))


def test_rejects_invalid_sample_dimensions() -> None:
    with pytest.raises(AnnotationError):
        SampleRecord(path="images/a.jpg", width=0, height=100)


def test_rejects_empty_path() -> None:
    with pytest.raises(AnnotationError):
        SampleRecord(path="  ", width=100, height=100)
