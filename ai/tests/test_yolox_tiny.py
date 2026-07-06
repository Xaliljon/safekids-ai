"""YOLOX-Tiny: build, loss, decode, export — the production family."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from guardian_ai.export.onnx_export import export_onnx
from guardian_ai.training.families import Prediction, get_family, reserved_families
from guardian_ai.training.yolox_tiny import (
    YoloxTinyFamily,
    _nms,
    _pairwise_iou,
    build_anchor_grid,
)


def test_yolox_tiny_registered_and_unreserved() -> None:
    assert "yolox-tiny" not in reserved_families()
    family = get_family("yolox-tiny")
    assert isinstance(family, YoloxTinyFamily)
    assert family.license == "Proprietary-GuardianAI"
    assert family.input_name() == "images"
    assert family.output_name() == "output"


def test_anchor_grid_shape_and_order() -> None:
    grid = build_anchor_grid(160, strides=(8, 16, 32))
    # 20x20 + 10x10 + 5x5 = 400 + 100 + 25
    assert grid.shape == (525, 3)
    assert grid[0].tolist() == [0.0, 0.0, 8.0]
    assert grid[399].tolist() == [19.0, 19.0, 8.0]  # last stride-8 cell
    assert grid[400].tolist() == [0.0, 0.0, 16.0]  # first stride-16 cell


class TestBuildForwardDecode:
    @pytest.fixture(scope="class")
    def family(self) -> YoloxTinyFamily:
        family = YoloxTinyFamily()
        family.build(num_classes=4, input_size=128)
        return family

    def test_train_mode_returns_raw_logits(self, family: YoloxTinyFamily) -> None:
        model = family.build(num_classes=4, input_size=128)
        model.train()
        out = model(torch.rand(2, 3, 128, 128))
        assert out.shape == (2, (16 * 16 + 8 * 8 + 4 * 4), 9)
        # unbounded logits: at least one value outside [0,1] somewhere is expected
        assert out.detach().numpy().min() < 0 or out.detach().numpy().max() > 1

    def test_eval_mode_sigmoids_obj_and_cls_only(self, family: YoloxTinyFamily) -> None:
        model = family.build(num_classes=4, input_size=128)
        model.eval()
        with torch.no_grad():
            out = model(torch.rand(2, 3, 128, 128))
        obj_cls = out[..., 4:].numpy()
        assert obj_cls.min() >= 0.0 and obj_cls.max() <= 1.0

    def test_decode_returns_one_prediction_per_image(self, family: YoloxTinyFamily) -> None:
        model = family.build(num_classes=4, input_size=128)
        model.eval()
        with torch.no_grad():
            out = model(torch.rand(3, 3, 128, 128))
        predictions = family.decode(out)
        assert len(predictions) == 3
        for prediction in predictions:
            assert isinstance(prediction, Prediction)
            assert prediction.boxes.shape[1] == 4 if prediction.boxes.size else True
            assert prediction.scores.dtype == np.float32
            assert prediction.labels.dtype == np.int64

    def test_decode_accepts_numpy_directly(self, family: YoloxTinyFamily) -> None:
        model = family.build(num_classes=4, input_size=128)
        model.eval()
        with torch.no_grad():
            out = model(torch.rand(1, 3, 128, 128)).numpy()
        predictions = family.decode(out)
        assert len(predictions) == 1


class TestLoss:
    def test_loss_decreases_when_overfitting_one_box(self) -> None:
        """A tiny sanity check: repeated gradient steps on a single fixed
        target must reduce the loss — proves the assignment+loss actually
        teach the model something, not just "runs without crashing"."""
        family = YoloxTinyFamily()
        model = family.build(num_classes=2, input_size=64)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
        images = torch.rand(1, 3, 64, 64)
        targets = [(torch.tensor([[0.5, 0.5, 0.3, 0.3]]), torch.tensor([1]))]

        model.train()
        losses = []
        for _ in range(15):
            optimizer.zero_grad()
            out = model(images)
            loss = family.loss(out, targets)
            loss.backward()
            optimizer.step()
            losses.append(float(loss))
        assert losses[-1] < losses[0]

    def test_loss_handles_multi_object_and_empty_targets(self) -> None:
        family = YoloxTinyFamily()
        model = family.build(num_classes=3, input_size=64)
        model.train()
        images = torch.rand(2, 3, 64, 64)
        out = model(images)
        targets = [
            (
                torch.tensor([[0.3, 0.3, 0.2, 0.2], [0.7, 0.7, 0.1, 0.1]]),
                torch.tensor([0, 2]),
            ),
            (torch.zeros((0, 4)), torch.zeros((0,), dtype=torch.long)),  # no GTs
        ]
        loss = family.loss(out, targets)
        assert torch.isfinite(loss)
        loss.backward()

    def test_loss_requires_build_first(self) -> None:
        from guardian_ai.training.errors import TrainingConfigurationError

        family = YoloxTinyFamily()
        with pytest.raises(TrainingConfigurationError, match="build"):
            family.loss(torch.zeros(1, 1, 9), [(torch.zeros(0, 4), torch.zeros(0).long())])

    def test_decode_requires_build_first(self) -> None:
        from guardian_ai.training.errors import TrainingConfigurationError

        family = YoloxTinyFamily()
        with pytest.raises(TrainingConfigurationError, match="build"):
            family.decode(torch.zeros(1, 1, 9))


class TestAssignment:
    def test_every_gt_gets_at_least_one_positive_anchor(self) -> None:
        family = YoloxTinyFamily()
        family.build(num_classes=2, input_size=64)
        # a tiny box, smaller than even the finest (stride-8) grid cell
        boxes_px = np.array([[32.0, 32.0, 2.0, 2.0]], dtype=np.float32)
        anchor_centers = (family._anchor_grid[:, :2] + 0.5) * family._anchor_grid[:, 2:3]
        assignments = family._assign(boxes_px, anchor_centers)
        assert len(assignments) == 1
        assert assignments[0].size >= 1

    def test_overlapping_gts_prefer_smaller_area(self) -> None:
        family = YoloxTinyFamily()
        family.build(num_classes=2, input_size=64)
        anchor_centers = (family._anchor_grid[:, :2] + 0.5) * family._anchor_grid[:, 2:3]
        # a big box and a small box centered at the same point: the small
        # one should win any anchor both claim
        boxes_px = np.array([[32.0, 32.0, 40.0, 40.0], [32.0, 32.0, 8.0, 8.0]], dtype=np.float32)
        assignments = family._assign(boxes_px, anchor_centers)
        overlap = set(assignments[0].tolist()) & set(assignments[1].tolist())
        assert overlap == set()  # no anchor is claimed by both


class TestNmsAndIou:
    def test_pairwise_iou_identity_and_disjoint(self) -> None:
        box = np.array([[0.5, 0.5, 0.2, 0.2]])
        disjoint = np.array([[0.1, 0.1, 0.05, 0.05]])
        assert _pairwise_iou(box, box)[0, 0] == pytest.approx(1.0)
        assert _pairwise_iou(box, disjoint)[0, 0] == 0.0

    def test_nms_suppresses_duplicate_boxes(self) -> None:
        boxes = np.array([[0.5, 0.5, 0.2, 0.2], [0.51, 0.51, 0.2, 0.2], [0.1, 0.1, 0.05, 0.05]])
        scores = np.array([0.9, 0.8, 0.7])
        kept = _nms(boxes, scores, iou_threshold=0.45)
        assert 0 in kept  # highest score kept
        assert 1 not in kept  # suppressed as a near-duplicate of 0
        assert 2 in kept  # disjoint box survives


def test_yolox_tiny_exports_and_validates(tmp_path: Path) -> None:
    family = YoloxTinyFamily()
    model = family.build(num_classes=4, input_size=64)
    destination = tmp_path / "model.onnx"
    sha256 = export_onnx(model, family, 64, destination)
    assert len(sha256) == 64
    assert destination.is_file()
