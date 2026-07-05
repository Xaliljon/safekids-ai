"""Vision pipeline: intake, latest-frame-wins, isolation of failures."""

from typing import Any

import pytest
from camera_fakes import make_frame, wait_until

from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.application.vision.ports import AnnotatedFrame
from guardian_edge.domain.detection import DetectionResult, ModelDescriptor
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame


class RecordingDetector:
    """Detector fake: records frames, optionally fails on marked sequences."""

    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.seen: list[Frame] = []
        self._fail_on = fail_on or set()
        self.descriptor = ModelDescriptor(name="recording", version="0.0.0")

    def detect(self, frame: Frame) -> DetectionResult:
        if frame.sequence in self._fail_on:
            raise RuntimeError(f"simulated detector failure on {frame.sequence}")
        self.seen.append(frame)
        return DetectionResult(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            frame_sequence=frame.sequence,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            detections=(),
            model=self.descriptor,
            inference_ms=1.0,
        )


class MarkerRenderer:
    """Overlay fake returning a recognizable object instead of pixels."""

    def render(self, frame: Frame, result: DetectionResult, fps: float) -> Any:
        assert fps >= 0.0
        return ("annotated", frame.sequence)


def test_frames_flow_to_detection_consumer() -> None:
    detector = RecordingDetector()
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once() is True
    assert pipeline.process_once() is False, "mailbox must be empty after processing"
    assert [r.frame_sequence for r in results] == [1]
    assert results[0].camera_id == "cam-1"


def test_latest_frame_wins_and_drops_are_counted() -> None:
    detector = RecordingDetector()
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    for sequence in (1, 2, 3):
        pipeline.on_frame(make_frame("cam-1", sequence))
    assert pipeline.process_once() is True
    stats = pipeline.stats()["cam-1"]
    assert [r.frame_sequence for r in results] == [3], "only the freshest frame is processed"
    assert stats.frames_received == 3
    assert stats.frames_processed == 1
    assert stats.frames_dropped == 2, "drops must be counted, never silent"


def test_each_camera_has_its_own_mailbox() -> None:
    detector = RecordingDetector()
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    pipeline.on_frame(make_frame("cam-1", 1))
    pipeline.on_frame(make_frame("cam-2", 1))
    assert pipeline.process_once() and pipeline.process_once()
    assert {r.camera_id for r in results} == {"cam-1", "cam-2"}


def test_detector_failure_is_counted_and_pipeline_continues() -> None:
    detector = RecordingDetector(fail_on={1})
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once() is True
    pipeline.on_frame(make_frame("cam-1", 2))
    assert pipeline.process_once() is True
    stats = pipeline.stats()["cam-1"]
    assert stats.detector_errors == 1
    assert [r.frame_sequence for r in results] == [2]


def test_consumer_failure_does_not_stop_processing() -> None:
    detector = RecordingDetector()
    received: list[int] = []

    def flaky_consumer(result: DetectionResult) -> None:
        if result.frame_sequence == 1:
            raise ValueError("consumer bug")
        received.append(result.frame_sequence)

    pipeline = VisionPipeline(detector, flaky_consumer)
    pipeline.on_frame(make_frame("cam-1", 1))
    pipeline.process_once()
    pipeline.on_frame(make_frame("cam-1", 2))
    pipeline.process_once()
    assert received == [2]
    assert pipeline.stats()["cam-1"].frames_processed == 2


def test_overlay_path_renders_and_publishes() -> None:
    annotated: list[AnnotatedFrame] = []
    pipeline = VisionPipeline(
        RecordingDetector(),
        lambda _result: None,
        overlay_renderer=MarkerRenderer(),
        annotated_consumer=annotated.append,
    )
    pipeline.on_frame(make_frame("cam-1", 5))
    pipeline.process_once()
    assert len(annotated) == 1
    assert annotated[0].image == ("annotated", 5)
    assert annotated[0].result.frame_sequence == 5
    assert annotated[0].frame.sequence == 5


def test_overlay_failure_does_not_lose_detection_results() -> None:
    class BrokenRenderer:
        def render(self, frame: Frame, result: DetectionResult, fps: float) -> Any:
            raise RuntimeError("renderer bug")

    results: list[DetectionResult] = []
    pipeline = VisionPipeline(
        RecordingDetector(),
        results.append,
        overlay_renderer=BrokenRenderer(),
        annotated_consumer=lambda _annotated: None,
    )
    pipeline.on_frame(make_frame("cam-1", 1))
    pipeline.process_once()
    assert [r.frame_sequence for r in results] == [1]


def test_renderer_and_annotated_consumer_must_come_together() -> None:
    with pytest.raises(VisionConfigurationError):
        VisionPipeline(RecordingDetector(), lambda _r: None, overlay_renderer=MarkerRenderer())
    with pytest.raises(VisionConfigurationError):
        VisionPipeline(RecordingDetector(), lambda _r: None, annotated_consumer=lambda _a: None)


def test_worker_thread_processes_and_stops_cleanly() -> None:
    detector = RecordingDetector()
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    pipeline.start()
    pipeline.start()  # idempotent
    try:
        for sequence in range(1, 6):
            pipeline.on_frame(make_frame("cam-1", sequence))
        assert wait_until(lambda: len(results) >= 1)
    finally:
        pipeline.stop()
        pipeline.stop()  # idempotent
    processed = len(results)
    pipeline.on_frame(make_frame("cam-1", 99))
    assert not wait_until(lambda: len(results) > processed, timeout=0.1), (
        "stopped pipeline must not process new frames"
    )
