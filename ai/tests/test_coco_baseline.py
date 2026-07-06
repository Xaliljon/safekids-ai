"""COCO-pretrained baseline: preprocessing + decode math, no network needed.

``fetch_official_checkpoint``/``evaluate_coco_baseline`` need a real
network fetch and the edge/ project and are exercised manually (Sprint 19
report); here we test everything that doesn't require either.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from guardian_ai.training.coco_baseline import (
    COCO_INPUT_SIZE,
    _grid_and_stride,
    decode,
    fetch_official_checkpoint,
    preprocess,
)
from guardian_ai.training.errors import TrainingConfigurationError


class TestPreprocess:
    def test_wider_image_scales_to_width_and_pads_bottom_right(self) -> None:
        image = np.zeros((300, 416, 3), dtype=np.uint8)
        tensor, ratio = preprocess(image, input_size=416)
        assert tensor.shape == (1, 3, 416, 416)
        assert ratio == pytest.approx(1.0)  # already matches target width

    def test_output_is_bgr_zero_to_255_not_normalized(self) -> None:
        image = np.zeros((416, 416, 3), dtype=np.uint8)
        image[0, 0] = [10, 20, 30]  # RGB
        tensor, _ = preprocess(image, input_size=416)
        # channel-first BGR: channel 0 should be the source's blue (30)
        assert tensor[0, 0, 0, 0] == pytest.approx(30.0)
        assert tensor[0, 2, 0, 0] == pytest.approx(10.0)
        assert tensor.max() > 1.0  # never normalized to [0,1]

    def test_padding_uses_114_and_is_anchored_top_left(self) -> None:
        image = np.zeros((208, 416, 3), dtype=np.uint8)  # half height -> ratio 1, pad bottom
        tensor, ratio = preprocess(image, input_size=416)
        assert ratio == pytest.approx(1.0)
        bottom_row_bgr = tensor[0, :, 415, 0]
        assert np.allclose(bottom_row_bgr, 114.0)
        top_row_bgr = tensor[0, :, 0, 0]
        assert np.allclose(top_row_bgr, 0.0)  # real content, not padding


class TestGridAndStride:
    def test_matches_expected_anchor_count(self) -> None:
        grid, stride = _grid_and_stride(416)
        assert grid.shape[0] == stride.shape[0]
        expected = (416 // 8) ** 2 + (416 // 16) ** 2 + (416 // 32) ** 2
        assert grid.shape[0] == expected


class TestDecode:
    def _raw_output(self, num_anchors: int, num_classes: int = 80) -> np.ndarray:
        raw = np.zeros((1, num_anchors, 5 + num_classes), dtype=np.float32)
        return raw

    def test_no_detections_above_floor_returns_empty(self) -> None:
        grid, _ = _grid_and_stride(COCO_INPUT_SIZE)
        raw = self._raw_output(grid.shape[0])
        prediction = decode(raw, ratio=1.0, original_width=640, original_height=480)
        assert prediction.boxes.shape == (0, 4)
        assert prediction.scores.shape == (0,)

    def test_single_confident_person_detection_decodes_to_expected_box(self) -> None:
        grid, stride = _grid_and_stride(COCO_INPUT_SIZE)
        raw = self._raw_output(grid.shape[0])
        # pick the anchor at grid cell (10,10) on the stride-8 map (index 10*52+10)
        anchor_index = 10 * (COCO_INPUT_SIZE // 8) + 10
        raw[0, anchor_index, 0:2] = 0.0  # dx=dy=0 -> center exactly at grid cell
        raw[0, anchor_index, 2:4] = np.log(1.0)  # size = 1*stride = 8px
        raw[0, anchor_index, 4] = 1.0  # objectness already "sigmoided" (=1)
        raw[0, anchor_index, 5] = 1.0  # COCO class 0 (person) score = 1
        prediction = decode(raw, ratio=1.0, original_width=416, original_height=416)
        assert len(prediction.scores) == 1
        assert prediction.scores[0] == pytest.approx(1.0)
        assert prediction.labels[0] == 0  # mapped onto target_label_index (default 0)
        # center should land near (10*8+4)/416 = 84/416 in both axes
        assert prediction.boxes[0, 0] == pytest.approx(84 / 416, abs=0.01)

    def test_target_label_index_remaps_person_class(self) -> None:
        grid, stride = _grid_and_stride(COCO_INPUT_SIZE)
        raw = self._raw_output(grid.shape[0])
        raw[0, 0, 2:4] = np.log(1.0)
        raw[0, 0, 4] = 1.0
        raw[0, 0, 5] = 1.0
        prediction = decode(
            raw, ratio=1.0, original_width=416, original_height=416, target_label_index=2
        )
        assert prediction.labels[0] == 2

    def test_mismatched_anchor_count_is_rejected(self) -> None:
        raw = self._raw_output(num_anchors=10)  # wrong count for 416 input
        with pytest.raises(TrainingConfigurationError, match="expected"):
            decode(raw, ratio=1.0, original_width=416, original_height=416)

    def test_nms_suppresses_duplicate_person_detections(self) -> None:
        grid, stride = _grid_and_stride(COCO_INPUT_SIZE)
        raw = self._raw_output(grid.shape[0])
        width = COCO_INPUT_SIZE // 8
        first, second = 10 * width + 10, 10 * width + 11  # adjacent cells, same-ish box
        for index in (first, second):
            raw[0, index, 2:4] = np.log(4.0)  # a fairly large, overlapping box
            raw[0, index, 4] = 1.0
            raw[0, index, 5] = 0.9
        prediction = decode(raw, ratio=1.0, original_width=416, original_height=416)
        assert len(prediction.scores) == 1  # the near-duplicate was suppressed


def test_fetch_refuses_missing_edge_project(tmp_path: Path) -> None:
    with pytest.raises(TrainingConfigurationError, match="edge project not found"):
        fetch_official_checkpoint(tmp_path / "zoo", tmp_path / "no-such-edge-project")


def test_fetch_reuses_already_installed_artifact(tmp_path: Path) -> None:
    installed = tmp_path / "zoo" / "yolox-tiny" / "0.1.1-rc0" / "model.onnx"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"already here")
    # edge_project_root need not even exist since the artifact is already present
    result = fetch_official_checkpoint(tmp_path / "zoo", tmp_path / "no-such-edge-project")
    assert result == installed
