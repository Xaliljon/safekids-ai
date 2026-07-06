"""Detection evaluation: the full ethics-mandated metric set (docs/04).

Pure numpy — no framework, so the numbers are testable against hand
calculations. Computes precision, recall, F1, mAP@50, mAP@50-95, a
confusion matrix (with background row/column for FP/FN), absolute FP/FN
counts and per-class metrics, and writes ``evaluation.json``.

Boxes are normalized (cx, cy, w, h). Matching is greedy by score at a
given IoU threshold, one ground truth per prediction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.training.families import Prediction

EVALUATION_FILE = "evaluation.json"
_MAP_THRESHOLDS = [round(0.5 + 0.05 * step, 2) for step in range(10)]  # .5 .. .95


def box_iou(first: np.ndarray, second: np.ndarray) -> float:
    """IoU of two (cx, cy, w, h) boxes."""

    def corners(box: np.ndarray) -> tuple[float, float, float, float]:
        return (
            float(box[0] - box[2] / 2),
            float(box[1] - box[3] / 2),
            float(box[0] + box[2] / 2),
            float(box[1] + box[3] / 2),
        )

    ax1, ay1, ax2, ay2 = corners(first)
    bx1, by1, bx2, by2 = corners(second)
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def _match_image(
    prediction: Prediction,
    gt_boxes: np.ndarray,
    gt_labels: np.ndarray,
    iou_threshold: float,
    score_threshold: float,
) -> list[dict[str, Any]]:
    """Per-prediction outcomes for one image (greedy, score-ordered)."""
    order = np.argsort(-prediction.scores)
    taken: set[int] = set()
    outcomes = []
    for index in order:
        if prediction.scores[index] < score_threshold:
            continue
        best_iou, best_gt = 0.0, -1
        for gt_index in range(len(gt_labels)):
            if gt_index in taken:
                continue
            iou = box_iou(prediction.boxes[index], gt_boxes[gt_index])
            if iou > best_iou:
                best_iou, best_gt = iou, gt_index
        matched = best_iou >= iou_threshold and best_gt >= 0
        if matched:
            taken.add(best_gt)
        outcomes.append(
            {
                "score": float(prediction.scores[index]),
                "label": int(prediction.labels[index]),
                "matched": matched,
                "gt_label": int(gt_labels[best_gt]) if best_gt >= 0 and matched else None,
                "correct": matched and int(prediction.labels[index]) == int(gt_labels[best_gt]),
                "iou": float(best_iou),  # best available IoU, even for unmatched/FP predictions
            }
        )
    return outcomes


def _average_precision(scores: list[float], correct: list[bool], total_gt: int) -> float:
    """101-point interpolated AP for one class at one IoU threshold."""
    if total_gt == 0:
        return 0.0
    order = np.argsort(-np.asarray(scores)) if scores else np.array([], dtype=int)
    tp = np.cumsum([1 if correct[i] else 0 for i in order]) if len(order) else np.array([])
    fp = np.cumsum([0 if correct[i] else 1 for i in order]) if len(order) else np.array([])
    if len(tp) == 0:
        return 0.0
    recalls = tp / total_gt
    precisions = tp / np.maximum(tp + fp, 1e-9)
    ap = 0.0
    for point in np.linspace(0.0, 1.0, 101):
        mask = recalls >= point
        ap += float(precisions[mask].max()) if mask.any() else 0.0
    return ap / 101.0


def evaluate_detections(
    predictions: list[Prediction],
    ground_truths: list[tuple[np.ndarray, np.ndarray]],
    class_names: list[str],
    iou_threshold: float = 0.5,
    score_threshold: float = 0.25,
) -> dict[str, Any]:
    """The full metric set over one split. Inputs are per-image pairs."""
    if len(predictions) != len(ground_truths):
        raise ValueError(
            f"{len(predictions)} prediction sets vs {len(ground_truths)} ground truths"
        )
    num_classes = len(class_names)
    confusion = np.zeros((num_classes + 1, num_classes + 1), dtype=int)  # +background
    per_class_tp = np.zeros(num_classes, dtype=int)
    per_class_fp = np.zeros(num_classes, dtype=int)
    per_class_gt = np.zeros(num_classes, dtype=int)
    ap_inputs: dict[float, dict[int, tuple[list[float], list[bool]]]] = {
        threshold: {c: ([], []) for c in range(num_classes)} for threshold in _MAP_THRESHOLDS
    }

    for prediction, (gt_boxes, gt_labels) in zip(predictions, ground_truths, strict=True):
        for label in gt_labels:
            per_class_gt[int(label)] += 1
        matched_gts: set[int] = set()
        outcomes = _match_image(prediction, gt_boxes, gt_labels, iou_threshold, score_threshold)
        for outcome in outcomes:
            predicted = outcome["label"]
            if outcome["correct"]:
                per_class_tp[predicted] += 1
                confusion[outcome["gt_label"]][predicted] += 1
            elif outcome["matched"]:
                per_class_fp[predicted] += 1  # right box, wrong class
                confusion[outcome["gt_label"]][predicted] += 1
            else:
                per_class_fp[predicted] += 1
                confusion[num_classes][predicted] += 1  # background -> class (FP)
            if outcome["gt_label"] is not None:
                matched_gts.add(outcome["gt_label"])
        # every AP threshold sees its own matching
        for threshold in _MAP_THRESHOLDS:
            for entry in _match_image(prediction, gt_boxes, gt_labels, threshold, 0.0):
                scores, correct = ap_inputs[threshold][entry["label"]]
                scores.append(entry["score"])
                correct.append(bool(entry["correct"]))
        # unmatched ground truths are FNs: class -> background column
        matched_count: dict[int, int] = {}
        for outcome in outcomes:
            if outcome["correct"] or outcome["matched"]:
                gt_label = outcome["gt_label"]
                if gt_label is not None:
                    matched_count[gt_label] = matched_count.get(gt_label, 0) + 1
        for label in gt_labels:
            label = int(label)
            if matched_count.get(label, 0) > 0:
                matched_count[label] -= 1
            else:
                confusion[label][num_classes] += 1

    per_class_fn = per_class_gt - per_class_tp
    per_class: dict[str, dict[str, float]] = {}
    ap50_values, map_values = [], []
    for index, name in enumerate(class_names):
        tp, fp, fn = int(per_class_tp[index]), int(per_class_fp[index]), int(per_class_fn[index])
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        ap50 = _average_precision(*ap_inputs[0.5][index], total_gt=int(per_class_gt[index]))
        ap_all = [
            _average_precision(*ap_inputs[threshold][index], total_gt=int(per_class_gt[index]))
            for threshold in _MAP_THRESHOLDS
        ]
        ap50_values.append(ap50)
        map_values.append(float(np.mean(ap_all)))
        per_class[name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "ap50": round(ap50, 4),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "ground_truths": int(per_class_gt[index]),
        }

    total_tp = int(per_class_tp.sum())
    total_fp = int(per_class_fp.sum())
    total_fn = int(per_class_fn.sum())
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "overall": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "map50": round(float(np.mean(ap50_values)) if ap50_values else 0.0, 4),
            "map50_95": round(float(np.mean(map_values)) if map_values else 0.0, 4),
            "false_positives": total_fp,
            "false_negatives": total_fn,
            "images": len(predictions),
        },
        "per_class": per_class,
        "confusion_matrix": {
            "labels": [*class_names, "background"],
            "matrix": confusion.tolist(),
        },
        "thresholds": {"iou": iou_threshold, "score": score_threshold},
    }


def save_evaluation(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
