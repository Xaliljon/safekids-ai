"""Engine latency and error metrics.

Backend-independent: every engine implementation records into an
EngineMetricsRecorder so operators see the same metric surface regardless of
runtime (docs/03: real-time performance is mandatory — measure it).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

DEFAULT_LATENCY_WINDOW = 240
"""Recent inferences kept for percentile computation (~10s at 24 FPS)."""


@dataclass(frozen=True, slots=True)
class EngineMetrics:
    """Point-in-time inference statistics for one engine instance."""

    inferences_total: int
    errors_total: int
    warmup_runs: int
    last_latency_ms: float | None
    mean_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class EngineMetricsRecorder:
    """Thread-safe accumulator behind ``InferenceEngine.metrics()``.

    Percentiles are computed over a bounded window of recent latencies so a
    long-running engine reflects current behavior, not its lifetime average.
    """

    def __init__(self, window: int = DEFAULT_LATENCY_WINDOW) -> None:
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window)
        self._inferences_total = 0
        self._errors_total = 0
        self._warmup_runs = 0
        self._last_latency_ms: float | None = None
        self._latency_sum_ms = 0.0

    def record_inference(self, latency_ms: float) -> None:
        with self._lock:
            self._inferences_total += 1
            self._latency_sum_ms += latency_ms
            self._last_latency_ms = latency_ms
            self._latencies.append(latency_ms)

    def record_error(self) -> None:
        with self._lock:
            self._errors_total += 1

    def record_warmup(self) -> None:
        with self._lock:
            self._warmup_runs += 1

    def snapshot(self) -> EngineMetrics:
        with self._lock:
            window = sorted(self._latencies)
            total = self._inferences_total
            mean = self._latency_sum_ms / total if total else None
            return EngineMetrics(
                inferences_total=total,
                errors_total=self._errors_total,
                warmup_runs=self._warmup_runs,
                last_latency_ms=self._last_latency_ms,
                mean_latency_ms=round(mean, 3) if mean is not None else None,
                p50_latency_ms=_percentile(window, 0.50),
                p95_latency_ms=_percentile(window, 0.95),
            )


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index = min(int(fraction * len(sorted_values)), len(sorted_values) - 1)
    return round(sorted_values[index], 3)
