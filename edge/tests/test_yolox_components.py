"""YOLOX adapters: letterbox preprocessing and grid decoding (no model)."""

from datetime import datetime, timezone

import numpy as np
import pytest

from guardian_edge.domain.errors import DetectorError
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.vision.yolox import (
    COCO_LABELS,
    YoloxDecoder,
    YoloxMeta,
    YoloxPreprocessor,
)

INPUT_SIZE = (416, 416)
CELLS_416 = 52 * 52 + 26 * 26 + 13 * 13  # strides 8/16/32


def image_frame(width: int = 640, height: int = 480) -> Frame:
    return Frame(
        camera_id="cam-1",
        sequence=1,
        captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
        width=width,
        height=height,
        data=np.full((height, width, 3), 200, dtype=np.uint8),
    )


def make_meta(ratio: float = 0.65, width: int = 640, height: int = 480) -> YoloxMeta:
    return YoloxMeta(
        ratio=ratio,
        original_width=width,
        original_height=height,
        input_width=416,
        input_height=416,
    )


class TestPreprocessor:
    def test_letterboxes_into_padded_canvas(self) -> None:
        pre = YoloxPreprocessor("images", INPUT_SIZE).preprocess(image_frame(640, 480))
        tensor = pre.inputs["images"]
        assert tensor.shape == (1, 3, 416, 416)
        assert tensor.dtype == np.float32
        # ratio = min(416/480, 416/640) = 0.65 -> content 416x312, rest padded 114
        assert pre.meta.ratio == pytest.approx(0.65)
        assert tensor[0, 0, 0, 0] == pytest.approx(200.0), "pixels stay 0-255 (no /255)"
        assert tensor[0, 0, 400, 400] == pytest.approx(114.0), "padding value is 114"

    def test_meta_carries_geometry(self) -> None:
        pre = YoloxPreprocessor("images", INPUT_SIZE).preprocess(image_frame(1920, 1080))
        meta = pre.meta
        assert isinstance(meta, YoloxMeta)
        assert (meta.original_width, meta.original_height) == (1920, 1080)
        assert (meta.input_width, meta.input_height) == (416, 416)

    def test_non_image_buffer_fails_loudly(self) -> None:
        frame = Frame(
            camera_id="cam-1",
            sequence=1,
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            width=10,
            height=10,
            data=object(),
        )
        with pytest.raises(DetectorError, match="HxWx3"):
            YoloxPreprocessor("images", INPUT_SIZE).preprocess(frame)


def raw_output(cells: dict[int, tuple[float, float, float, float, float, int]]) -> np.ndarray:
    """[1, N, 85] tensor of near-zero background plus chosen active cells.

    Cell values are (dx, dy, log_w, log_h, objectness, class_index).
    """
    tensor = np.zeros((1, CELLS_416, 85), dtype=np.float32)
    tensor[..., 2:4] = -10.0  # exp(-10) ~ 0 sized boxes for background cells
    for cell, (dx, dy, log_w, log_h, objectness, label) in cells.items():
        tensor[0, cell, 0:4] = (dx, dy, log_w, log_h)
        tensor[0, cell, 4] = objectness
        tensor[0, cell, 5 + label] = 1.0
    return tensor


class TestDecoder:
    def test_decodes_known_cell_to_expected_normalized_box(self) -> None:
        # Cell 0 of the stride-8 level: grid (0,0). Center = (dx*8, dy*8);
        # size = exp(log)*8. Choose a 104x104 px box centered at (208, 208)
        # on the canvas: with ratio 0.65 over 640x480 that maps to
        # center (320, 320) px -> x1=240/640, y1=240/480 in the original.
        log_13 = float(np.log(13.0))
        output = raw_output({0: (26.0, 26.0, log_13, log_13, 0.9, 0)})
        detections = YoloxDecoder().decode({"output": output}, make_meta(ratio=0.65))
        assert len(detections) == 1
        detection = detections[0]
        assert detection.label_index == 0
        assert detection.confidence == pytest.approx(0.9, abs=1e-3)
        assert detection.box.x == pytest.approx((208 - 52) / 0.65 / 640, abs=1e-3)
        assert detection.box.y == pytest.approx((208 - 52) / 0.65 / 480, abs=1e-3)
        assert detection.box.width == pytest.approx(104 / 0.65 / 640, abs=1e-3)
        assert detection.box.height == pytest.approx(104 / 0.65 / 480, abs=1e-3)

    def test_score_is_objectness_times_class_score(self) -> None:
        output = raw_output({0: (1.0, 1.0, 0.0, 0.0, 0.8, 3)})
        output[0, 0, 5 + 3] = 0.5
        detections = YoloxDecoder().decode({"output": output}, make_meta())
        assert detections[0].confidence == pytest.approx(0.4, abs=1e-3)
        assert detections[0].label_index == 3

    def test_background_cells_are_filtered_by_score_floor(self) -> None:
        detections = YoloxDecoder().decode({"output": raw_output({})}, make_meta())
        assert detections == []

    def test_out_of_frame_boxes_are_clamped_or_dropped(self) -> None:
        # Enormous box centered near the origin: clamped into [0, 1].
        output = raw_output({0: (0.0, 0.0, 6.0, 6.0, 0.9, 0)})
        detections = YoloxDecoder().decode({"output": output}, make_meta())
        assert len(detections) == 1
        box = detections[0].box
        assert box.x >= 0.0 and box.y >= 0.0
        assert box.x + box.width <= 1.0 and box.y + box.height <= 1.0

    def test_wrong_cell_count_fails_loudly(self) -> None:
        bad = np.zeros((1, 100, 85), dtype=np.float32)
        with pytest.raises(DetectorError, match="expected 3549"):
            YoloxDecoder().decode({"output": bad}, make_meta())

    def test_missing_output_fails_loudly(self) -> None:
        with pytest.raises(DetectorError, match="missing"):
            YoloxDecoder().decode({"other": raw_output({})}, make_meta())

    def test_requires_yolox_meta(self) -> None:
        with pytest.raises(DetectorError, match="YoloxMeta"):
            YoloxDecoder().decode({"output": raw_output({})}, meta=None)


def test_coco_labels_are_80_with_person_first() -> None:
    assert len(COCO_LABELS) == 80
    assert COCO_LABELS[0] == "person"
    assert len(set(COCO_LABELS)) == 80
