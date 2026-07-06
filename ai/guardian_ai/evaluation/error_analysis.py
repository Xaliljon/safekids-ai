"""error-analysis.json: where the model is actually failing, per image.

Reuses ``evaluate_detections``'s exact greedy per-image matching (same
IoU/score thresholds, same ``_match_image`` routine) so error analysis
and the headline metrics can never quietly disagree about which
detection was a true/false positive.

Five views, each answering a different "why is it wrong" question:

- **top FP images** — images with the most spurious detections.
- **top FN images** — images with the most missed people.
- **worst-confidence predictions** — false positives the model was most
  *sure* about (high score, wrong anyway) — the most misleading mistakes.
- **worst localization** — correctly-classified detections with the
  lowest IoU against their ground truth (right person, sloppy box).
- **most confused classes** — (actual, predicted) label pairs, ranked by
  how often a matched box got the wrong class.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.evaluation.detection import _match_image
from guardian_ai.training.families import Prediction

ERROR_ANALYSIS_FILE = "error-analysis.json"


def analyze_errors(
    predictions: list[Prediction],
    ground_truths: list[tuple[np.ndarray, np.ndarray]],
    image_paths: list[str],
    class_names: list[str],
    iou_threshold: float = 0.5,
    score_threshold: float = 0.25,
    top_k: int = 10,
) -> dict[str, Any]:
    if not (len(predictions) == len(ground_truths) == len(image_paths)):
        raise ValueError(
            f"predictions ({len(predictions)}), ground_truths ({len(ground_truths)}) and "
            f"image_paths ({len(image_paths)}) must have the same length"
        )

    per_image: list[dict[str, Any]] = []
    confused_pairs: Counter[tuple[str, str]] = Counter()
    low_confidence_false_positives: list[dict[str, Any]] = []
    poor_localizations: list[dict[str, Any]] = []

    for image_path, prediction, (gt_boxes, gt_labels) in zip(
        image_paths, predictions, ground_truths, strict=True
    ):
        outcomes = _match_image(prediction, gt_boxes, gt_labels, iou_threshold, score_threshold)
        false_positives = [outcome for outcome in outcomes if not outcome["correct"]]
        true_positives = [outcome for outcome in outcomes if outcome["correct"]]

        false_negatives = _count_false_negatives(outcomes, gt_labels)

        for outcome in false_positives:
            low_confidence_false_positives.append(
                {
                    "image": image_path,
                    "predicted_label": class_names[outcome["label"]],
                    "confidence": outcome["score"],
                    "best_iou": outcome["iou"],
                }
            )
            if outcome["matched"] and outcome["gt_label"] is not None:
                confused_pairs[
                    (class_names[outcome["gt_label"]], class_names[outcome["label"]])
                ] += 1

        for outcome in true_positives:
            poor_localizations.append(
                {
                    "image": image_path,
                    "label": class_names[outcome["label"]],
                    "confidence": outcome["score"],
                    "iou": outcome["iou"],
                }
            )

        per_image.append(
            {
                "image": image_path,
                "false_positives": len(false_positives),
                "false_negatives": false_negatives,
                "ground_truths": int(len(gt_labels)),
            }
        )

    top_fp_images = sorted(per_image, key=lambda entry: entry["false_positives"], reverse=True)
    top_fn_images = sorted(per_image, key=lambda entry: entry["false_negatives"], reverse=True)
    worst_confidence = sorted(
        low_confidence_false_positives, key=lambda entry: entry["confidence"], reverse=True
    )
    worst_localization = sorted(poor_localizations, key=lambda entry: entry["iou"])

    return {
        "settings": {"iou_threshold": iou_threshold, "score_threshold": score_threshold},
        "images_analyzed": len(per_image),
        "top_false_positive_images": [
            entry for entry in top_fp_images[:top_k] if entry["false_positives"] > 0
        ],
        "top_false_negative_images": [
            entry for entry in top_fn_images[:top_k] if entry["false_negatives"] > 0
        ],
        "worst_confidence_false_positives": worst_confidence[:top_k],
        "worst_localization": worst_localization[:top_k],
        "most_confused_classes": [
            {"actual": actual, "predicted": predicted, "count": count}
            for (actual, predicted), count in confused_pairs.most_common(top_k)
        ],
    }


def _count_false_negatives(outcomes: list[dict[str, Any]], gt_labels: np.ndarray) -> int:
    """Ground truths with no satisfying match — mirrors evaluate_detections."""
    matched_count: dict[int, int] = {}
    for outcome in outcomes:
        if outcome["correct"] or outcome["matched"]:
            gt_label = outcome["gt_label"]
            if gt_label is not None:
                matched_count[gt_label] = matched_count.get(gt_label, 0) + 1
    missed = 0
    for label in gt_labels:
        label_int = int(label)
        if matched_count.get(label_int, 0) > 0:
            matched_count[label_int] -= 1
        else:
            missed += 1
    return missed


def save_error_analysis(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
