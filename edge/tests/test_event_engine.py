"""Event engine: consumption, isolation, stats, and end-to-end integration."""

from collections.abc import Sequence
from uuid import uuid4

from event_fixtures import fall_trajectory, make_tracking_result, walking_trajectory

from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.application.events.history import TrackObservation
from guardian_edge.domain.event import CandidateEvent, CandidateEventType
from guardian_edge.domain.track import Track, TrackingResult


class BrokenDetector:
    event_type = CandidateEventType.POTENTIAL_FALL

    def evaluate(
        self, history: Sequence[TrackObservation], track: Track, result: TrackingResult
    ) -> CandidateEvent | None:
        raise RuntimeError("detector bug")


def feed(engine: EventEngine, boxes: list, track_id: object = None) -> None:
    track_id = track_id or uuid4()
    for step, box in enumerate(boxes):
        engine(make_tracking_result(box, step, track_id=track_id))


def test_engine_emits_fall_candidates_from_tracking_stream() -> None:
    events: list[CandidateEvent] = []
    engine = EventEngine([PotentialFallDetector()], events.append)
    feed(engine, fall_trajectory())
    assert len(events) == 1
    assert events[0].event_type is CandidateEventType.POTENTIAL_FALL
    stats = engine.stats()
    assert stats.events_emitted == {"potential_fall": 1}
    assert stats.frames_observed == 35
    assert stats.tracks_evaluated == 35
    assert stats.detector_errors == 0


def test_quiet_scene_emits_nothing() -> None:
    events: list[CandidateEvent] = []
    engine = EventEngine([PotentialFallDetector()], events.append)
    feed(engine, walking_trajectory())
    assert events == []
    assert engine.stats().events_emitted == {}


def test_broken_detector_is_isolated() -> None:
    events: list[CandidateEvent] = []
    engine = EventEngine([BrokenDetector(), PotentialFallDetector()], events.append)
    feed(engine, fall_trajectory())
    stats = engine.stats()
    assert stats.detector_errors == 35, "broken detector fails every frame"
    assert len(events) == 1, "healthy detector still emits through the failures"


def test_broken_consumer_is_isolated() -> None:
    def broken_consumer(event: CandidateEvent) -> None:
        raise ValueError("consumer bug")

    engine = EventEngine([PotentialFallDetector()], broken_consumer)
    feed(engine, fall_trajectory())
    stats = engine.stats()
    assert stats.consumer_errors == 1
    assert stats.events_emitted == {"potential_fall": 1}, "emission is counted before delivery"


def test_latency_is_measured() -> None:
    engine = EventEngine([PotentialFallDetector()], lambda event: None)
    feed(engine, walking_trajectory())
    stats = engine.stats()
    assert stats.p50_latency_ms is not None and stats.p50_latency_ms >= 0.0
    assert stats.p95_latency_ms is not None


def test_end_to_end_through_pipeline_tracker_and_engine() -> None:
    """Full chain: scripted detections -> ByteTrack -> EventEngine -> candidate."""
    from datetime import timedelta

    from camera_fakes import make_frame
    from event_fixtures import BASE_TIME

    from guardian_edge.application.vision.pipeline import VisionPipeline
    from guardian_edge.domain.detection import Detection, DetectionResult, ModelDescriptor
    from guardian_edge.domain.frame import Frame
    from guardian_edge.infrastructure.tracking.bytetrack import ByteTrackConfig, ByteTracker

    model = ModelDescriptor(name="scripted", version="1.0.0")
    boxes = fall_trajectory()

    class ScriptedFallDetector:
        descriptor = model

        def detect(self, frame: Frame) -> DetectionResult:
            box = boxes[min(frame.sequence, len(boxes) - 1)]
            detection = Detection(
                detection_id=frame.frame_id,
                frame_id=frame.frame_id,
                camera_id=frame.camera_id,
                captured_at=frame.captured_at,
                correlation_id=frame.correlation_id,
                label="child",
                confidence=0.9,
                box=box,
            )
            return DetectionResult(
                camera_id=frame.camera_id,
                frame_id=frame.frame_id,
                frame_sequence=frame.sequence,
                captured_at=frame.captured_at,
                correlation_id=frame.correlation_id,
                detections=(detection,),
                model=model,
                inference_ms=1.0,
            )

    events: list[CandidateEvent] = []
    engine = EventEngine([PotentialFallDetector()], events.append)
    pipeline = VisionPipeline(
        ScriptedFallDetector(),
        lambda result: None,
        tracker=ByteTracker(ByteTrackConfig(confirm_after=2)),
        track_consumer=engine,
    )
    for step in range(len(boxes)):
        base = make_frame("cam-1", step)
        frame = Frame(
            camera_id=base.camera_id,
            sequence=step,
            captured_at=BASE_TIME + timedelta(seconds=step * 0.1),
            width=base.width,
            height=base.height,
            data=base.data,
        )
        pipeline.on_frame(frame)
        assert pipeline.process_once()

    assert len(events) == 1, "the full chain must surface exactly one fall candidate"
    event = events[0]
    assert event.event_type is CandidateEventType.POTENTIAL_FALL
    assert event.confidence >= 0.6
    assert event.track.label == "child"
    assert event.track.display_id >= 1
    assert engine.stats().events_emitted == {"potential_fall": 1}
