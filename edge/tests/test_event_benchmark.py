"""Event engine latency benchmark (pure CPU, runs everywhere)."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from event_fixtures import BASE_TIME, MODEL, TRACKER

from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.domain.detection import BoundingBox, Detection
from guardian_edge.domain.track import Track, TrackingResult, TrackState

logger = logging.getLogger(__name__)

TRACKS = 12
FRAMES = 300
EVENT_BUDGET_MS = 2.0  # the event engine must be noise next to ~15ms inference


def busy_result(step: int, track_ids: list) -> TrackingResult:
    captured_at = BASE_TIME + timedelta(seconds=step * 0.1)
    frame_id = uuid4()
    correlation_id = uuid4()
    tracks = []
    for index, track_id in enumerate(track_ids):
        x = (0.05 + index * 0.07 + step * 0.002) % 0.7
        box = BoundingBox(x=x, y=0.2 + (index % 3) * 0.15, width=0.08, height=0.2)
        detection = Detection(
            detection_id=uuid4(),
            frame_id=frame_id,
            camera_id="bench-cam",
            captured_at=captured_at,
            correlation_id=correlation_id,
            label="person",
            confidence=0.9,
            box=box,
        )
        tracks.append(
            Track(
                track_id=track_id,
                display_id=index + 1,
                camera_id="bench-cam",
                state=TrackState.CONFIRMED,
                label="person",
                confidence=0.9,
                box=box,
                last_detection=detection,
                hits=step + 1,
                age_frames=step + 1,
                frames_since_update=0,
                first_seen_at=BASE_TIME,
                last_seen_at=captured_at,
            )
        )
    return TrackingResult(
        camera_id="bench-cam",
        frame_id=frame_id,
        frame_sequence=step,
        captured_at=captured_at,
        correlation_id=correlation_id,
        tracks=tuple(tracks),
        detection_model=MODEL,
        tracker=TRACKER,
        tracking_ms=0.1,
    )


@pytest.mark.benchmark
def test_event_engine_latency_benchmark() -> None:
    engine = EventEngine([PotentialFallDetector()], lambda event: None)
    track_ids = [uuid4() for _ in range(TRACKS)]
    for step in range(FRAMES):
        engine(busy_result(step, track_ids))
    stats = engine.stats()
    logger.info(
        "event engine benchmark: %d tracks x %d frames — p50=%.3fms p95=%.3fms",
        TRACKS,
        FRAMES,
        stats.p50_latency_ms or 0.0,
        stats.p95_latency_ms or 0.0,
    )
    assert stats.frames_observed == FRAMES
    assert stats.tracks_evaluated == TRACKS * FRAMES
    assert stats.p95_latency_ms is not None
    assert stats.p95_latency_ms < EVENT_BUDGET_MS, (
        f"event engine p95 {stats.p95_latency_ms:.2f}ms exceeds {EVENT_BUDGET_MS}ms"
    )


def test_single_smoke_pass_without_benchmark_marker() -> None:
    """Keeps the busy-scene path exercised in ordinary CI runs."""
    engine = EventEngine([PotentialFallDetector()], lambda event: None)
    track_ids = [uuid4() for _ in range(3)]
    for step in range(20):
        engine(busy_result(step, track_ids))
    assert engine.stats().frames_observed == 20
