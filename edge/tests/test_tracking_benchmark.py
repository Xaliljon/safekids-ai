"""Tracking latency benchmarks.

The synthetic benchmark runs everywhere (pure CPU, no model). The
end-to-end benchmark (real YOLOX + ByteTrack) needs the installed model
and skips cleanly without it.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.infrastructure.tracking.bytetrack import ByteTracker

logger = logging.getLogger(__name__)

MODELS_DIR = Path(os.environ.get("GUARDIAN_MODELS_DIR", "models"))
OBJECTS = 12  # a busy classroom
FRAMES = 300
TRACKING_BUDGET_MS = 5.0  # tracking must be noise next to ~15ms inference


def synthetic_result(sequence: int, frame_id: object = None) -> DetectionResult:
    correlation = uuid4()
    fid = uuid4()
    captured = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    detections = []
    for index in range(OBJECTS):
        x = (0.05 + index * 0.07 + sequence * 0.003) % 0.8
        y = 0.1 + (index % 4) * 0.2
        detections.append(
            Detection(
                detection_id=uuid4(),
                frame_id=fid,  # type: ignore[arg-type]
                camera_id="bench-cam",
                captured_at=captured,
                correlation_id=correlation,
                label="person",
                confidence=0.9 if index % 5 else 0.3,  # some occluded (BYTE path)
                box=BoundingBox(x=x, y=y, width=0.08, height=0.15),
            )
        )
    return DetectionResult(
        camera_id="bench-cam",
        frame_id=fid,  # type: ignore[arg-type]
        frame_sequence=sequence,
        captured_at=captured,
        correlation_id=correlation,
        detections=tuple(detections),
        model=ModelDescriptor(name="bench", version="1.0.0"),
        inference_ms=0.0,
    )


@pytest.mark.benchmark
def test_bytetrack_latency_benchmark() -> None:
    tracker = ByteTracker()
    latencies: list[float] = []
    for sequence in range(FRAMES):
        result = synthetic_result(sequence)
        started = time.perf_counter()
        tracking = tracker.update(result)
        latencies.append((time.perf_counter() - started) * 1000.0)
        assert tracking.camera_id == "bench-cam"
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    logger.info(
        "ByteTrack benchmark: %d objects x %d frames — p50=%.3fms p95=%.3fms max=%.3fms",
        OBJECTS,
        FRAMES,
        p50,
        p95,
        latencies[-1],
    )
    assert p95 < TRACKING_BUDGET_MS, (
        f"tracking p95 {p95:.2f}ms exceeds {TRACKING_BUDGET_MS}ms — it must be "
        f"negligible next to inference"
    )


@pytest.mark.benchmark
@pytest.mark.skipif(
    not (MODELS_DIR / "yolox-tiny").is_dir(),
    reason=f"YOLOX model not installed under '{MODELS_DIR}' (run: make model-yolox)",
)
def test_detection_plus_tracking_end_to_end_benchmark() -> None:
    import numpy as np

    from guardian_edge.domain.frame import Frame
    from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
    from guardian_edge.infrastructure.vision.yolox import create_yolox_detector

    detector = create_yolox_detector(FileSystemModelRegistry(MODELS_DIR))
    tracker = ByteTracker()
    rng = np.random.default_rng(seed=7)
    try:
        tracking_ms: list[float] = []
        total_started = time.perf_counter()
        for sequence in range(50):
            frame = Frame(
                camera_id="bench-cam",
                sequence=sequence,
                captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
                width=640,
                height=480,
                data=rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8),
            )
            result = detector.detect(frame)
            tracking = tracker.update(result)
            tracking_ms.append(tracking.tracking_ms)
        elapsed = time.perf_counter() - total_started
        logger.info(
            "detect+track end-to-end: %.1f FPS, tracking mean %.3fms of pipeline",
            50 / elapsed,
            sum(tracking_ms) / len(tracking_ms),
        )
        assert max(tracking_ms) < TRACKING_BUDGET_MS
    finally:
        detector.close()
