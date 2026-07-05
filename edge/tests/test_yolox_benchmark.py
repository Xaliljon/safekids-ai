"""Real-model integration and performance benchmarks for YOLOX.

These tests need the actual model installed (``make model-yolox``); they
skip cleanly when it is absent (e.g. in hosted CI). Latency bounds are
deliberately generous — they catch order-of-magnitude regressions, not
machine-to-machine variance. Hard budget enforcement happens on the bench
Jetson (nightly hardware job), not on developer laptops.
"""

from __future__ import annotations

import logging
import os
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.vision.overlay import OpenCvOverlayRenderer
from guardian_edge.infrastructure.vision.yolox import YOLOX_MODEL_NAME, create_yolox_detector

logger = logging.getLogger(__name__)

MODELS_DIR = Path(os.environ.get("GUARDIAN_MODELS_DIR", "models"))
WARMUP_FRAMES = 5
TIMED_FRAMES = 50
GENEROUS_LATENCY_BUDGET_MS = 500.0  # the charter's whole-alert budget

requires_model = pytest.mark.skipif(
    not (MODELS_DIR / YOLOX_MODEL_NAME).is_dir(),
    reason=f"YOLOX model not installed under '{MODELS_DIR}' (run: make model-yolox)",
)


def image_frame(sequence: int, width: int = 640, height: int = 480) -> Frame:
    rng = np.random.default_rng(seed=sequence)
    return Frame(
        camera_id="bench-cam",
        sequence=sequence,
        captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
        width=width,
        height=height,
        data=rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8),
    )


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    return peak / (1 << 20) if sys.platform == "darwin" else peak / (1 << 10)


@requires_model
def test_real_model_loads_through_registry_and_detects() -> None:
    detector = create_yolox_detector(FileSystemModelRegistry(MODELS_DIR))
    try:
        assert detector.descriptor.name == YOLOX_MODEL_NAME
        assert detector.config.labels[0] == "person"
        frame = image_frame(1)
        result = detector.detect(frame)
        assert result.model.name == YOLOX_MODEL_NAME
        assert result.inference_ms > 0.0
        assert result.frame_id == frame.frame_id  # ADR-0007 identity intact
        for detection in result.detections:  # noise may yield boxes; all must be valid
            assert 0.0 <= detection.confidence <= 1.0
            assert detection.label in detector.config.labels
    finally:
        detector.close()


@requires_model
def test_overlay_renders_real_results() -> None:
    detector = create_yolox_detector(FileSystemModelRegistry(MODELS_DIR))
    try:
        frame = image_frame(2)
        result = detector.detect(frame)
        rendered = OpenCvOverlayRenderer().render(frame, result, fps=25.0)
        assert rendered.shape == frame.data.shape
        assert not np.array_equal(rendered, frame.data)
    finally:
        detector.close()


@pytest.mark.benchmark
@requires_model
def test_yolox_latency_fps_and_memory_benchmark() -> None:
    rss_before_mb = peak_rss_mb()
    detector = create_yolox_detector(FileSystemModelRegistry(MODELS_DIR))
    try:
        for sequence in range(WARMUP_FRAMES):
            detector.detect(image_frame(sequence))

        import time

        started = time.perf_counter()
        for sequence in range(TIMED_FRAMES):
            detector.detect(image_frame(100 + sequence))
        elapsed = time.perf_counter() - started

        fps = TIMED_FRAMES / elapsed
        metrics = detector._engine.metrics()  # noqa: SLF001 - benchmark introspection
        rss_after_mb = peak_rss_mb()

        logger.info(
            "YOLOX benchmark: fps=%.1f, engine p50=%.1fms p95=%.1fms mean=%.1fms, "
            "peak RSS %.0f MB (delta %.0f MB), %d inferences",
            fps,
            metrics.p50_latency_ms or 0.0,
            metrics.p95_latency_ms or 0.0,
            metrics.mean_latency_ms or 0.0,
            rss_after_mb,
            rss_after_mb - rss_before_mb,
            metrics.inferences_total,
        )

        assert metrics.inferences_total == WARMUP_FRAMES + TIMED_FRAMES
        assert metrics.p95_latency_ms is not None
        assert metrics.p95_latency_ms < GENEROUS_LATENCY_BUDGET_MS, (
            f"p95 {metrics.p95_latency_ms:.1f}ms blows the whole-alert budget "
            f"({GENEROUS_LATENCY_BUDGET_MS}ms) on inference alone"
        )
        assert fps > 2.0, f"end-to-end {fps:.2f} FPS is below any usable floor"
        assert rss_after_mb - rss_before_mb < 2048, "model load leaked >2GB RSS"
    finally:
        detector.close()
