"""Multi-object tracking domain model.

A Track is a persistent identity for one physical object observed across
frames. Tracks preserve the ADR-0007 chain: every track carries the full
Detection that last evidenced it (detection_id, frame_id, camera_id,
captured_at, correlation_id), and every TrackingResult propagates the
frame identity of the DetectionResult it was computed from — minted at
source, propagated, never regenerated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, unique
from uuid import UUID

from guardian_edge.domain.detection import BoundingBox, Detection, ModelDescriptor
from guardian_edge.domain.errors import VisionConfigurationError


@unique
class TrackState(Enum):
    """Track lifecycle (ADR-0011).

    TENTATIVE — newly spawned; not yet trusted (needs consecutive hits).
    CONFIRMED — established identity; what downstream consumers act on.
    LOST      — confirmed track currently unmatched; position is predicted.
    REMOVED   — gone for too long (or never confirmed); terminal.
    """

    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST = "lost"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class Track:
    """Point-in-time snapshot of one tracked object."""

    track_id: UUID
    """Stable identity of this track across frames (minted at track birth)."""

    display_id: int
    """Short human-facing id for overlays and logs ("#7"); unique per tracker."""

    camera_id: str
    state: TrackState
    label: str
    confidence: float
    """Confidence of the most recent associated detection."""

    box: BoundingBox
    """Current position estimate (measured or predicted while LOST)."""

    last_detection: Detection
    """The full detection that last evidenced this track (ADR-0007 identity)."""

    hits: int
    """Total frames with an associated detection."""

    age_frames: int
    """Frames since the track was born."""

    frames_since_update: int
    """0 when matched this frame; grows while LOST."""

    first_seen_at: datetime
    last_seen_at: datetime

    def __post_init__(self) -> None:
        if self.last_detection.camera_id != self.camera_id:
            raise VisionConfigurationError(
                f"track {self.display_id}: detection from camera "
                f"'{self.last_detection.camera_id}' cannot evidence a track on "
                f"'{self.camera_id}'"
            )


@dataclass(frozen=True, slots=True)
class TrackingResult:
    """Everything the tracker concluded about one frame."""

    camera_id: str
    frame_id: UUID
    frame_sequence: int
    captured_at: datetime
    correlation_id: UUID
    tracks: tuple[Track, ...]
    detection_model: ModelDescriptor
    tracker: ModelDescriptor
    tracking_ms: float

    def __post_init__(self) -> None:
        for track in self.tracks:
            if track.camera_id != self.camera_id:
                raise VisionConfigurationError(
                    f"track {track.display_id} (camera '{track.camera_id}') does not "
                    f"belong to a result for camera '{self.camera_id}'"
                )

    def confirmed(self) -> tuple[Track, ...]:
        """Tracks downstream consumers should act on."""
        return tuple(track for track in self.tracks if track.state is TrackState.CONFIRMED)
