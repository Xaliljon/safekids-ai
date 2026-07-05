"""ByteTrack multi-object tracking (independent implementation, ADR-0011).

Algorithm from Zhang et al., "ByteTrack: Multi-Object Tracking by
Associating Every Detection Box" — the key idea is two-stage association:
high-confidence detections match first; the *low*-confidence leftovers
(usually occluded objects) then rescue unmatched tracks instead of being
thrown away. This file is our own dependency-free implementation.

Deliberate simplifications (documented in ADR-0011):
- Greedy IoU association instead of Hungarian (no scipy on the box; at
  classroom object counts the difference is negligible, and the matcher
  is one function to swap if profiling ever disagrees).
- Association is label-aware: a 'child' track can never be continued by a
  'chair' detection — identity mistakes in a safety system are worse than
  fragmented tracks.

Implements the Tracker port: per-camera state lives inside; the vision
pipeline's single worker thread serializes calls.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import uuid4

from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.track import Track, TrackingResult, TrackState
from guardian_edge.infrastructure.tracking.kalman import KalmanBoxFilter

TRACKER_DESCRIPTOR = ModelDescriptor(name="bytetrack", version="1.0.0")

_MIN_BOX_SIZE = 1e-4


@dataclass(frozen=True, slots=True)
class ByteTrackConfig:
    """Tracking thresholds.

    Detections with confidence >= ``high_threshold`` drive association and
    may spawn tracks; those in [``low_threshold``, ``high_threshold``) only
    rescue existing tracks (the BYTE idea). A track is CONFIRMED after
    ``confirm_after`` hits and REMOVED after ``max_lost_frames`` without
    evidence.
    """

    high_threshold: float = 0.5
    low_threshold: float = 0.1
    match_iou: float = 0.3
    second_match_iou: float = 0.4
    confirm_after: int = 3
    max_lost_frames: int = 30

    def __post_init__(self) -> None:
        if not (0.0 <= self.low_threshold < self.high_threshold <= 1.0):
            raise VisionConfigurationError(
                f"thresholds must satisfy 0 <= low < high <= 1, got "
                f"low={self.low_threshold}, high={self.high_threshold}"
            )
        for name, value in (
            ("match_iou", self.match_iou),
            ("second_match_iou", self.second_match_iou),
        ):
            if not (0.0 < value <= 1.0):
                raise VisionConfigurationError(f"{name} out of range: {value}")
        if self.confirm_after < 1 or self.max_lost_frames < 1:
            raise VisionConfigurationError("confirm_after and max_lost_frames must be >= 1")


class _TrackedObject:
    """Mutable per-track state; snapshots become immutable domain Tracks."""

    def __init__(self, detection: Detection, display_id: int, config: ByteTrackConfig) -> None:
        self.track_id = uuid4()
        self.display_id = display_id
        self.camera_id = detection.camera_id
        self.label = detection.label
        self.state = TrackState.CONFIRMED if config.confirm_after <= 1 else TrackState.TENTATIVE
        self.hits = 1
        self.age_frames = 1
        self.frames_since_update = 0
        self.last_detection = detection
        self.first_seen_at = detection.captured_at
        self._config = config
        self._kalman = KalmanBoxFilter(_to_center(detection.box))

    def predict(self) -> None:
        self.age_frames += 1
        self._kalman.predict()

    def update(self, detection: Detection) -> None:
        self._kalman.update(_to_center(detection.box))
        self.hits += 1
        self.frames_since_update = 0
        self.last_detection = detection
        self.label = detection.label
        confirmed_now = self.state is TrackState.LOST or (
            self.state is TrackState.TENTATIVE and self.hits >= self._config.confirm_after
        )
        if confirmed_now:
            self.state = TrackState.CONFIRMED

    def mark_missed(self) -> None:
        self.frames_since_update += 1
        never_coming_back = (
            self.state is TrackState.TENTATIVE
            or self.frames_since_update > self._config.max_lost_frames
        )
        self.state = TrackState.REMOVED if never_coming_back else TrackState.LOST

    def current_box(self) -> BoundingBox:
        box = _from_center(self._kalman.box)
        return box if box is not None else self.last_detection.box

    def snapshot(self) -> Track:
        return Track(
            track_id=self.track_id,
            display_id=self.display_id,
            camera_id=self.camera_id,
            state=self.state,
            label=self.label,
            confidence=self.last_detection.confidence,
            box=self.current_box(),
            last_detection=self.last_detection,
            hits=self.hits,
            age_frames=self.age_frames,
            frames_since_update=self.frames_since_update,
            first_seen_at=self.first_seen_at,
            last_seen_at=self.last_detection.captured_at,
        )


class _CameraTracker:
    """ByteTrack state machine for one camera."""

    def __init__(self, config: ByteTrackConfig, ids: itertools.count[int]) -> None:
        self._config = config
        self._ids = ids
        self._tracks: list[_TrackedObject] = []

    def step(self, result: DetectionResult) -> tuple[Track, ...]:
        config = self._config
        for track in self._tracks:
            track.predict()

        high = [d for d in result.detections if d.confidence >= config.high_threshold]
        low = [
            d
            for d in result.detections
            if config.low_threshold <= d.confidence < config.high_threshold
        ]
        established = [t for t in self._tracks if t.state is not TrackState.TENTATIVE]
        tentative = [t for t in self._tracks if t.state is TrackState.TENTATIVE]

        # Stage 1: high-confidence detections vs established (confirmed/lost) tracks.
        matched, unmatched_tracks, unmatched_high = _greedy_match(
            established, high, config.match_iou
        )
        for track, detection in matched:
            track.update(detection)
        # Stage 2 (BYTE): low-confidence leftovers rescue still-unmatched tracks.
        rescued, still_unmatched, _ = _greedy_match(unmatched_tracks, low, config.second_match_iou)
        for track, detection in rescued:
            track.update(detection)
        # Stage 3: tentative tracks vs remaining high-confidence detections.
        confirmed_new, unmatched_tentative, spawning = _greedy_match(
            tentative, unmatched_high, config.match_iou
        )
        for track, detection in confirmed_new:
            track.update(detection)

        for track in still_unmatched + unmatched_tentative:
            track.mark_missed()
        for detection in spawning:
            self._tracks.append(_TrackedObject(detection, next(self._ids), config))

        self._tracks = [t for t in self._tracks if t.state is not TrackState.REMOVED]
        return tuple(track.snapshot() for track in sorted(self._tracks, key=lambda t: t.display_id))


class ByteTracker:
    """Tracker-port implementation; keeps independent state per camera."""

    def __init__(
        self,
        config: ByteTrackConfig | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._config = config or ByteTrackConfig()
        self._clock = clock
        self._ids = itertools.count(1)  # display ids unique across cameras
        self._cameras: dict[str, _CameraTracker] = {}

    @property
    def descriptor(self) -> ModelDescriptor:
        return TRACKER_DESCRIPTOR

    def update(self, result: DetectionResult) -> TrackingResult:
        started = self._clock()
        camera = self._cameras.get(result.camera_id)
        if camera is None:
            camera = _CameraTracker(self._config, self._ids)
            self._cameras[result.camera_id] = camera
        tracks = camera.step(result)
        return TrackingResult(
            camera_id=result.camera_id,
            frame_id=result.frame_id,
            frame_sequence=result.frame_sequence,
            captured_at=result.captured_at,
            correlation_id=result.correlation_id,  # propagate, never regenerate (ADR-0007)
            tracks=tracks,
            detection_model=result.model,
            tracker=TRACKER_DESCRIPTOR,
            tracking_ms=round((self._clock() - started) * 1000.0, 3),
        )


def _greedy_match(
    tracks: Sequence[_TrackedObject],
    detections: Sequence[Detection],
    iou_threshold: float,
) -> tuple[list[tuple[_TrackedObject, Detection]], list[_TrackedObject], list[Detection]]:
    """Label-aware greedy IoU assignment (highest overlap first)."""
    if not tracks or not detections:
        return [], list(tracks), list(detections)
    scored: list[tuple[float, int, int]] = []
    for track_index, track in enumerate(tracks):
        track_box = track.current_box()
        for det_index, detection in enumerate(detections):
            if detection.label != track.label:
                continue
            iou = track_box.intersection_over_union(detection.box)
            if iou >= iou_threshold:
                scored.append((iou, track_index, det_index))
    scored.sort(reverse=True)
    matched: list[tuple[_TrackedObject, Detection]] = []
    used_tracks: set[int] = set()
    used_detections: set[int] = set()
    for _, track_index, det_index in scored:
        if track_index in used_tracks or det_index in used_detections:
            continue
        used_tracks.add(track_index)
        used_detections.add(det_index)
        matched.append((tracks[track_index], detections[det_index]))
    unmatched_tracks = [t for i, t in enumerate(tracks) if i not in used_tracks]
    unmatched_detections = [d for i, d in enumerate(detections) if i not in used_detections]
    return matched, unmatched_tracks, unmatched_detections


def _to_center(box: BoundingBox) -> tuple[float, float, float, float]:
    return (box.x + box.width / 2.0, box.y + box.height / 2.0, box.width, box.height)


def _from_center(center: tuple[float, float, float, float]) -> BoundingBox | None:
    cx, cy, width, height = center
    left = min(max(cx - width / 2.0, 0.0), 1.0)
    top = min(max(cy - height / 2.0, 0.0), 1.0)
    right = min(max(cx + width / 2.0, 0.0), 1.0)
    bottom = min(max(cy + height / 2.0, 0.0), 1.0)
    if right - left < _MIN_BOX_SIZE or bottom - top < _MIN_BOX_SIZE:
        return None
    return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)
