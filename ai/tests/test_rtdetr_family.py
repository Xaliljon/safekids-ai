"""RT-DETR adapter (Sprint 22) — candidate only, never promoted.

The convergence proof that actually justifies trusting this adapter is a
recorded experiment, not a test: 800 optimizer steps take minutes. See
reports/model-v1/rtdetr-benchmark-report.md, mirroring how Sprint 19.1
recorded the same proof for YOLOX.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from guardian_ai.training.detectors.rtdetr.targets import to_rtdetr_labels
from guardian_ai.training.detectors.rtdetr.variants import VARIANTS, get_variant
from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.families import available_families, family_metadata, get_family

# ------------------------------------------------------ configuration


def test_every_variant_is_registered_as_a_family() -> None:
    families = available_families()
    for variant in VARIANTS:
        assert f"rtdetr-{variant}" in families


def test_variants_carry_a_pinned_revision() -> None:
    """'main' is not a version. An unpinned reference makes an experiment
    unreproducible, which ADR-0010 does not allow."""
    for variant in VARIANTS.values():
        assert variant.revision
        assert variant.model_id.startswith("PekingU/")


def test_invalid_variant_fails_loudly() -> None:
    with pytest.raises(TrainingConfigurationError, match="unknown rtdetr variant"):
        get_variant("r9000vd")


def test_invalid_family_name_fails_loudly() -> None:
    with pytest.raises(TrainingConfigurationError, match="unknown detector family"):
        get_family("rtdetr-nonexistent")


def test_family_reports_apache_license() -> None:
    """The licence gate's whole point. AGPL RT-DETR implementations exist
    (Ultralytics); this one must not be confusable with them."""
    family = get_family("rtdetr-r18vd")
    assert family.license == "Apache-2.0"
    metadata = family_metadata(family, num_classes=1, input_size=640)
    assert metadata["license"] == "Apache-2.0"
    assert metadata["family"] == "rtdetr-r18vd"


def test_ultralytics_rtdetr_is_not_reachable_through_the_registry() -> None:
    """RT-DETR also ships inside Ultralytics under AGPL-3.0. Sprint 21
    blocked that package by family name and Sprint 22 must not open a door
    back to it under a friendlier label."""
    from guardian_ai.training.families import reserved_families

    reserved = reserved_families()
    for blocked in ("yolov8", "yolo11", "yolov12"):
        assert "AGPL" in reserved[blocked]


def test_loss_before_build_is_refused() -> None:
    family = get_family("rtdetr-r18vd")
    with pytest.raises(TrainingConfigurationError, match="build\\(\\) must run before loss"):
        family.loss(torch.zeros(1, 4, 6), [(torch.zeros(1, 4), torch.zeros(1))])


# ------------------------------------------------------------- targets


def test_targets_pack_without_converting_coordinates() -> None:
    """Guardian and RT-DETR both use normalized cx/cy/w/h, so this is
    packing rather than conversion — there is no transform here to get
    subtly wrong, and this test is what keeps it that way."""
    boxes = torch.tensor([[0.5, 0.5, 0.2, 0.4], [0.1, 0.2, 0.05, 0.05]])
    classes = torch.tensor([0, 0])
    labels = to_rtdetr_labels([(boxes, classes)])
    assert len(labels) == 1
    assert torch.equal(labels[0]["boxes"], boxes)
    assert labels[0]["class_labels"].dtype == torch.int64


def test_targets_keep_per_image_counts() -> None:
    one = (torch.zeros(1, 4), torch.zeros(1))
    three = (torch.zeros(3, 4), torch.zeros(3))
    labels = to_rtdetr_labels([one, three])
    assert [entry["boxes"].shape[0] for entry in labels] == [1, 3]


# -------------------------------------------------------------- decode


def _outputs(rows: list[list[float]]) -> torch.Tensor:
    """One image's worth of [cx, cy, w, h, objectness, class_score]."""
    return torch.tensor([rows], dtype=torch.float32)


def test_decode_returns_normalized_boxes_unchanged() -> None:
    """RT-DETR predicts in [0,1] already; dividing by input_size the way the
    YOLOX family does would shrink every box to nothing."""
    family = get_family("rtdetr-r18vd")
    prediction = family.decode(_outputs([[0.5, 0.5, 0.2, 0.4, 1.0, 0.9]]))[0]
    assert np.allclose(prediction.boxes[0], [0.5, 0.5, 0.2, 0.4])
    assert prediction.scores[0] == pytest.approx(0.9)


def test_decode_applies_the_score_floor() -> None:
    family = get_family("rtdetr-r18vd")
    prediction = family.decode(
        _outputs([[0.5, 0.5, 0.2, 0.4, 1.0, 0.9], [0.1, 0.1, 0.1, 0.1, 1.0, 0.01]])
    )[0]
    assert len(prediction.boxes) == 1


def test_decode_keeps_overlapping_boxes() -> None:
    """No NMS, deliberately: RT-DETR is trained with one-to-one Hungarian
    matching, so duplicate suppression is the loss's job. Adding NMS would
    change the YOLOX comparison in one direction or the other (Sprint 22
    §14) and is documented rather than done."""
    family = get_family("rtdetr-r18vd")
    rows = [[0.5, 0.5, 0.2, 0.4, 1.0, 0.9], [0.51, 0.5, 0.2, 0.4, 1.0, 0.8]]
    assert len(family.decode(_outputs(rows))[0].boxes) == 2


def test_decode_handles_an_image_with_nothing_above_the_floor() -> None:
    family = get_family("rtdetr-r18vd")
    prediction = family.decode(_outputs([[0.5, 0.5, 0.2, 0.4, 1.0, 0.001]]))[0]
    assert prediction.boxes.shape == (0, 4)
    assert prediction.scores.shape == (0,)
    assert prediction.labels.shape == (0,)


def test_decode_picks_the_highest_scoring_class() -> None:
    family = get_family("rtdetr-r18vd")
    prediction = family.decode(_outputs([[0.5, 0.5, 0.2, 0.4, 1.0, 0.2, 0.7, 0.3]]))[0]
    assert prediction.labels[0] == 1
    assert prediction.scores[0] == pytest.approx(0.7)


def test_decode_returns_one_prediction_per_image() -> None:
    family = get_family("rtdetr-r18vd")
    batch = torch.zeros(3, 2, 6)
    batch[:, :, 5] = 0.9
    assert len(family.decode(batch)) == 3


# ---------------------------------------------- contract with the engine


def test_io_names_match_every_other_family() -> None:
    family = get_family("rtdetr-r18vd")
    assert family.input_name() == "images"
    assert family.output_name() == "output"


@pytest.mark.network
def test_build_produces_a_trainable_module_with_guardian_output_shape() -> None:
    """The DetectorFamily contract end to end, minus the training loop.

    Marked network: the variant's config is fetched from its pinned
    HuggingFace revision rather than duplicated here, because a hand-copied
    RTDetrConfig is a second source of truth that drifts.
    """
    family = get_family("rtdetr-r18vd")
    model = family.build(num_classes=1, input_size=320, pretrained=False)
    model.eval()
    with torch.no_grad():
        outputs = model(torch.zeros(1, 3, 320, 320))
    assert outputs.ndim == 3
    assert outputs.shape[0] == 1
    assert outputs.shape[2] == 5 + 1  # cx, cy, w, h, objectness, one class
    assert len(family.decode(outputs)) == 1
