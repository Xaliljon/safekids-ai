"""TensorRowDecoder: [1, N, 6] rows -> RawDetections."""

import numpy as np
import pytest

from guardian_edge.domain.errors import DetectorError
from guardian_edge.infrastructure.vision.decoders import TensorRowDecoder


def tensor(rows: list[list[float]]) -> np.ndarray:
    return np.asarray([rows], dtype=np.float32)


def test_decodes_rows_into_raw_detections() -> None:
    rows = [[0.1, 0.2, 0.3, 0.4, 0.9, 1.0]]
    decoded = TensorRowDecoder().decode({"detections": tensor(rows)}, meta=None)
    assert len(decoded) == 1
    detection = decoded[0]
    assert detection.label_index == 1
    assert detection.confidence == pytest.approx(0.9)
    assert (detection.box.x, detection.box.y) == (pytest.approx(0.1), pytest.approx(0.2))
    assert (detection.box.width, detection.box.height) == (pytest.approx(0.3), pytest.approx(0.4))


def test_clamps_slightly_out_of_range_boxes() -> None:
    rows = [[0.9, 0.9, 0.3, 0.3, 0.8, 0.0]]  # spills past the right/bottom edges
    decoded = TensorRowDecoder().decode({"detections": tensor(rows)}, meta=None)
    box = decoded[0].box
    assert box.x + box.width <= 1.0
    assert box.y + box.height <= 1.0


def test_drops_zero_confidence_and_degenerate_rows() -> None:
    rows = [
        [0.1, 0.1, 0.2, 0.2, 0.0, 0.0],  # zero confidence
        [1.0, 1.0, 0.2, 0.2, 0.9, 0.0],  # fully outside after clamping
        [0.1, 0.1, 0.2, 0.2, 0.9, 0.0],  # valid
    ]
    decoded = TensorRowDecoder().decode({"detections": tensor(rows)}, meta=None)
    assert len(decoded) == 1


def test_confidence_above_one_is_clamped() -> None:
    rows = [[0.1, 0.1, 0.2, 0.2, 1.7, 0.0]]
    decoded = TensorRowDecoder().decode({"detections": tensor(rows)}, meta=None)
    assert decoded[0].confidence == 1.0


def test_missing_output_fails_loudly() -> None:
    with pytest.raises(DetectorError, match="missing"):
        TensorRowDecoder().decode({"other": tensor([[0, 0, 1, 1, 1, 0]])}, meta=None)


def test_wrong_shape_fails_loudly() -> None:
    flat = np.zeros((3, 6), dtype=np.float32)
    with pytest.raises(DetectorError, match="must be"):
        TensorRowDecoder().decode({"detections": flat}, meta=None)
