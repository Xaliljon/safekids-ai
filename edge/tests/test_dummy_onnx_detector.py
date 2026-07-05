"""End-to-end: registry -> ONNX engine -> EngineDetector -> DetectionResult.

The whole detector abstraction running on a real ONNX Runtime session with
a synthetic detection graph — no YOLO, no real model, full pipeline.
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from camera_fakes import make_frame

from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.domain.detection import DetectionResult
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.vision.dummy_onnx import (
    DUMMY_ONNX_DETECTOR_NAME,
    create_dummy_onnx_detector,
)


def image_frame(camera_id: str = "cam-1", width: int = 64, height: int = 64) -> Frame:
    return Frame(
        camera_id=camera_id,
        sequence=1,
        captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
        width=width,
        height=height,
        data=np.zeros((height, width, 3), dtype=np.uint8),
    )


def test_detects_through_a_real_onnx_session(detection_model_dir: Path) -> None:
    detector = create_dummy_onnx_detector(FileSystemModelRegistry(detection_model_dir))
    try:
        frame = image_frame()
        result = detector.detect(frame)
        # Of the three synthetic rows: the weak child is confidence-filtered,
        # the overlapping person is NMS-suppressed, one strong person remains.
        assert len(result.detections) == 1
        detection = result.detections[0]
        assert detection.label == "person"
        assert detection.confidence == pytest.approx(0.9, abs=1e-4)
        assert detection.box.x == pytest.approx(0.1, abs=1e-4)
        assert detection.frame_id == frame.frame_id
        assert detection.correlation_id == frame.correlation_id
        assert result.model.name == DUMMY_ONNX_DETECTOR_NAME
        assert result.inference_ms >= 0.0
    finally:
        detector.close()


def test_dynamic_input_sizes_share_one_session(detection_model_dir: Path) -> None:
    detector = create_dummy_onnx_detector(FileSystemModelRegistry(detection_model_dir))
    try:
        for width, height in ((64, 64), (128, 96)):
            result = detector.detect(image_frame(width=width, height=height))
            assert len(result.detections) == 1
    finally:
        detector.close()


def test_config_overrides_tighten_thresholds(detection_model_dir: Path) -> None:
    detector = create_dummy_onnx_detector(
        FileSystemModelRegistry(detection_model_dir),
        confidence_threshold=0.95,  # above every synthetic row
    )
    try:
        assert detector.detect(image_frame()).detections == ()
    finally:
        detector.close()


def test_descriptor_and_config_come_from_the_manifest(detection_model_dir: Path) -> None:
    detector = create_dummy_onnx_detector(FileSystemModelRegistry(detection_model_dir))
    try:
        assert detector.descriptor.name == DUMMY_ONNX_DETECTOR_NAME
        assert detector.descriptor.version == "1.0.0"
        assert detector.config.labels == ("person", "child")
        assert detector.config.confidence_threshold == 0.5  # from manifest metadata
    finally:
        detector.close()


def test_works_behind_the_vision_pipeline_detector_port(detection_model_dir: Path) -> None:
    """The abstraction satisfies the same Detector port the pipeline drives."""
    detector = create_dummy_onnx_detector(FileSystemModelRegistry(detection_model_dir))
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    try:
        frame = image_frame()
        # Pipeline fakes carry opaque buffers; this frame has real pixels.
        pipeline.on_frame(frame)
        assert pipeline.process_once() is True
        assert len(results) == 1
        assert results[0].detections[0].label == "person"
        assert results[0].correlation_id == frame.correlation_id
    finally:
        detector.close()


def test_frames_from_capture_fakes_fail_safely(detection_model_dir: Path) -> None:
    """Opaque (non-image) frame buffers are rejected loudly by preprocessing."""
    detector = create_dummy_onnx_detector(FileSystemModelRegistry(detection_model_dir))
    results: list[DetectionResult] = []
    pipeline = VisionPipeline(detector, results.append)
    try:
        pipeline.on_frame(make_frame("cam-1", 1))  # opaque object() buffer
        assert pipeline.process_once() is True
        assert results == []
        assert pipeline.stats()["cam-1"].detector_errors == 1
    finally:
        detector.close()
