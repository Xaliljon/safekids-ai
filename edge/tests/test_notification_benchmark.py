"""Notification engine throughput/latency benchmark (pure CPU)."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

import pytest
from camera_fakes import wait_until
from event_fixtures import make_safety_incident

from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.domain.incident import Severity
from guardian_edge.domain.notification import Notification

logger = logging.getLogger(__name__)

NOTIFICATIONS = 500
DELIVERY_TIME_BUDGET_MS = 250.0
"""Mean creation->delivered must stay far inside the 1s charter budget."""


class InstantChannel:
    name = "instant"

    def __init__(self) -> None:
        self.count = 0

    def send(self, notification: Notification) -> None:
        self.count += 1


@pytest.mark.benchmark
def test_notification_engine_throughput_benchmark() -> None:
    channel = InstantChannel()
    engine = NotificationEngine(channel)
    engine.start()
    try:
        started = time.perf_counter()
        for _ in range(NOTIFICATIONS):
            engine(
                make_safety_incident(
                    severity=Severity.CRITICAL, confidence=0.9, incident_id=uuid4()
                )
            )
        assert wait_until(lambda: channel.count == NOTIFICATIONS, timeout=10.0)
        elapsed = time.perf_counter() - started
    finally:
        engine.stop()
    metrics = engine.metrics()
    logger.info(
        "notification benchmark: %d delivered in %.2fs (%.0f/s), "
        "mean send %.3fms, mean create->delivered %.1fms",
        NOTIFICATIONS,
        elapsed,
        NOTIFICATIONS / elapsed,
        metrics.mean_delivery_latency_ms or 0.0,
        metrics.mean_time_to_delivered_ms or 0.0,
    )
    assert metrics.delivered == NOTIFICATIONS
    assert metrics.queue_size == 0
    assert metrics.mean_time_to_delivered_ms is not None
    assert metrics.mean_time_to_delivered_ms < DELIVERY_TIME_BUDGET_MS


def test_notification_smoke_pass_without_benchmark_marker() -> None:
    """Keeps the throughput path exercised in ordinary CI runs."""
    channel = InstantChannel()
    engine = NotificationEngine(channel)
    engine.start()
    try:
        for _ in range(20):
            engine(
                make_safety_incident(
                    severity=Severity.CRITICAL, confidence=0.9, incident_id=uuid4()
                )
            )
        assert wait_until(lambda: channel.count == 20)
    finally:
        engine.stop()
