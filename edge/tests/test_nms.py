"""IoU math and greedy non-maximum suppression."""

import pytest

from guardian_edge.application.vision.nms import GreedyNms
from guardian_edge.application.vision.ports import RawDetection
from guardian_edge.domain.detection import BoundingBox


def raw(
    x: float, y: float, confidence: float, label_index: int = 0, size: float = 0.3
) -> RawDetection:
    return RawDetection(
        label_index=label_index,
        confidence=confidence,
        box=BoundingBox(x=x, y=y, width=size, height=size),
    )


class TestIntersectionOverUnion:
    def test_identical_boxes_have_iou_one(self) -> None:
        box = BoundingBox(x=0.1, y=0.1, width=0.4, height=0.4)
        assert box.intersection_over_union(box) == pytest.approx(1.0)

    def test_disjoint_boxes_have_iou_zero(self) -> None:
        a = BoundingBox(x=0.0, y=0.0, width=0.2, height=0.2)
        b = BoundingBox(x=0.5, y=0.5, width=0.2, height=0.2)
        assert a.intersection_over_union(b) == 0.0

    def test_known_overlap(self) -> None:
        a = BoundingBox(x=0.0, y=0.0, width=0.4, height=0.4)
        b = BoundingBox(x=0.2, y=0.0, width=0.4, height=0.4)
        # intersection 0.2*0.4 = 0.08; union 0.16 + 0.16 - 0.08 = 0.24
        assert a.intersection_over_union(b) == pytest.approx(0.08 / 0.24)

    def test_symmetric(self) -> None:
        a = BoundingBox(x=0.0, y=0.0, width=0.4, height=0.4)
        b = BoundingBox(x=0.1, y=0.1, width=0.4, height=0.4)
        assert a.intersection_over_union(b) == pytest.approx(b.intersection_over_union(a))


class TestGreedyNms:
    def test_keeps_most_confident_of_overlapping_pair(self) -> None:
        weaker = raw(0.11, 0.11, confidence=0.7)
        stronger = raw(0.10, 0.10, confidence=0.9)
        kept = GreedyNms().suppress([weaker, stronger], iou_threshold=0.45)
        assert kept == [stronger]

    def test_keeps_non_overlapping_candidates(self) -> None:
        candidates = [raw(0.0, 0.0, 0.9), raw(0.6, 0.6, 0.8)]
        assert len(GreedyNms().suppress(candidates, iou_threshold=0.45)) == 2

    def test_class_aware_by_default(self) -> None:
        person = raw(0.10, 0.10, confidence=0.9, label_index=0)
        child = raw(0.11, 0.11, confidence=0.7, label_index=1)
        kept = GreedyNms().suppress([person, child], iou_threshold=0.45)
        assert len(kept) == 2, "different classes never suppress each other"

    def test_class_agnostic_mode_suppresses_across_classes(self) -> None:
        person = raw(0.10, 0.10, confidence=0.9, label_index=0)
        child = raw(0.11, 0.11, confidence=0.7, label_index=1)
        kept = GreedyNms(class_aware=False).suppress([person, child], iou_threshold=0.45)
        assert kept == [person]

    def test_high_threshold_keeps_moderate_overlaps(self) -> None:
        a = raw(0.10, 0.10, confidence=0.9)
        b = raw(0.20, 0.20, confidence=0.8)  # partial overlap
        assert len(GreedyNms().suppress([a, b], iou_threshold=0.99)) == 2

    def test_empty_input_gives_empty_output(self) -> None:
        assert GreedyNms().suppress([], iou_threshold=0.45) == []
