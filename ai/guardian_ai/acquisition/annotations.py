"""Guardian Video Annotation Format v1 — one JSON per clip, validated hard.

Every source annotation (UR Fall CSV, Le2i txt, GMDCSA24 JSON, pilot
evidence, the annotation tool) converges on this shape:

    {
      "schema": "guardian-video-annotation/1",
      "clip_id": "urfall-fall-01-cam0",
      "fps": 15.0, "width": 640, "height": 480, "frame_count": 90,
      "taxonomy": {"name": "guardian-video-safety", "version": "1.0.0"},
      "frames": [{"index": 12, "boxes": [
          {"label": "person", "box": [x, y, w, h], "confidence": 1.0,
           "track": "optional-source-track"}]}],
      "events": [{"label": "fall", "start_frame": 30, "end_frame": 45,
                  "confidence": 1.0}]
    }

Geometry is normalized [0,1], top-left origin — the ADR-0010 convention.
Malformed annotations are rejected, never repaired silently.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.errors import AnnotationFormatError
from guardian_ai.acquisition.taxonomy import (
    GUARDIAN_VIDEO_TAXONOMY_V1,
    is_box_label,
    is_event_label,
)

SCHEMA = "guardian-video-annotation/1"


@dataclass(frozen=True, slots=True)
class FrameBox:
    """One object in one frame; geometry normalized, top-left origin."""

    label: str
    box: tuple[float, float, float, float]  # x, y, w, h in [0, 1]
    confidence: float = 1.0
    track: str | None = None


@dataclass(frozen=True, slots=True)
class FrameAnnotation:
    index: int
    boxes: tuple[FrameBox, ...] = ()


@dataclass(frozen=True, slots=True)
class EventSpan:
    """A labelled time span, in frames of the normalized clip."""

    label: str
    start_frame: int
    end_frame: int
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ClipAnnotation:
    """The complete Guardian annotation for one normalized clip."""

    clip_id: str
    fps: float
    width: int
    height: int
    frame_count: int
    frames: tuple[FrameAnnotation, ...] = ()
    events: tuple[EventSpan, ...] = ()
    taxonomy_name: str = GUARDIAN_VIDEO_TAXONOMY_V1.name
    taxonomy_version: str = GUARDIAN_VIDEO_TAXONOMY_V1.version
    attributes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "clip_id": self.clip_id,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "taxonomy": {"name": self.taxonomy_name, "version": self.taxonomy_version},
            "frames": [
                {
                    "index": frame.index,
                    "boxes": [
                        {
                            "label": box.label,
                            "box": list(box.box),
                            "confidence": box.confidence,
                            **({"track": box.track} if box.track else {}),
                        }
                        for box in frame.boxes
                    ],
                }
                for frame in self.frames
            ],
            "events": [
                {
                    "label": event.label,
                    "start_frame": event.start_frame,
                    "end_frame": event.end_frame,
                    "confidence": event.confidence,
                }
                for event in self.events
            ],
            "attributes": self.attributes,
        }


def validate_annotation(annotation: ClipAnnotation) -> None:
    """Reject anything malformed. No silent repair, ever."""
    where = f"clip '{annotation.clip_id}'"
    if not annotation.clip_id.strip():
        raise AnnotationFormatError("clip_id must not be empty")
    if not (math.isfinite(annotation.fps) and annotation.fps > 0):
        raise AnnotationFormatError(f"{where}: fps must be positive, got {annotation.fps}")
    if annotation.width <= 0 or annotation.height <= 0:
        raise AnnotationFormatError(f"{where}: width/height must be positive")
    if annotation.frame_count <= 0:
        raise AnnotationFormatError(f"{where}: frame_count must be positive")

    seen_frames: set[int] = set()
    for frame in annotation.frames:
        if not 0 <= frame.index < annotation.frame_count:
            raise AnnotationFormatError(
                f"{where}: frame index {frame.index} outside clip "
                f"(frame_count={annotation.frame_count})"
            )
        if frame.index in seen_frames:
            raise AnnotationFormatError(f"{where}: duplicate frame annotation {frame.index}")
        seen_frames.add(frame.index)
        for box in frame.boxes:
            _validate_box(where, frame.index, box)

    for event in annotation.events:
        if not is_event_label(event.label):
            raise AnnotationFormatError(
                f"{where}: '{event.label}' is not an event label of "
                f"{annotation.taxonomy_name}@{annotation.taxonomy_version}"
            )
        if event.start_frame < 0 or event.end_frame >= annotation.frame_count:
            raise AnnotationFormatError(
                f"{where}: event '{event.label}' [{event.start_frame}, {event.end_frame}] "
                f"outside clip (frame_count={annotation.frame_count}) — invalid timestamps"
            )
        if event.start_frame > event.end_frame:
            raise AnnotationFormatError(
                f"{where}: event '{event.label}' starts after it ends "
                f"({event.start_frame} > {event.end_frame})"
            )
        if not 0.0 <= event.confidence <= 1.0:
            raise AnnotationFormatError(
                f"{where}: event confidence {event.confidence} outside [0, 1]"
            )


def _validate_box(where: str, frame_index: int, box: FrameBox) -> None:
    if not is_box_label(box.label):
        raise AnnotationFormatError(
            f"{where}: frame {frame_index}: '{box.label}' is not a box label"
        )
    x, y, w, h = box.box
    values = (x, y, w, h)
    if any(not math.isfinite(value) for value in values):
        raise AnnotationFormatError(f"{where}: frame {frame_index}: non-finite box")
    if w <= 0 or h <= 0:
        raise AnnotationFormatError(
            f"{where}: frame {frame_index}: broken box (non-positive size {w}x{h})"
        )
    if x < 0 or y < 0 or x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
        raise AnnotationFormatError(
            f"{where}: frame {frame_index}: box [{x}, {y}, {w}, {h}] escapes [0, 1]"
        )
    if not 0.0 <= box.confidence <= 1.0:
        raise AnnotationFormatError(
            f"{where}: frame {frame_index}: confidence {box.confidence} outside [0, 1]"
        )


def save_annotation(annotation: ClipAnnotation, path: Path) -> None:
    validate_annotation(annotation)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(annotation.to_dict(), indent=2), encoding="utf-8")
    temp.replace(path)


def load_annotation(path: Path) -> ClipAnnotation:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationFormatError(f"cannot read annotation '{path}': {exc}") from exc
    return annotation_from_dict(raw, source=str(path))


def annotation_from_dict(raw: dict[str, Any], source: str = "<dict>") -> ClipAnnotation:
    if raw.get("schema") != SCHEMA:
        raise AnnotationFormatError(f"{source}: schema '{raw.get('schema')}' is not '{SCHEMA}'")
    try:
        annotation = ClipAnnotation(
            clip_id=str(raw["clip_id"]),
            fps=float(raw["fps"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
            frame_count=int(raw["frame_count"]),
            taxonomy_name=str(raw["taxonomy"]["name"]),
            taxonomy_version=str(raw["taxonomy"]["version"]),
            frames=tuple(
                FrameAnnotation(
                    index=int(frame["index"]),
                    boxes=tuple(
                        FrameBox(
                            label=str(box["label"]),
                            box=(
                                float(box["box"][0]),
                                float(box["box"][1]),
                                float(box["box"][2]),
                                float(box["box"][3]),
                            ),
                            confidence=float(box.get("confidence", 1.0)),
                            track=(str(box["track"]) if box.get("track") else None),
                        )
                        for box in frame.get("boxes", ())
                    ),
                )
                for frame in raw.get("frames", ())
            ),
            events=tuple(
                EventSpan(
                    label=str(event["label"]),
                    start_frame=int(event["start_frame"]),
                    end_frame=int(event["end_frame"]),
                    confidence=float(event.get("confidence", 1.0)),
                )
                for event in raw.get("events", ())
            ),
            attributes={str(k): str(v) for k, v in raw.get("attributes", {}).items()},
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise AnnotationFormatError(f"{source}: malformed annotation: {exc}") from exc
    validate_annotation(annotation)
    return annotation
