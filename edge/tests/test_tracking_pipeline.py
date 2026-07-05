"""Tracking as a vision pipeline stage: consumers, isolation, overlays."""

from typing import Any

import pytest
from camera_fakes import make_frame

from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.application.vision.ports import AnnotatedFrame
from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import TrackingResult, TrackState
from guardian_edge.infrastructure.tracking.bytetrack import ByteTrackConfig, ByteTracker

MODEL = ModelDescriptor(name="fake-detector", version="1.0.0")


class MovingBoxDetector:
    """Emits one high-confidence person box sweeping smoothly right."""

    descriptor = MODEL

    def __init__(self) -> None:
        self._step = 0

    def detect(self, frame: Frame) -> DetectionResult:
        x = min(0.1 + self._step * 0.02, 0.7)
        self._step += 1
        detection = Detection(
            detection_id=frame.frame_id,  # any uuid; uniqueness not needed here
            frame_id=frame.frame_id,
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            label="person",
            confidence=0.9,
            box=BoundingBox(x=x, y=0.4, width=0.2, height=0.3),
        )
        return DetectionResult(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            frame_sequence=frame.sequence,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            detections=(detection,),
            model=MODEL,
            inference_ms=1.0,
        )


class BrokenTracker:
    descriptor = ModelDescriptor(name="broken", version="0.0.0")

    def update(self, result: DetectionResult) -> TrackingResult:
        raise RuntimeError("tracker bug")


class MarkerTrackRenderer:
    def render(self, frame: Frame, result: TrackingResult, fps: float) -> Any:
        return ("tracked", frame.sequence, len(result.tracks))


def test_tracks_flow_to_track_consumer_with_stable_ids() -> None:
    detections: list[DetectionResult] = []
    tracking: list[TrackingResult] = []
    pipeline = VisionPipeline(
        MovingBoxDetector(),
        detections.append,
        tracker=ByteTracker(ByteTrackConfig(confirm_after=2)),
        track_consumer=tracking.append,
    )
    for sequence in range(1, 11):
        pipeline.on_frame(make_frame("cam-1", sequence))
        assert pipeline.process_once()
    assert len(detections) == 10, "detections still flow unchanged"
    assert len(tracking) == 10
    confirmed = [r for r in tracking if r.confirmed()]
    assert confirmed, "the moving object must get confirmed"
    ids = {r.confirmed()[0].track_id for r in confirmed}
    assert len(ids) == 1, "persistent id across all frames"
    assert tracking[0].correlation_id == detections[0].correlation_id


def test_tracker_failure_is_counted_and_detections_still_flow() -> None:
    detections: list[DetectionResult] = []
    tracking: list[TrackingResult] = []
    pipeline = VisionPipeline(
        MovingBoxDetector(),
        detections.append,
        tracker=BrokenTracker(),
        track_consumer=tracking.append,
    )
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once()
    assert len(detections) == 1
    assert tracking == []
    stats = pipeline.stats()["cam-1"]
    assert stats.tracker_errors == 1
    assert stats.frames_processed == 1


def test_track_overlay_wins_over_detection_overlay() -> None:
    annotated: list[AnnotatedFrame] = []
    pipeline = VisionPipeline(
        MovingBoxDetector(),
        lambda _result: None,
        annotated_consumer=annotated.append,
        tracker=ByteTracker(ByteTrackConfig(confirm_after=1)),
        track_overlay_renderer=MarkerTrackRenderer(),
    )
    pipeline.on_frame(make_frame("cam-1", 7))
    pipeline.process_once()
    assert annotated[0].image == ("tracked", 7, 1)


def test_track_consumer_failure_does_not_break_processing() -> None:
    def broken_consumer(_result: TrackingResult) -> None:
        raise ValueError("consumer bug")

    pipeline = VisionPipeline(
        MovingBoxDetector(),
        lambda _result: None,
        tracker=ByteTracker(ByteTrackConfig(confirm_after=1)),
        track_consumer=broken_consumer,
    )
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once()
    pipeline.on_frame(make_frame("cam-1", 2))
    assert pipeline.process_once()
    assert pipeline.stats()["cam-1"].frames_processed == 2


def test_track_options_require_a_tracker() -> None:
    with pytest.raises(VisionConfigurationError, match="require a tracker"):
        VisionPipeline(
            MovingBoxDetector(),
            lambda _result: None,
            track_consumer=lambda _tracking: None,
        )
    with pytest.raises(VisionConfigurationError, match="require a tracker"):
        VisionPipeline(
            MovingBoxDetector(),
            lambda _result: None,
            annotated_consumer=lambda _annotated: None,
            track_overlay_renderer=MarkerTrackRenderer(),
        )


def test_track_renderer_requires_annotated_consumer() -> None:
    with pytest.raises(VisionConfigurationError, match="together"):
        VisionPipeline(
            MovingBoxDetector(),
            lambda _result: None,
            tracker=ByteTracker(),
            track_overlay_renderer=MarkerTrackRenderer(),
        )


def test_lifecycle_states_visible_through_the_pipeline() -> None:
    tracking: list[TrackingResult] = []

    class VanishingDetector(MovingBoxDetector):
        def detect(self, frame: Frame) -> DetectionResult:
            result = super().detect(frame)
            if frame.sequence > 5:  # object leaves the scene
                return DetectionResult(
                    camera_id=result.camera_id,
                    frame_id=result.frame_id,
                    frame_sequence=result.frame_sequence,
                    captured_at=result.captured_at,
                    correlation_id=result.correlation_id,
                    detections=(),
                    model=result.model,
                    inference_ms=result.inference_ms,
                )
            return result

    pipeline = VisionPipeline(
        VanishingDetector(),
        lambda _result: None,
        tracker=ByteTracker(ByteTrackConfig(confirm_after=2, max_lost_frames=3)),
        track_consumer=tracking.append,
    )
    for sequence in range(1, 12):
        pipeline.on_frame(make_frame("cam-1", sequence))
        pipeline.process_once()
    states = [result.tracks[0].state for result in tracking if result.tracks]
    assert TrackState.TENTATIVE in states
    assert TrackState.CONFIRMED in states
    assert TrackState.LOST in states
    assert tracking[-1].tracks == (), "removed track disappears from results"
