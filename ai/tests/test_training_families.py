"""Detector families: the engine never depends on one detector."""

from __future__ import annotations

import numpy as np
import pytest

from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.families import (
    TinySsdFamily,
    available_families,
    family_metadata,
    get_family,
    reserved_families,
)


def test_tiny_ssd_is_available() -> None:
    assert "tiny-ssd" in available_families()
    family = get_family("tiny-ssd")
    assert family.license == "Proprietary-GuardianAI"


@pytest.mark.parametrize("variant", ["nano", "tiny", "s", "m", "l"])
def test_official_yolox_variants_are_available_since_sprint_19_1(variant: str) -> None:
    # unlocked by the Sprint 19 architecture review; Sprint 19.1 swapped the
    # custom from-scratch implementation for the official Apache-2.0 package
    # (architecture/detector-integration.md) — see test_official_yolox.py.
    name = f"yolox-{variant}"
    assert name in available_families()
    assert name not in reserved_families()
    family = get_family(name)
    assert family.license == "Apache-2.0"
    assert family.name == name


@pytest.mark.parametrize("name", ["yolov8", "yolo11", "rt-detr"])
def test_reserved_families_fail_loudly(name: str) -> None:
    assert name in reserved_families()
    with pytest.raises(TrainingConfigurationError, match="reserved"):
        get_family(name)


def test_agpl_families_cite_the_license_block() -> None:
    with pytest.raises(TrainingConfigurationError, match="AGPL"):
        get_family("yolov8")


def test_unknown_family_lists_options() -> None:
    with pytest.raises(TrainingConfigurationError, match="unknown detector family"):
        get_family("mystery-net")


def test_tiny_ssd_forward_loss_decode() -> None:
    import torch

    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    images = torch.rand(2, 3, 64, 64)
    outputs = model(images)
    assert outputs.shape == (2, 5 + 3)
    # box channels are sigmoid-bounded: always a valid normalized box
    assert float(outputs[:, :4].min()) >= 0.0
    assert float(outputs[:, :4].max()) <= 1.0

    boxes = torch.tensor([[0.5, 0.5, 0.3, 0.3], [0.4, 0.4, 0.2, 0.2]])
    labels = torch.tensor([0, 2])
    targets = [(boxes[0:1], labels[0:1]), (boxes[1:2], labels[1:2])]
    loss = family.loss(outputs, targets)
    assert loss.requires_grad
    assert float(loss) > 0

    predictions = family.decode(outputs)
    assert len(predictions) == 2
    prediction = predictions[0]
    assert prediction.boxes.shape == (1, 4)
    assert prediction.scores.shape == (1,)
    assert 0.0 <= float(prediction.scores[0]) <= 1.0
    assert prediction.labels.dtype == np.int64


def test_family_metadata_matches_export_contract() -> None:
    family = TinySsdFamily()
    metadata = family_metadata(family, num_classes=3, input_size=96)
    assert metadata["input_name"] == "images"
    assert metadata["output_name"] == "output"
    assert metadata["input_shape"] == [1, 3, 96, 96]
    assert metadata["license"] == "Proprietary-GuardianAI"
