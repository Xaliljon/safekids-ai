"""Deterministic fake detector for developing the pipeline without models.

Produces the same detections for the same frame metadata every time
(pure function of camera_id-independent frame sequence), which makes
end-to-end behavior — pipeline, overlay, future risk engine input —
reproducible in development and tests. Never ships in production
deployments; it exists so the platform works before any model does.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame

_PHASE_STEPS = 20
_BOX_WIDTH = 0.2
_BOX_HEIGHT = 0.3
_MIN_CONFIDENCE = 0.55
_CONFIDENCE_SPAN = 0.4


class DummyDetector:
    """Detector implementation returning deterministic synthetic detections.

    Boxes sweep across the frame as the sequence number advances, so overlay
    rendering and downstream consumers can be watched working in real time.
    """

    def __init__(
        self,
        labels: Sequence[str] = ("person",),
        detections_per_frame: int = 1,
    ) -> None:
        if not labels or not all(label.strip() for label in labels):
            raise VisionConfigurationError("labels must be non-empty strings")
        if detections_per_frame < 0:
            raise VisionConfigurationError("detections_per_frame must be >= 0")
        self._labels = tuple(labels)
        self._detections_per_frame = detections_per_frame
        self._descriptor = ModelDescriptor(name="dummy-detector", version="0.1.0")

    @property
    def descriptor(self) -> ModelDescriptor:
        return self._descriptor

    def detect(self, frame: Frame) -> DetectionResult:
        detections = tuple(
            self._synthesize(frame, index) for index in range(self._detections_per_frame)
        )
        return DetectionResult(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            frame_sequence=frame.sequence,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            detections=detections,
            model=self._descriptor,
            inference_ms=0.0,  # synthetic result: no inference happened
        )

    def _synthesize(self, frame: Frame, index: int) -> Detection:
        phase = ((frame.sequence + index * 7) % _PHASE_STEPS) / _PHASE_STEPS
        return Detection(
            # uuid5 keyed on the frame keeps the dummy fully deterministic:
            # the same frame always yields identical detections, ids included.
            detection_id=uuid.uuid5(frame.frame_id, str(index)),
            frame_id=frame.frame_id,
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            label=self._labels[index % len(self._labels)],
            confidence=round(_MIN_CONFIDENCE + _CONFIDENCE_SPAN * phase, 4),
            box=BoundingBox(
                x=round(0.05 + (0.9 - _BOX_WIDTH) * phase, 4),
                y=round(0.1 + (0.85 - _BOX_HEIGHT) * ((phase + 0.5) % 1.0), 4),
                width=_BOX_WIDTH,
                height=_BOX_HEIGHT,
            ),
        )
