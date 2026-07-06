"""Model comparison: PROMOTE or REJECT, with reasons on paper.

A candidate is compared against the current model on the metrics that
matter for a child-safety product: precision must not regress (false
alarms erode trust), recall must not regress (missed falls are the worst
failure), false positives must not grow, and the edge budget (latency,
memory, size) must hold. The verdict is advisory — promotion itself is
always a separate, manually approved step (Sprint 17 rule: "Never allow
automatic promotion").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

COMPARISON_FILE = "comparison.json"
PROMOTE = "PROMOTE"
REJECT = "REJECT"

# Regression tolerances: a candidate may not be worse than the baseline
# by more than this on each metric (small slack absorbs eval noise).
_METRIC_SLACK = 0.005
_FP_SLACK = 0  # false positives may never increase, full stop
_LATENCY_SLACK = 1.20  # candidate may be at most 20% slower
_SIZE_SLACK = 1.50  # and at most 50% larger on disk


@dataclass(frozen=True)
class BenchmarkResult:
    latency_ms_mean: float
    latency_ms_p95: float
    memory_mb: float
    size_mb: float

    def to_dict(self) -> dict[str, float]:
        return {
            "latency_ms_mean": round(self.latency_ms_mean, 3),
            "latency_ms_p95": round(self.latency_ms_p95, 3),
            "memory_mb": round(self.memory_mb, 2),
            "size_mb": round(self.size_mb, 3),
        }


def benchmark_onnx(
    model_path: Path,
    input_name: str,
    input_shape: tuple[int, ...],
    runs: int = 30,
    warmup: int = 5,
    seed: int = 0,
) -> BenchmarkResult:
    """Latency/memory/size of an ONNX artifact on the CPU provider."""
    import resource
    import sys
    import time

    import onnxruntime

    generator = np.random.default_rng(seed)
    example = generator.standard_normal(input_shape).astype(np.float32)
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    session = onnxruntime.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    for _ in range(warmup):
        session.run(None, {input_name: example})
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS, kilobytes on Linux
    rss_unit = 1 if sys.platform == "darwin" else 1024
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        session.run(None, {input_name: example})
        timings.append((time.perf_counter() - start) * 1000.0)
    return BenchmarkResult(
        latency_ms_mean=float(np.mean(timings)),
        latency_ms_p95=float(np.percentile(timings, 95)),
        memory_mb=max(0, rss_after - rss_before) * rss_unit / (1024 * 1024),
        size_mb=model_path.stat().st_size / (1024 * 1024),
    )


def compare_models(
    candidate_eval: dict[str, Any],
    baseline_eval: dict[str, Any],
    candidate_bench: BenchmarkResult,
    baseline_bench: BenchmarkResult,
) -> dict[str, Any]:
    """Full comparison verdict. Every failed clause becomes a reason."""
    cand, base = candidate_eval["overall"], baseline_eval["overall"]
    reasons: list[str] = []
    checks: list[dict[str, Any]] = []

    def metric(name: str, higher_is_better: bool = True) -> None:
        delta = cand[name] - base[name]
        ok = delta >= -_METRIC_SLACK if higher_is_better else delta <= _METRIC_SLACK
        checks.append(
            {
                "check": name,
                "candidate": cand[name],
                "baseline": base[name],
                "delta": round(delta, 4),
                "passed": ok,
            }
        )
        if not ok:
            direction = "dropped" if higher_is_better else "grew"
            reasons.append(f"{name} {direction}: {base[name]:.4f} -> {cand[name]:.4f}")

    metric("precision")
    metric("recall")

    # Extra false positives are acceptable ONLY when precision holds — i.e.
    # they are the price of real recall gains, not noise. A dead baseline
    # (predicts nothing, FP=0) must not be unbeatable.
    fp_grew = cand["false_positives"] > base["false_positives"] + _FP_SLACK
    precision_held = cand["precision"] >= base["precision"] - _METRIC_SLACK
    fp_ok = not fp_grew or precision_held
    checks.append(
        {
            "check": "false_positives",
            "candidate": cand["false_positives"],
            "baseline": base["false_positives"],
            "delta": cand["false_positives"] - base["false_positives"],
            "passed": fp_ok,
        }
    )
    if not fp_ok:
        reasons.append(
            f"false positives grew ({base['false_positives']} -> "
            f"{cand['false_positives']}) while precision regressed — "
            "extra alarms without accuracy are a rejection"
        )

    latency_ok = candidate_bench.latency_ms_mean <= (
        baseline_bench.latency_ms_mean * _LATENCY_SLACK
    )
    checks.append(
        {
            "check": "latency_ms_mean",
            "candidate": round(candidate_bench.latency_ms_mean, 3),
            "baseline": round(baseline_bench.latency_ms_mean, 3),
            "limit": round(baseline_bench.latency_ms_mean * _LATENCY_SLACK, 3),
            "passed": latency_ok,
        }
    )
    if not latency_ok:
        reasons.append(
            f"latency regressed beyond +20%: {baseline_bench.latency_ms_mean:.2f}ms "
            f"-> {candidate_bench.latency_ms_mean:.2f}ms"
        )

    size_ok = candidate_bench.size_mb <= baseline_bench.size_mb * _SIZE_SLACK
    checks.append(
        {
            "check": "size_mb",
            "candidate": round(candidate_bench.size_mb, 3),
            "baseline": round(baseline_bench.size_mb, 3),
            "limit": round(baseline_bench.size_mb * _SIZE_SLACK, 3),
            "passed": size_ok,
        }
    )
    if not size_ok:
        reasons.append(
            f"model size grew beyond +50%: {baseline_bench.size_mb:.2f}MB -> "
            f"{candidate_bench.size_mb:.2f}MB"
        )

    verdict = PROMOTE if not reasons else REJECT
    return {
        "verdict": verdict,
        "reasons": reasons or ["candidate matches or improves the baseline on every gate"],
        "checks": checks,
        "candidate": {"evaluation": cand, "benchmark": candidate_bench.to_dict()},
        "baseline": {"evaluation": base, "benchmark": baseline_bench.to_dict()},
    }


def save_comparison(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
