"""Model comparison: PROMOTE/REJECT with reasons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guardian_ai.export.onnx_export import MODEL_FILE, export_onnx
from guardian_ai.training.compare import (
    PROMOTE,
    REJECT,
    BenchmarkResult,
    benchmark_onnx,
    compare_models,
    save_comparison,
)
from guardian_ai.training.families import TinySsdFamily


def evaluation(
    precision: float = 0.8, recall: float = 0.7, false_positives: int = 3
) -> dict[str, Any]:
    return {
        "overall": {
            "precision": precision,
            "recall": recall,
            "f1": 0.75,
            "map50": 0.7,
            "map50_95": 0.5,
            "false_positives": false_positives,
            "false_negatives": 2,
            "images": 10,
        }
    }


BENCH = BenchmarkResult(latency_ms_mean=1.0, latency_ms_p95=1.2, memory_mb=10.0, size_mb=0.5)


def test_equal_models_promote() -> None:
    result = compare_models(evaluation(), evaluation(), BENCH, BENCH)
    assert result["verdict"] == PROMOTE
    assert all(check["passed"] for check in result["checks"])


def test_precision_regression_rejects() -> None:
    result = compare_models(evaluation(precision=0.7), evaluation(), BENCH, BENCH)
    assert result["verdict"] == REJECT
    assert any("precision" in reason for reason in result["reasons"])


def test_recall_regression_rejects() -> None:
    result = compare_models(evaluation(recall=0.5), evaluation(), BENCH, BENCH)
    assert result["verdict"] == REJECT
    assert any("recall" in reason for reason in result["reasons"])


def test_extra_fps_with_held_precision_pass() -> None:
    # dead baseline (0 detections, 0 FP) must not be unbeatable
    candidate = evaluation(precision=0.8, recall=0.7, false_positives=4)
    baseline = evaluation(precision=0.0, recall=0.0, false_positives=0)
    result = compare_models(candidate, baseline, BENCH, BENCH)
    assert result["verdict"] == PROMOTE


def test_extra_fps_with_dropped_precision_reject() -> None:
    candidate = evaluation(precision=0.5, recall=0.75, false_positives=9)
    baseline = evaluation(precision=0.8, recall=0.7, false_positives=3)
    result = compare_models(candidate, baseline, BENCH, BENCH)
    assert result["verdict"] == REJECT
    assert any("false positives" in reason for reason in result["reasons"])


def test_latency_regression_rejects() -> None:
    slow = BenchmarkResult(latency_ms_mean=1.5, latency_ms_p95=1.7, memory_mb=10.0, size_mb=0.5)
    result = compare_models(evaluation(), evaluation(), slow, BENCH)
    assert result["verdict"] == REJECT
    assert any("latency" in reason for reason in result["reasons"])


def test_size_regression_rejects() -> None:
    fat = BenchmarkResult(latency_ms_mean=1.0, latency_ms_p95=1.2, memory_mb=10.0, size_mb=0.9)
    result = compare_models(evaluation(), evaluation(), fat, BENCH)
    assert result["verdict"] == REJECT
    assert any("size" in reason for reason in result["reasons"])


def test_save_comparison(tmp_path: Path) -> None:
    result = compare_models(evaluation(), evaluation(), BENCH, BENCH)
    destination = tmp_path / "comparison.json"
    save_comparison(result, destination)
    assert json.loads(destination.read_text())["verdict"] == PROMOTE


def test_benchmark_onnx_measures_a_real_model(tmp_path: Path) -> None:
    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    destination = tmp_path / MODEL_FILE
    export_onnx(model, family, 64, destination)
    result = benchmark_onnx(destination, "images", (1, 3, 64, 64), runs=5, warmup=1)
    assert result.latency_ms_mean > 0
    assert result.latency_ms_p95 >= 0
    assert result.size_mb > 0
    assert result.memory_mb >= 0
    payload = result.to_dict()
    assert set(payload) == {"latency_ms_mean", "latency_ms_p95", "memory_mb", "size_mb"}
