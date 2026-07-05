"""Builders for event engine tests: tracks, tracking results, trajectories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from guardian_edge.domain.detection import BoundingBox, Detection, ModelDescriptor
from guardian_edge.domain.track import Track, TrackingResult, TrackState

BASE_TIME = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
FRAME_INTERVAL_SECONDS = 0.1
MODEL = ModelDescriptor(name="test-detector", version="1.0.0")
TRACKER = ModelDescriptor(name="bytetrack", version="1.0.0")

STANDING = BoundingBox(x=0.45, y=0.30, width=0.10, height=0.35)
LYING = BoundingBox(x=0.40, y=0.70, width=0.30, height=0.12)


def timestamp(step: int) -> datetime:
    return BASE_TIME + timedelta(seconds=step * FRAME_INTERVAL_SECONDS)


def make_tracking_result(
    box: BoundingBox,
    step: int,
    track_id: object = None,
    label: str = "child",
    state: TrackState = TrackState.CONFIRMED,
    camera_id: str = "cam-1",
    display_id: int = 1,
) -> TrackingResult:
    """One frame's tracking result holding a single track at ``box``."""
    captured_at = timestamp(step)
    frame_id = uuid4()
    correlation_id = uuid4()
    detection = Detection(
        detection_id=uuid4(),
        frame_id=frame_id,
        camera_id=camera_id,
        captured_at=captured_at,
        correlation_id=correlation_id,
        label=label,
        confidence=0.9,
        box=box,
    )
    track = Track(
        track_id=track_id or uuid4(),  # type: ignore[arg-type]
        display_id=display_id,
        camera_id=camera_id,
        state=state,
        label=label,
        confidence=0.9,
        box=box,
        last_detection=detection,
        hits=step + 1,
        age_frames=step + 1,
        frames_since_update=0,
        first_seen_at=BASE_TIME,
        last_seen_at=captured_at,
    )
    return TrackingResult(
        camera_id=camera_id,
        frame_id=frame_id,
        frame_sequence=step,
        captured_at=captured_at,
        correlation_id=correlation_id,
        tracks=(track,),
        detection_model=MODEL,
        tracker=TRACKER,
        tracking_ms=0.1,
    )


def interpolate(a: BoundingBox, b: BoundingBox, fraction: float) -> BoundingBox:
    def mix(start: float, end: float) -> float:
        return start + (end - start) * fraction

    return BoundingBox(
        x=mix(a.x, b.x),
        y=mix(a.y, b.y),
        width=mix(a.width, b.width),
        height=mix(a.height, b.height),
    )


def fall_trajectory(
    standing_frames: int = 15,
    falling_frames: int = 5,
    still_frames: int = 15,
) -> list[BoundingBox]:
    """Stand -> rapid drop with tall->wide flip -> lie still near the ground."""
    boxes = [STANDING] * standing_frames
    boxes += [interpolate(STANDING, LYING, (i + 1) / falling_frames) for i in range(falling_frames)]
    boxes += [LYING] * still_frames
    return boxes


def walking_trajectory(frames: int = 35) -> list[BoundingBox]:
    """Constant-height horizontal walk: motion without any fall geometry."""
    return [
        BoundingBox(x=0.05 + step * 0.015, y=0.30, width=0.10, height=0.35)
        for step in range(frames)
    ]


def slow_sit_trajectory(frames: int = 35) -> list[BoundingBox]:
    """Gentle descent (sitting down): downward but far below fall velocity."""
    return [
        BoundingBox(
            x=0.45,
            y=min(0.30 + step * 0.006, 0.55),
            width=0.10,
            height=max(0.35 - step * 0.003, 0.25),
        )
        for step in range(frames)
    ]
