"""Development wiring for the vision pipeline.

Composes the pipeline with the DummyDetector and OpenCV overlay so the whole
edge flow (camera -> vision -> consumers) runs before any real model exists.
Production wiring will swap the detector for a real one behind the same
Detector port; nothing else changes (ADR-0006).
"""

from __future__ import annotations

from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.application.vision.ports import AnnotatedFrameConsumer, DetectionConsumer
from guardian_edge.infrastructure.vision.dummy_detector import DummyDetector
from guardian_edge.infrastructure.vision.overlay import OpenCvOverlayRenderer


def create_dummy_vision_pipeline(
    detection_consumer: DetectionConsumer,
    annotated_consumer: AnnotatedFrameConsumer | None = None,
) -> VisionPipeline:
    """Build a vision pipeline running the deterministic DummyDetector.

    The returned pipeline is not started; attach it with
    ``CameraService(frame_consumer=pipeline.on_frame, ...)`` and call
    ``pipeline.start()`` alongside ``service.start()``.
    """
    return VisionPipeline(
        detector=DummyDetector(),
        detection_consumer=detection_consumer,
        overlay_renderer=OpenCvOverlayRenderer() if annotated_consumer is not None else None,
        annotated_consumer=annotated_consumer,
    )
