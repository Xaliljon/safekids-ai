"""DetectionResult mapper: raw candidates -> identified domain detections.

The single place where model-space candidates become domain objects:
label indices resolve to names, and every detection is stamped with its
own UUID plus the frame's identity (ADR-0007 — mint at source, propagate,
never regenerate). An index outside the label set fails loudly: silently
mislabeling a safety event is not an option.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from guardian_edge.application.vision.ports import RawDetection
from guardian_edge.domain.detection import Detection, DetectionResult, ModelDescriptor
from guardian_edge.domain.errors import DetectorError
from guardian_edge.domain.frame import Frame


class DetectionResultMapper:
    """Maps filtered RawDetections into a DetectionResult for one frame."""

    def __init__(self, labels: Sequence[str], model: ModelDescriptor) -> None:
        self._labels = tuple(labels)
        self._model = model

    def map(
        self, frame: Frame, candidates: Sequence[RawDetection], inference_ms: float
    ) -> DetectionResult:
        detections = tuple(
            Detection(
                detection_id=uuid4(),
                frame_id=frame.frame_id,
                camera_id=frame.camera_id,
                captured_at=frame.captured_at,
                correlation_id=frame.correlation_id,
                label=self._label_for(candidate),
                confidence=candidate.confidence,
                box=candidate.box,
            )
            for candidate in candidates
        )
        return DetectionResult(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            frame_sequence=frame.sequence,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            detections=detections,
            model=self._model,
            inference_ms=round(inference_ms, 3),
        )

    def _label_for(self, candidate: RawDetection) -> str:
        if not 0 <= candidate.label_index < len(self._labels):
            raise DetectorError(
                f"model {self._model.name} v{self._model.version}: label index "
                f"{candidate.label_index} outside configured labels "
                f"(0..{len(self._labels) - 1}) — refusing to guess"
            )
        return self._labels[candidate.label_index]
