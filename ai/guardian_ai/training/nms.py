"""Generic box IoU + greedy NMS — pure numpy, no detector-specific code.

Shared by every detector family's ``decode()`` and by the COCO-baseline
comparison. Boxes are (cx, cy, w, h), any consistent unit (normalized or
pixel) as long as both inputs to a call share it.
"""

from __future__ import annotations

import numpy as np

MAX_DETECTIONS = 100


def pairwise_iou(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """IoU matrix between two sets of (cx, cy, w, h) boxes: (A, B)."""

    def corners(boxes: np.ndarray) -> np.ndarray:
        return np.stack(
            [
                boxes[:, 0] - boxes[:, 2] / 2,
                boxes[:, 1] - boxes[:, 3] / 2,
                boxes[:, 0] + boxes[:, 2] / 2,
                boxes[:, 1] + boxes[:, 3] / 2,
            ],
            axis=1,
        )

    a, b = corners(boxes_a), corners(boxes_b)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    intersection = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - intersection
    return np.where(union > 0, intersection / np.maximum(union, 1e-9), 0.0)


def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    iou_threshold: float,
    max_detections: int = MAX_DETECTIONS,
) -> list[int]:
    """Greedy score-ordered NMS on (cx, cy, w, h) boxes. Returns kept indices."""
    order = np.argsort(-scores)
    keep: list[int] = []
    while order.size and len(keep) < max_detections:
        current = order[0]
        keep.append(int(current))
        if order.size == 1:
            break
        rest = order[1:]
        ious = pairwise_iou(boxes[current : current + 1], boxes[rest])[0]
        order = rest[ious <= iou_threshold]
    return keep
