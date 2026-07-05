"""Camera service -> vision pipeline integration through FrameConsumer only.

The camera service is wired with ``pipeline.on_frame`` exactly like any other
frame consumer — it has no knowledge of AI, and the pipeline has no knowledge
of capture. This test exercises the whole loop on fakes.
"""

from camera_fakes import ScriptedStreamFactory, make_camera, make_frame, wait_until

from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.application.vision.ports import AnnotatedFrame
from guardian_edge.domain.detection import DetectionResult
from guardian_edge.infrastructure.vision.dummy_detector import DummyDetector
from guardian_edge.infrastructure.vision.wiring import create_dummy_vision_pipeline


def test_frames_captured_by_camera_service_produce_detections() -> None:
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(DummyDetector(), results.append)
    service = CameraService(
        stream_factory=ScriptedStreamFactory(),
        frame_consumer=pipeline.on_frame,  # the only coupling between the two
        retry_policy=RetryPolicy(initial_delay_seconds=0.01, max_delay_seconds=0.02),
    )
    service.add_camera(make_camera("cam-1"))
    service.add_camera(make_camera("cam-2"))
    pipeline.start()
    service.start()
    try:
        assert wait_until(lambda: {r.camera_id for r in results} == {"cam-1", "cam-2"})
    finally:
        service.stop()
        pipeline.stop()

    assert all(r.model.name == "dummy-detector" for r in results)
    stats = pipeline.stats()
    assert set(stats) == {"cam-1", "cam-2"}
    assert all(s.frames_processed >= 1 for s in stats.values())
    # Capture outpaces single-threaded inference by design; drops are counted.
    assert all(s.frames_received >= s.frames_processed for s in stats.values())


def test_dummy_wiring_without_overlay_produces_results() -> None:
    results: list[DetectionResult] = []
    pipeline = create_dummy_vision_pipeline(results.append)
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once() is True
    assert results[0].model.name == "dummy-detector"


def test_dummy_wiring_with_overlay_needs_real_pixels() -> None:
    # The OpenCV renderer requires an ndarray buffer; fake frames carry an
    # opaque object, so the overlay path fails safely and the detection
    # result still gets through (overlay failures never cost results).
    results: list[DetectionResult] = []
    annotated: list[AnnotatedFrame] = []
    pipeline = create_dummy_vision_pipeline(results.append, annotated.append)
    pipeline.on_frame(make_frame("cam-1", 1))
    assert pipeline.process_once() is True
    assert len(results) == 1
    assert annotated == []
