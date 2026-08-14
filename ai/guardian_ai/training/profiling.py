"""Inference profiling: where the latency actually goes (Sprint 20.2).

The promotion gate compares one number — mean ONNX latency — and
``compare.benchmark_onnx`` produces it with 30 runs and 5 warmups on the
CPU provider. That is enough to rank two models roughly; it is not enough
to *optimize* against. Three consecutive repeats of the same measurement
on the same machine spread 45.4 / 52.3 / 62.1 ms, and no honest 20%
improvement is visible inside a ±37% band.

So this module does three things the gate's benchmark does not:

* **Separates cold start from steady state.** The first inference pays for
  weight paging and lazy kernel selection; folding it into the mean hides
  the number a running box actually experiences (Sprint 20.2 §9).
* **Reports spread, not just central tendency.** A latency claim without
  its stdev and sample count cannot be reproduced or argued with.
* **Breaks the pipeline into components.** The gate's number is model
  inference *only* — no capture, preprocess, NMS or tracking. Optimizing
  preprocessing cannot move it, and knowing that before starting saves a
  sprint (§3).

Nothing here changes detection semantics. It measures.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_WARMUP = 20
"""Discarded before timing. Deliberately larger than the gate's 5: on this
class of machine the first ~10 calls are still settling."""

DEFAULT_RUNS = 200
"""Timed steady-state calls. Large enough that the mean stops moving
between repeats — the property the gate's 30 runs did not have."""


@dataclass(frozen=True)
class LatencyStats:
    """One timing distribution. Never report a mean without its company."""

    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    stdev_ms: float
    runs: int

    @classmethod
    def of(cls, timings_ms: Sequence[float]) -> LatencyStats:
        ordered = sorted(timings_ms)
        return cls(
            mean_ms=float(statistics.fmean(ordered)),
            p50_ms=float(np.percentile(ordered, 50)),
            p95_ms=float(np.percentile(ordered, 95)),
            min_ms=ordered[0],
            max_ms=ordered[-1],
            stdev_ms=float(statistics.stdev(ordered)) if len(ordered) > 1 else 0.0,
            runs=len(ordered),
        )

    @property
    def relative_spread(self) -> float:
        """stdev / mean — how much a single sample can be trusted."""
        return self.stdev_ms / self.mean_ms if self.mean_ms else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_ms": round(self.mean_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "stdev_ms": round(self.stdev_ms, 3),
            "relative_spread": round(self.relative_spread, 4),
            "runs": self.runs,
        }


@dataclass(frozen=True)
class RuntimeConfig:
    """An ONNX Runtime session configuration under test.

    Every field is something the sprint is allowed to change: none of them
    touch the model, the thresholds, or the detection semantics.
    """

    provider: str = "CPUExecutionProvider"
    graph_optimization_level: str = "ORT_ENABLE_ALL"
    intra_op_threads: int | None = None
    inter_op_threads: int | None = None

    @property
    def label(self) -> str:
        threads = (
            f"intra={self.intra_op_threads or 'default'},inter={self.inter_op_threads or 'default'}"
        )
        provider = self.provider.replace("ExecutionProvider", "")
        return f"{provider} {self.graph_optimization_level.removeprefix('ORT_')} {threads}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "graph_optimization_level": self.graph_optimization_level,
            "intra_op_threads": self.intra_op_threads,
            "inter_op_threads": self.inter_op_threads,
        }


def host_provenance() -> dict[str, Any]:
    """Everything needed to know whether a latency number is comparable.

    A benchmark without this is a number without a claim (§2). ``is_edge``
    is explicit so a development measurement can never be quietly read as
    an Edge one (§11).
    """
    import onnxruntime as ort

    machine = platform.machine()
    return {
        "platform": platform.platform(),
        "machine": machine,
        "processor": _cpu_brand(),
        "logical_cpus": _logical_cpus(),
        "python": sys.version.split()[0],
        "onnxruntime": ort.__version__,
        "available_providers": ort.get_available_providers(),
        "is_edge_target": False,
        "measurement_class": "development",
    }


def _cpu_brand() -> str:
    # platform.system(), not sys.platform: mypy narrows the latter to the
    # checking host and then calls the portable branch unreachable.
    if platform.system() == "Darwin":
        import subprocess

        try:
            return subprocess.run(
                ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return platform.processor()
    return platform.processor()


def _logical_cpus() -> int:
    import os

    return os.cpu_count() or 0


def make_session(model_path: Path, config: RuntimeConfig) -> Any:
    """Build a session for one configuration. Raises if unavailable."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.graph_optimization_level = getattr(
        ort.GraphOptimizationLevel, config.graph_optimization_level
    )
    if config.intra_op_threads is not None:
        options.intra_op_num_threads = config.intra_op_threads
    if config.inter_op_threads is not None:
        options.inter_op_num_threads = config.inter_op_threads
    return ort.InferenceSession(str(model_path), options, providers=[config.provider])


@dataclass(frozen=True)
class InferenceProfile:
    """Cold start and steady state, kept apart on purpose (§9)."""

    config: RuntimeConfig
    first_call_ms: float
    first_ten: LatencyStats
    steady_state: LatencyStats
    peak_rss_mb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "first_call_ms": round(self.first_call_ms, 3),
            "first_ten": self.first_ten.to_dict(),
            "steady_state": self.steady_state.to_dict(),
            "peak_rss_mb": round(self.peak_rss_mb, 2),
        }


def profile_inference(
    model_path: Path,
    config: RuntimeConfig,
    input_shape: tuple[int, ...],
    input_name: str = "images",
    warmup: int = DEFAULT_WARMUP,
    runs: int = DEFAULT_RUNS,
    seed: int = 0,
) -> InferenceProfile:
    """Time one model under one runtime configuration.

    The same fixed-seed synthetic tensor the gate uses, so this stays
    comparable to ``compare.benchmark_onnx`` — the point is a better
    method on the same subject, not a different subject.
    """
    generator = np.random.default_rng(seed)
    example = generator.standard_normal(input_shape).astype(np.float32)
    session = make_session(model_path, config)
    feed = {input_name: example}

    first = _time_call(session, feed)
    first_ten = [first] + [_time_call(session, feed) for _ in range(9)]
    for _ in range(max(0, warmup - 10)):
        session.run(None, feed)
    steady = [_time_call(session, feed) for _ in range(runs)]

    return InferenceProfile(
        config=config,
        first_call_ms=first,
        first_ten=LatencyStats.of(first_ten),
        steady_state=LatencyStats.of(steady),
        peak_rss_mb=_peak_rss_mb(),
    )


def _time_call(session: Any, feed: dict[str, Any]) -> float:
    start = time.perf_counter()
    session.run(None, feed)
    return (time.perf_counter() - start) * 1000.0


def _peak_rss_mb() -> float:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


@dataclass
class StageTimer:
    """Accumulates per-stage timings across frames (§3).

    A stage that is never timed reports nothing rather than zero — a zero
    would read as "free", and the whole point of the breakdown is to stop
    guessing which stage is expensive.
    """

    stages: dict[str, list[float]] = field(default_factory=dict)

    def record(self, stage: str, elapsed_ms: float) -> None:
        self.stages.setdefault(stage, []).append(elapsed_ms)

    def measure(self, stage: str, call: Callable[[], Any]) -> Any:
        start = time.perf_counter()
        result = call()
        self.record(stage, (time.perf_counter() - start) * 1000.0)
        return result

    def breakdown(self) -> dict[str, LatencyStats]:
        return {name: LatencyStats.of(times) for name, times in self.stages.items() if times}

    def to_dict(self) -> dict[str, Any]:
        stats = self.breakdown()
        total_mean = sum(s.mean_ms for s in stats.values())
        return {
            "stages": {
                name: {
                    **stat.to_dict(),
                    "share_of_total": round(stat.mean_ms / total_mean, 4) if total_mean else 0.0,
                }
                for name, stat in stats.items()
            },
            "total_mean_ms": round(total_mean, 3),
        }
