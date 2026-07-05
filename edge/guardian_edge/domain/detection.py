"""Detection domain model: what the vision system says about a frame.

Pure Python. Knows nothing about models, inference runtimes, or what
downstream engines (tracking, risk analysis, notification) do with
detections.

Identity (ADR-0007): every Detection is self-contained — it carries its own
UUID plus the frame id, camera id, capture timestamp, and correlation id it
belongs to, so downstream systems (tracking, risk engine, analytics,
notifications) can queue, store, and join detections without needing the
originating objects. ``DetectionResult`` enforces that all its detections
agree with its own identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from guardian_edge.domain.errors import VisionConfigurationError


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in normalized image coordinates.

    All values are fractions of frame size in [0, 1], origin at the top-left
    (ADR-0006): detections stay valid across stream resolutions and are
    model- and renderer-independent.
    """

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
            raise VisionConfigurationError(f"box origin out of range: ({self.x}, {self.y})")
        if self.width <= 0.0 or self.height <= 0.0:
            raise VisionConfigurationError(f"box size must be positive: {self.width}x{self.height}")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise VisionConfigurationError(
                f"box exceeds frame bounds: ({self.x}+{self.width}, {self.y}+{self.height})"
            )

    def intersection_over_union(self, other: BoundingBox) -> float:
        """IoU with another box, in [0, 1]. Basis for NMS and future tracking."""
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.x + self.width, other.x + other.width)
        bottom = min(self.y + self.height, other.y + other.height)
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        union = self.width * self.height + other.width * other.height - intersection
        return intersection / union

    def to_pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        """Corner coordinates ``(x1, y1, x2, y2)`` in pixels, clamped to the frame."""
        x1 = round(self.x * frame_width)
        y1 = round(self.y * frame_height)
        x2 = round((self.x + self.width) * frame_width)
        y2 = round((self.y + self.height) * frame_height)
        return (
            max(x1, 0),
            max(y1, 0),
            min(x2, frame_width - 1),
            min(y2, frame_height - 1),
        )


@dataclass(frozen=True, slots=True)
class Detection:
    """One detected object in one frame, self-contained for downstream use."""

    detection_id: UUID
    """Unique identity of this single detection."""

    frame_id: UUID
    """The captured frame this detection was found in."""

    camera_id: str
    """The camera that captured the frame."""

    captured_at: datetime
    """When the frame was captured (UTC)."""

    correlation_id: UUID
    """Trace token of the capture's processing chain — propagate, never regenerate."""

    label: str
    confidence: float
    box: BoundingBox

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise VisionConfigurationError("detection label must not be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise VisionConfigurationError(f"confidence out of range: {self.confidence}")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Identity of the model that produced a result.

    Carried on every DetectionResult so each downstream decision remains
    traceable to a named, versioned model (docs/04, transparency).
    """

    name: str
    version: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Everything the vision system concluded about one frame."""

    camera_id: str
    frame_id: UUID
    frame_sequence: int
    captured_at: datetime
    correlation_id: UUID
    detections: tuple[Detection, ...]
    model: ModelDescriptor
    inference_ms: float

    def __post_init__(self) -> None:
        for detection in self.detections:
            if (
                detection.frame_id != self.frame_id
                or detection.camera_id != self.camera_id
                or detection.correlation_id != self.correlation_id
            ):
                raise VisionConfigurationError(
                    f"detection {detection.detection_id} does not belong to "
                    f"frame {self.frame_id} (camera '{self.camera_id}')"
                )
