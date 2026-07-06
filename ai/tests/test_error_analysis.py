"""error-analysis.json: hand-verified FP/FN counts, confidence, IoU, confusion."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from guardian_ai.evaluation.error_analysis import (
    ERROR_ANALYSIS_FILE,
    analyze_errors,
    save_error_analysis,
)
from guardian_ai.training.families import Prediction

CLASSES = ["adult", "child"]


def prediction(boxes: list[list[float]], scores: list[float], labels: list[int]) -> Prediction:
    return Prediction(
        boxes=np.array(boxes, dtype=np.float32),
        scores=np.array(scores, dtype=np.float32),
        labels=np.array(labels, dtype=np.int64),
    )


def truth(boxes: list[list[float]], labels: list[int]) -> tuple[np.ndarray, np.ndarray]:
    return np.array(boxes, dtype=np.float32), np.array(labels, dtype=np.int64)


BOX = [0.5, 0.5, 0.3, 0.3]
FAR_BOX = [0.1, 0.1, 0.05, 0.05]


def test_length_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="same length"):
        analyze_errors([], [truth([BOX], [0])], ["a.png"], CLASSES)


def test_perfect_image_contributes_nothing() -> None:
    result = analyze_errors(
        [prediction([BOX], [0.9], [1])],
        [truth([BOX], [1])],
        ["ok.png"],
        CLASSES,
    )
    assert result["top_false_positive_images"] == []
    assert result["top_false_negative_images"] == []
    assert result["most_confused_classes"] == []


def test_false_positive_ranking_and_confidence() -> None:
    # image A: one confident false positive (background -> adult, score .9)
    # image B: one less-confident false positive
    predictions = [
        prediction([FAR_BOX], [0.9], [0]),
        prediction([FAR_BOX], [0.4], [0]),
    ]
    truths = [truth([], []), truth([], [])]
    result = analyze_errors(predictions, truths, ["a.png", "b.png"], CLASSES)

    fp_images = {
        entry["image"]: entry["false_positives"] for entry in result["top_false_positive_images"]
    }
    assert fp_images == {"a.png": 1, "b.png": 1}

    worst = result["worst_confidence_false_positives"]
    assert worst[0]["image"] == "a.png"  # highest-confidence mistake ranks first
    assert worst[0]["confidence"] == pytest.approx(0.9)
    assert worst[1]["confidence"] == pytest.approx(0.4)


def test_false_negative_counting() -> None:
    # two ground truths, only one detected
    predictions = [prediction([BOX], [0.9], [1])]
    truths = [truth([BOX, FAR_BOX], [1, 0])]
    result = analyze_errors(predictions, truths, ["missed.png"], CLASSES, score_threshold=0.25)
    fn_images = {
        entry["image"]: entry["false_negatives"] for entry in result["top_false_negative_images"]
    }
    assert fn_images == {"missed.png": 1}


def test_worst_localization_ranks_lowest_iou_first() -> None:
    # a perfectly-placed box (iou=1) and a sloppily-placed but still-matched box
    tight = [0.5, 0.5, 0.3, 0.3]
    loose_pred = [0.55, 0.55, 0.3, 0.3]  # shifted, still overlaps >0.5 IoU with tight GT
    predictions = [prediction([tight], [0.95], [1]), prediction([loose_pred], [0.8], [0])]
    truths = [truth([tight], [1]), truth([tight], [0])]
    result = analyze_errors(predictions, truths, ["tight.png", "loose.png"], CLASSES)
    localization = result["worst_localization"]
    assert localization[0]["image"] == "loose.png"  # lower IoU ranks first (worst)
    assert localization[0]["iou"] < 1.0
    assert any(
        entry["image"] == "tight.png" and entry["iou"] == pytest.approx(1.0)
        for entry in localization
    )


def test_most_confused_classes() -> None:
    # three images where a child GT gets matched but predicted as adult
    predictions = [prediction([BOX], [0.9], [0])] * 3
    truths = [truth([BOX], [1])] * 3
    result = analyze_errors(predictions, truths, ["x1.png", "x2.png", "x3.png"], CLASSES)
    assert result["most_confused_classes"][0] == {
        "actual": "child",
        "predicted": "adult",
        "count": 3,
    }


def test_top_k_limits_results() -> None:
    predictions = [prediction([FAR_BOX], [0.5 + 0.01 * i], [0]) for i in range(20)]
    truths = [truth([], []) for _ in range(20)]
    paths = [f"img{i}.png" for i in range(20)]
    result = analyze_errors(predictions, truths, paths, CLASSES, top_k=5)
    assert len(result["worst_confidence_false_positives"]) == 5
    assert len(result["top_false_positive_images"]) == 5


def test_settings_and_image_count_recorded() -> None:
    result = analyze_errors(
        [prediction([BOX], [0.9], [1])],
        [truth([BOX], [1])],
        ["a.png"],
        CLASSES,
        iou_threshold=0.6,
        score_threshold=0.3,
    )
    assert result["settings"] == {"iou_threshold": 0.6, "score_threshold": 0.3}
    assert result["images_analyzed"] == 1


def test_save_error_analysis(tmp_path: Path) -> None:
    result = analyze_errors(
        [prediction([BOX], [0.9], [1])], [truth([BOX], [1])], ["a.png"], CLASSES
    )
    destination = tmp_path / "reports" / ERROR_ANALYSIS_FILE
    save_error_analysis(result, destination)
    assert json.loads(destination.read_text())["images_analyzed"] == 1
