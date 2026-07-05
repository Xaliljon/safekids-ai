"""Notification engine: policy routing, dedup, delivery, retry, failures."""

import threading
from dataclasses import replace
from uuid import uuid4

import pytest
from camera_fakes import wait_until
from event_fixtures import make_safety_incident, timestamp

from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.notifications.retry import RetryStrategy
from guardian_edge.domain.errors import ChannelDeliveryError, VisionConfigurationError
from guardian_edge.domain.incident import Severity
from guardian_edge.domain.notification import (
    Notification,
    NotificationPolicy,
    NotificationStatus,
)

FAST_RETRY = RetryStrategy((0.01, 0.02, 0.03, 0.04, 0.05))


class RecordingChannel:
    name = "recording"

    def __init__(self, fail_first: int = 0) -> None:
        self._fail_remaining = fail_first
        self._lock = threading.Lock()
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        with self._lock:
            if self._fail_remaining > 0:
                self._fail_remaining -= 1
                raise ChannelDeliveryError("simulated channel outage")
            self.sent.append(notification)


def make_engine(
    channel: RecordingChannel | None = None,
    policy: NotificationPolicy | None = None,
) -> tuple[NotificationEngine, RecordingChannel, list[Notification]]:
    channel = channel or RecordingChannel()
    observed: list[Notification] = []
    engine = NotificationEngine(
        channel=channel, policy=policy, retry=FAST_RETRY, listener=observed.append
    )
    return engine, channel, observed


class TestPolicyRouting:
    def test_critical_and_high_notify_low_is_ignored(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            engine(make_safety_incident(severity=Severity.HIGH, confidence=0.8))
            engine(make_safety_incident(severity=Severity.LOW, confidence=0.3))
            assert wait_until(lambda: len(channel.sent) == 2)
            metrics = engine.metrics()
            assert metrics.created == 2
            assert metrics.ignored_by_policy == 1
        finally:
            engine.stop()

    def test_immediate_priority_jumps_the_queue(self) -> None:
        engine, channel, _ = make_engine()
        engine(make_safety_incident(severity=Severity.MEDIUM, confidence=0.65))
        engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
        engine.start()  # worker starts only after both are queued
        try:
            assert wait_until(lambda: len(channel.sent) == 2)
            assert channel.sent[0].severity is Severity.CRITICAL, "immediate goes first"
        finally:
            engine.stop()


class TestDeduplication:
    def test_same_incident_snapshot_notifies_once(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        try:
            incident = make_safety_incident(severity=Severity.MEDIUM)
            engine(incident)
            engine(incident)  # correlated snapshot, same severity
            assert wait_until(lambda: len(channel.sent) == 1)
            assert engine.metrics().duplicates_suppressed == 1
        finally:
            engine.stop()

    def test_escalation_notifies_again(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        try:
            incident = make_safety_incident(severity=Severity.MEDIUM)
            engine(incident)
            escalated = replace(incident, severity=Severity.CRITICAL, risk_confidence=0.91)
            engine(escalated)
            assert wait_until(lambda: len(channel.sent) == 2)
            # Order is not guaranteed: the escalation is IMMEDIATE and may
            # legitimately jump ahead of the still-queued MEDIUM.
            assert {n.severity for n in channel.sent} == {Severity.MEDIUM, Severity.CRITICAL}
        finally:
            engine.stop()

    def test_resolution_is_silent_by_default(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        try:
            incident = make_safety_incident(severity=Severity.CRITICAL, confidence=0.9)
            engine(incident)
            engine(incident.confirmed("director-anna", timestamp(50)))
            assert wait_until(lambda: len(channel.sent) == 1)
            assert engine.metrics().duplicates_suppressed == 1
        finally:
            engine.stop()

    def test_resolution_notifies_when_configured(self) -> None:
        engine, channel, _ = make_engine(policy=NotificationPolicy(notify_on_resolution=True))
        engine.start()
        try:
            incident = make_safety_incident(severity=Severity.CRITICAL, confidence=0.9)
            engine(incident)
            engine(incident.dismissed("director-anna", timestamp(50)))
            assert wait_until(lambda: len(channel.sent) == 2)
        finally:
            engine.stop()


class TestLifecycleAndRetry:
    def test_full_lifecycle_is_observable(self) -> None:
        engine, _, observed = make_engine()
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            assert wait_until(
                lambda: any(n.status is NotificationStatus.DELIVERED for n in observed)
            )
        finally:
            engine.stop()
        statuses = [n.status for n in observed]
        assert statuses == [
            NotificationStatus.QUEUED,
            NotificationStatus.SENDING,
            NotificationStatus.DELIVERED,
        ]

    def test_retry_until_success(self) -> None:
        channel = RecordingChannel(fail_first=2)
        engine, _, observed = make_engine(channel)
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            assert wait_until(lambda: len(channel.sent) == 1)
            metrics = engine.metrics()
            assert metrics.retry_count == 2
            assert metrics.delivered == 1
            assert metrics.delivery_failure_attempts == 2
        finally:
            engine.stop()
        delivered = [n for n in observed if n.status is NotificationStatus.DELIVERED][0]
        assert [a.succeeded for a in delivered.attempts] == [False, False, True]

    def test_permanent_failure_after_the_ladder(self) -> None:
        channel = RecordingChannel(fail_first=99)
        engine, _, observed = make_engine(channel)
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            assert wait_until(
                lambda: any(n.status is NotificationStatus.FAILED for n in observed), timeout=5.0
            )
        finally:
            engine.stop()
        failed = [n for n in observed if n.status is NotificationStatus.FAILED][0]
        assert len(failed.attempts) == FAST_RETRY.max_attempts
        metrics = engine.metrics()
        assert metrics.failed_permanently == 1
        assert metrics.delivered == 0
        assert metrics.retry_count == FAST_RETRY.max_attempts - 1
        assert metrics.queue_size == 0, "failed notifications leave the queue"

    def test_metrics_track_latency(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            assert wait_until(lambda: len(channel.sent) == 1)
            assert wait_until(lambda: engine.metrics().mean_delivery_latency_ms is not None)
            metrics = engine.metrics()
            assert metrics.last_delivery_latency_ms is not None
            assert metrics.mean_time_to_delivered_ms is not None
            assert metrics.mean_time_to_delivered_ms >= 0.0
        finally:
            engine.stop()


class TestRobustness:
    def test_listener_failure_never_breaks_delivery(self) -> None:
        channel = RecordingChannel()

        def broken_listener(notification: Notification) -> None:
            raise ValueError("listener bug")

        engine = NotificationEngine(channel=channel, retry=FAST_RETRY, listener=broken_listener)
        engine.start()
        try:
            engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
            assert wait_until(lambda: len(channel.sent) == 1)
        finally:
            engine.stop()

    def test_start_and_stop_are_idempotent(self) -> None:
        engine, channel, _ = make_engine()
        engine.start()
        engine.start()
        engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
        assert wait_until(lambda: len(channel.sent) == 1)
        engine.stop()
        engine.stop()

    def test_queue_survives_stop_for_restart(self) -> None:
        engine, channel, _ = make_engine()
        engine(make_safety_incident(severity=Severity.CRITICAL, confidence=0.9))
        assert engine.metrics().queue_size == 1, "nothing is lost while the worker is down"
        engine.start()
        try:
            assert wait_until(lambda: len(channel.sent) == 1)
            assert engine.metrics().queue_size == 0
        finally:
            engine.stop()


def test_invalid_retry_ladders_are_rejected() -> None:
    with pytest.raises(VisionConfigurationError):
        RetryStrategy(())
    with pytest.raises(VisionConfigurationError):
        RetryStrategy((1.0, 0.5))
    with pytest.raises(VisionConfigurationError):
        RetryStrategy((0.0,))


def test_retry_ladder_matches_the_spec() -> None:
    strategy = RetryStrategy()
    delays = [strategy.delay_after_failure(n) for n in range(1, 7)]
    assert delays == [1.0, 2.0, 5.0, 10.0, 30.0, None]
    assert strategy.max_attempts == 6


def test_unknown_incident_ids_do_not_collide() -> None:
    """Distinct incidents never dedupe against each other."""
    engine, channel, _ = make_engine()
    engine.start()
    try:
        engine(
            make_safety_incident(severity=Severity.CRITICAL, confidence=0.9, incident_id=uuid4())
        )
        engine(
            make_safety_incident(severity=Severity.CRITICAL, confidence=0.9, incident_id=uuid4())
        )
        assert wait_until(lambda: len(channel.sent) == 2)
    finally:
        engine.stop()
