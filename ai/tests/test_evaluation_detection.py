"""Detection metrics verified against hand-computed cases."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from guardian_ai.evaluation.detection import (
    box_iou,
    evaluate_detections,
    save_evaluation,
)
from guardian_ai.training.families import Prediction

CLASSES = ["adult", "child"]


def prediction(box: list[float], score: float, label: int) -> Prediction:
    return Prediction(
        boxes=np.array([box], dtype=np.float32),
        scores=np.array([score], dtype=np.float32),
        labels=np.array([label], dtype=np.int64),
    )


def truth(box: list[float], label: int) -> tuple[np.ndarray, np.ndarray]:
    return np.array([box], dtype=np.float32), np.array([label], dtype=np.int64)


def test_box_iou_hand_cases() -> None:
    box = np.array([0.5, 0.5, 0.2, 0.2])
    assert box_iou(box, box) == pytest.approx(1.0)
    disjoint = np.array([0.1, 0.1, 0.1, 0.1])
    assert box_iou(box, disjoint) == 0.0
    # half-overlapping same-size boxes: inter=0.5A, union=1.5A -> 1/3
    shifted = np.array([0.6, 0.5, 0.2, 0.2])
    assert box_iou(box, shifted) == pytest.approx(1 / 3, abs=1e-6)


def test_perfect_prediction() -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    result = evaluate_detections([prediction(box, 0.9, 1)], [truth(box, 1)], CLASSES)
    overall = result["overall"]
    assert overall["precision"] == 1.0
    assert overall["recall"] == 1.0
    assert overall["f1"] == 1.0
    assert overall["false_positives"] == 0
    assert overall["false_negatives"] == 0
    assert result["per_class"]["child"]["ap50"] == pytest.approx(1.0, abs=0.01)
    # confusion: child -> child
    matrix = result["confusion_matrix"]["matrix"]
    assert matrix[1][1] == 1


def test_wrong_class_right_box_is_fp_and_fn() -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    result = evaluate_detections([prediction(box, 0.9, 0)], [truth(box, 1)], CLASSES)
    overall = result["overall"]
    assert overall["precision"] == 0.0
    assert overall["recall"] == 0.0
    assert overall["false_positives"] == 1
    assert overall["false_negatives"] == 1
    # confusion records the misclassification: actual child, predicted adult
    assert result["confusion_matrix"]["matrix"][1][0] == 1


def test_low_iou_is_background_fp_and_missed_gt() -> None:
    result = evaluate_detections(
        [prediction([0.2, 0.2, 0.1, 0.1], 0.9, 1)],
        [truth([0.8, 0.8, 0.1, 0.1], 1)],
        CLASSES,
    )
    matrix = result["confusion_matrix"]["matrix"]
    background = len(CLASSES)
    assert matrix[background][1] == 1  # background -> child (FP)
    assert matrix[1][background] == 1  # child -> background (FN)
    assert result["overall"]["false_positives"] == 1
    assert result["overall"]["false_negatives"] == 1


def test_below_score_threshold_is_ignored() -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    result = evaluate_detections(
        [prediction(box, 0.1, 1)], [truth(box, 1)], CLASSES, score_threshold=0.25
    )
    assert result["overall"]["false_positives"] == 0
    assert result["overall"]["false_negatives"] == 1


def test_mixed_batch_hand_computed() -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    predictions = [
        prediction(box, 0.9, 1),  # image 0: correct child
        prediction(box, 0.8, 1),  # image 1: predicts child, truth adult
        prediction([0.1, 0.1, 0.05, 0.05], 0.7, 0),  # image 2: background FP
    ]
    truths = [truth(box, 1), truth(box, 0), truth(box, 0)]
    overall = evaluate_detections(predictions, truths, CLASSES)["overall"]
    # TP=1 (child), FP=2 (misclass + background), FN=2 (adult x2)
    assert overall["precision"] == pytest.approx(1 / 3, abs=1e-4)
    assert overall["recall"] == pytest.approx(1 / 3, abs=1e-4)
    assert overall["false_positives"] == 2
    assert overall["false_negatives"] == 2


def test_map_50_95_less_or_equal_map50() -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    slightly_off = [0.52, 0.52, 0.3, 0.3]
    result = evaluate_detections([prediction(slightly_off, 0.9, 1)], [truth(box, 1)], CLASSES)
    assert result["overall"]["map50_95"] <= result["overall"]["map50"]


def test_mismatched_lengths_refused() -> None:
    with pytest.raises(ValueError, match="prediction sets"):
        evaluate_detections([], [truth([0.5, 0.5, 0.1, 0.1], 0)], CLASSES)


def test_save_evaluation(tmp_path: Path) -> None:
    box = [0.5, 0.5, 0.3, 0.3]
    result = evaluate_detections([prediction(box, 0.9, 1)], [truth(box, 1)], CLASSES)
    destination = tmp_path / "reports" / "evaluation.json"
    save_evaluation(result, destination)
    assert json.loads(destination.read_text())["overall"]["f1"] == 1.0
