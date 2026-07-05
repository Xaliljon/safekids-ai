"""Output decoders: model output tensors -> RawDetections.

``TensorRowDecoder`` handles the simple row format ``[1, N, 6]`` with rows
``(x, y, width, height, confidence, class_index)``, boxes normalized to
[0, 1] with a top-left origin — the exchange format the dummy detection
model emits. Real model families (each with their own output layout) ship
their own OutputDecoder next to their Preprocessor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from guardian_edge.application.vision.ports import RawDetection
from guardian_edge.domain.detection import BoundingBox
from guardian_edge.domain.errors import DetectorError

_ROW_FIELDS = 6


class TensorRowDecoder:
    """Decodes a [1, N, 6] detection tensor into RawDetections.

    Out-of-range coordinates are clamped into the frame (models routinely
    emit slightly out-of-bounds boxes); degenerate boxes and non-positive
    confidences are dropped. Structural problems fail loudly.
    """

    def __init__(self, output_name: str = "detections") -> None:
        self._output_name = output_name

    def decode(self, outputs: Mapping[str, Any], meta: Any) -> list[RawDetection]:
        tensor = outputs.get(self._output_name)
        if tensor is None:
            raise DetectorError(
                f"model output '{self._output_name}' missing (got {sorted(outputs)})"
            )
        shape = getattr(tensor, "shape", None)
        if shape is None or len(shape) != 3 or shape[0] != 1 or shape[2] < _ROW_FIELDS:
            raise DetectorError(
                f"model output '{self._output_name}' must be [1, N, >={_ROW_FIELDS}], "
                f"got shape {shape}"
            )
        detections: list[RawDetection] = []
        for row in tensor[0]:
            candidate = self._decode_row(row)
            if candidate is not None:
                detections.append(candidate)
        return detections

    def _decode_row(self, row: Any) -> RawDetection | None:
        x, y, width, height, confidence, label_index = (float(value) for value in row[:_ROW_FIELDS])
        if confidence <= 0.0:
            return None
        left = min(max(x, 0.0), 1.0)
        top = min(max(y, 0.0), 1.0)
        clamped_width = min(width, 1.0 - left)
        clamped_height = min(height, 1.0 - top)
        if clamped_width <= 0.0 or clamped_height <= 0.0:
            return None
        return RawDetection(
            label_index=int(label_index),
            confidence=min(confidence, 1.0),
            box=BoundingBox(x=left, y=top, width=clamped_width, height=clamped_height),
        )
