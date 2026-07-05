"""The notification engine: SafetyIncidents in, delivered Notifications out.

Attaches to the risk engine as a plain IncidentConsumer — the sixth layer
composed through a callable seam; nothing upstream knows notifications
exist. One worker thread drains a priority-aware queue, drives every
notification through its validated lifecycle
(PENDING → QUEUED → SENDING → DELIVERED / RETRYING → … / FAILED), applies
the exponential retry ladder, and records backend-independent metrics.

No AI logic, no risk logic: the policy reads severity and status, nothing
else.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from guardian_edge.application.notifications.ports import (
    NotificationChannel,
    NotificationListener,
)
from guardian_edge.application.notifications.retry import RetryStrategy
from guardian_edge.domain.incident import IncidentStatus, SafetyIncident
from guardian_edge.domain.notification import (
    DeliveryAttempt,
    Notification,
    NotificationAction,
    NotificationPolicy,
    NotificationPriority,
)

logger = logging.getLogger(__name__)

_IDLE_WAIT_SECONDS = 0.2
_LATENCY_WINDOW = 240


@dataclass(frozen=True, slots=True)
class NotificationMetrics:
    """Backend-independent delivery metrics snapshot."""

    queue_size: int
    """Ready + scheduled-for-retry notifications not yet terminal."""

    created: int
    ignored_by_policy: int
    duplicates_suppressed: int
    delivered: int
    failed_permanently: int
    retry_count: int
    delivery_success_attempts: int
    delivery_failure_attempts: int
    last_delivery_latency_ms: float | None
    """Duration of the last successful channel send."""

    mean_delivery_latency_ms: float | None
    mean_time_to_delivered_ms: float | None
    """Average from creation to DELIVERED, including queueing and retries."""


@dataclass(frozen=True, slots=True)
class _TrackedIncidentState:
    severity_rank: int
    status: IncidentStatus


class NotificationEngine:
    """IncidentConsumer delivering notifications through one channel."""

    def __init__(
        self,
        channel: NotificationChannel,
        policy: NotificationPolicy | None = None,
        retry: RetryStrategy | None = None,
        listener: NotificationListener | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        self._channel = channel
        self._policy = policy or NotificationPolicy()
        self._retry = retry or RetryStrategy()
        self._listener = listener
        self._clock = clock
        self._wall_clock = wall_clock

        self._condition = threading.Condition()
        self._ready: deque[Notification] = deque()
        self._scheduled: list[tuple[float, int, Notification]] = []
        self._schedule_sequence = itertools.count()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._notified: dict[UUID, _TrackedIncidentState] = {}
        self._created_at_mono: dict[UUID, float] = {}
        self._counters: dict[str, int] = {}
        self._send_latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self._latency_sum = 0.0
        self._time_to_delivered_sum = 0.0
        self._last_latency: float | None = None

    # ------------------------------------------------------ incident intake

    def __call__(self, incident: SafetyIncident) -> None:
        """IncidentConsumer entry point."""
        decision = self._decide(incident)
        if decision is None:
            return
        priority = decision
        notification = Notification.for_incident(
            incident,
            priority=priority,
            channel=self._channel.name,
            notification_id=uuid4(),
            created_at=self._wall_clock(),
        ).queued()
        with self._condition:
            self._counters["created"] = self._counters.get("created", 0) + 1
            self._created_at_mono[notification.notification_id] = self._clock()
            if priority is NotificationPriority.IMMEDIATE:
                self._ready.appendleft(notification)
            else:
                self._ready.append(notification)
            self._condition.notify()
        self._observe(notification)

    def _decide(self, incident: SafetyIncident) -> NotificationPriority | None:
        """Policy + dedup: returns a priority, or None for no notification."""
        with self._condition:
            last = self._notified.get(incident.incident_id)
            self._notified[incident.incident_id] = _TrackedIncidentState(
                severity_rank=incident.severity.rank, status=incident.status
            )
            if incident.status is not IncidentStatus.PENDING_REVIEW:
                if not self._policy.notify_on_resolution or last is None:
                    self._count_locked("duplicates_suppressed")
                    return None
            elif last is not None:
                escalated = incident.severity.rank > last.severity_rank
                if not (escalated and self._policy.notify_on_escalation):
                    self._count_locked("duplicates_suppressed")
                    return None
        action = self._policy.action_for(incident.severity)
        if action is NotificationAction.IGNORE:
            self._count("ignored_by_policy")
            return None
        if action is NotificationAction.NOTIFY_IMMEDIATE:
            return NotificationPriority.IMMEDIATE
        return NotificationPriority.STANDARD

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the delivery worker. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="notification-engine", daemon=True)
        self._thread.start()

    def stop(self, join_timeout_seconds: float = 10.0) -> None:
        """Stop the worker. Idempotent; queued items remain for restart."""
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout_seconds)
        self._thread = None

    # -------------------------------------------------------------- metrics

    def metrics(self) -> NotificationMetrics:
        with self._condition:
            get = self._counters.get
            delivered = get("delivered", 0)
            success_attempts = get("delivery_success_attempts", 0)
            return NotificationMetrics(
                queue_size=len(self._ready) + len(self._scheduled),
                created=get("created", 0),
                ignored_by_policy=get("ignored_by_policy", 0),
                duplicates_suppressed=get("duplicates_suppressed", 0),
                delivered=delivered,
                failed_permanently=get("failed_permanently", 0),
                retry_count=get("retry_count", 0),
                delivery_success_attempts=success_attempts,
                delivery_failure_attempts=get("delivery_failure_attempts", 0),
                last_delivery_latency_ms=self._last_latency,
                mean_delivery_latency_ms=(
                    round(self._latency_sum / success_attempts, 3) if success_attempts else None
                ),
                mean_time_to_delivered_ms=(
                    round(self._time_to_delivered_sum / delivered, 3) if delivered else None
                ),
            )

    # ------------------------------------------------------------ internals

    def _run(self) -> None:
        while not self._stop_event.is_set():
            notification = self._next_ready()
            if notification is not None:
                self._deliver(notification)

    def _next_ready(self) -> Notification | None:
        with self._condition:
            while not self._stop_event.is_set():
                now = self._clock()
                while self._scheduled and self._scheduled[0][0] <= now:
                    _, _, due = heapq.heappop(self._scheduled)
                    self._ready.append(due)
                if self._ready:
                    return self._ready.popleft()
                timeout = _IDLE_WAIT_SECONDS
                if self._scheduled:
                    timeout = min(timeout, max(self._scheduled[0][0] - now, 0.0))
                self._condition.wait(timeout=timeout)
            return None

    def _deliver(self, notification: Notification) -> None:
        notification = notification.sending()
        self._observe(notification)
        started_wall = self._wall_clock()
        started = self._clock()
        try:
            self._channel.send(notification)
        except Exception as exc:
            self._on_send_failure(notification, started_wall, str(exc))
            return
        latency_ms = (self._clock() - started) * 1000.0
        attempt = DeliveryAttempt(
            number=len(notification.attempts) + 1,
            channel=self._channel.name,
            started_at=started_wall,
            finished_at=self._wall_clock(),
            succeeded=True,
        )
        delivered = notification.delivered(attempt)
        with self._condition:
            self._count_locked("delivered")
            self._count_locked("delivery_success_attempts")
            self._last_latency = round(latency_ms, 3)
            self._latency_sum += latency_ms
            created_mono = self._created_at_mono.pop(delivered.notification_id, None)
            if created_mono is not None:
                self._time_to_delivered_sum += (self._clock() - created_mono) * 1000.0
        logger.info(
            "notification %s delivered via %s (%s, attempt %d, %.1f ms)",
            delivered.notification_id,
            self._channel.name,
            delivered.severity.value,
            attempt.number,
            latency_ms,
        )
        self._observe(delivered)

    def _on_send_failure(
        self, notification: Notification, started_wall: datetime, error: str
    ) -> None:
        attempt = DeliveryAttempt(
            number=len(notification.attempts) + 1,
            channel=self._channel.name,
            started_at=started_wall,
            finished_at=self._wall_clock(),
            succeeded=False,
            error=error[:300],
        )
        self._count("delivery_failure_attempts")
        delay = self._retry.delay_after_failure(attempt.number)
        if delay is None:
            failed = notification.failed(attempt)
            with self._condition:
                self._count_locked("failed_permanently")
                self._created_at_mono.pop(failed.notification_id, None)
            logger.error(
                "notification %s permanently failed after %d attempts via %s: %s",
                failed.notification_id,
                attempt.number,
                self._channel.name,
                error,
            )
            self._observe(failed)
            return
        retrying = notification.retrying(attempt)
        with self._condition:
            self._count_locked("retry_count")
            heapq.heappush(
                self._scheduled,
                (self._clock() + delay, next(self._schedule_sequence), retrying),
            )
            self._condition.notify()
        logger.warning(
            "notification %s attempt %d failed via %s (%s); retrying in %.1fs",
            retrying.notification_id,
            attempt.number,
            self._channel.name,
            error,
            delay,
        )
        self._observe(retrying)

    def _observe(self, notification: Notification) -> None:
        if self._listener is None:
            return
        try:
            self._listener(notification)
        except Exception:
            logger.exception("notification listener raised; observation dropped")

    def _count(self, name: str) -> None:
        with self._condition:
            self._count_locked(name)

    def _count_locked(self, name: str) -> None:
        self._counters[name] = self._counters.get(name, 0) + 1
