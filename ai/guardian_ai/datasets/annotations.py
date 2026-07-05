"""Guardian annotation format: JSON Lines, one sample per line.

Boxes use the platform-wide convention (ADR-0006/ADR-0010): normalized
[0, 1] coordinates, top-left origin — resolution-independent and identical
to what the edge vision pipeline emits, so datasets and detections speak
one geometry.

A sample line:

    {"path": "images/000001.jpg", "width": 1920, "height": 1080,
     "annotations": [{"label": "child",
                      "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                      "attributes": {"occluded": "partial"}}],
     "attributes": {"scene": "classroom"}}

``path`` is the sample's identity: always relative (media live in
DVC-managed storage next to the annotations, never in git). Attributes are
free string-to-string pairs — the privacy checker forbids identity-bearing
keys and values.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_ai.datasets.errors import AnnotationError


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box, normalized [0, 1], top-left origin."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
            raise AnnotationError(f"box origin out of range: ({self.x}, {self.y})")
        if self.width <= 0.0 or self.height <= 0.0:
            raise AnnotationError(f"box size must be positive: {self.width}x{self.height}")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise AnnotationError(
                f"box exceeds bounds: ({self.x}+{self.width}, {self.y}+{self.height})"
            )

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class Annotation:
    """One labeled region in one sample."""

    label: str
    box: BoundingBox
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise AnnotationError("annotation label must not be empty")


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """One media sample plus its annotations. ``path`` is its identity."""

    path: str
    width: int
    height: int
    annotations: tuple[Annotation, ...] = ()
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise AnnotationError("sample path must not be empty")
        if self.width < 1 or self.height < 1:
            raise AnnotationError(f"'{self.path}': dimensions must be positive")


def read_records(path: Path) -> list[SampleRecord]:
    """Parse a JSONL annotation file strictly; errors carry line numbers."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AnnotationError(f"cannot read annotations '{path}': {exc}") from exc
    records = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(_record_from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AnnotationError) as exc:
            raise AnnotationError(f"{path}:{line_number}: {exc}") from exc
    return records


def write_records(path: Path, records: Iterable[SampleRecord]) -> None:
    lines = [json.dumps(_record_to_dict(record), sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _record_from_dict(raw: Any) -> SampleRecord:
    if not isinstance(raw, dict):
        raise AnnotationError("record must be a JSON object")
    annotations = tuple(
        Annotation(
            label=str(entry["label"]),
            box=BoundingBox(
                x=float(entry["box"]["x"]),
                y=float(entry["box"]["y"]),
                width=float(entry["box"]["width"]),
                height=float(entry["box"]["height"]),
            ),
            attributes=_string_mapping(entry.get("attributes", {})),
        )
        for entry in raw.get("annotations", [])
    )
    return SampleRecord(
        path=str(raw["path"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        annotations=annotations,
        attributes=_string_mapping(raw.get("attributes", {})),
    )


def _record_to_dict(record: SampleRecord) -> dict[str, Any]:
    return {
        "path": record.path,
        "width": record.width,
        "height": record.height,
        "annotations": [
            {
                "label": annotation.label,
                "box": {
                    "x": annotation.box.x,
                    "y": annotation.box.y,
                    "width": annotation.box.width,
                    "height": annotation.box.height,
                },
                "attributes": dict(annotation.attributes),
            }
            for annotation in record.annotations
        ],
        "attributes": dict(record.attributes),
    }


def _string_mapping(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise AnnotationError("attributes must be an object of strings")
    return {str(key): str(value) for key, value in raw.items()}
