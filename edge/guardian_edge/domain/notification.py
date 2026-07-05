"""Notification domain: what leaves the risk layer toward humans.

A Notification is a metadata-only message about a SafetyIncident: ids,
severity, confidence, timestamps, and a text summary. By construction it
carries **no images, no video, and no personally identifiable
information** — the summary references tracks by display number only
(docs/03 privacy: only necessary metadata leaves the pipeline).

All objects are immutable; lifecycle transitions go through validating
methods, so an illegal transition is impossible to represent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, unique
from typing import Any
from uuid import UUID

from guardian_edge.domain.errors import (
    IllegalTransitionError,
    NotificationError,
    VisionConfigurationError,
)
from guardian_edge.domain.incident import IncidentStatus, SafetyIncident, Severity


@unique
class NotificationStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


_LEGAL_TRANSITIONS: dict[NotificationStatus, frozenset[NotificationStatus]] = {
    NotificationStatus.PENDING: frozenset({NotificationStatus.QUEUED}),
    NotificationStatus.QUEUED: frozenset({NotificationStatus.SENDING}),
    NotificationStatus.SENDING: frozenset(
        {NotificationStatus.DELIVERED, NotificationStatus.RETRYING, NotificationStatus.FAILED}
    ),
    NotificationStatus.RETRYING: frozenset({NotificationStatus.SENDING}),
    NotificationStatus.DELIVERED: frozenset(),
    NotificationStatus.FAILED: frozenset(),
}


@unique
class NotificationPriority(Enum):
    IMMEDIATE = "immediate"
    """Jumps the queue; critical/high severities."""

    STANDARD = "standard"


@unique
class NotificationAction(Enum):
    """What a policy decides for an incident severity."""

    NOTIFY_IMMEDIATE = "notify_immediate"
    NOTIFY = "notify"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One try at delivering through a channel."""

    number: int
    channel: str
    started_at: datetime
    finished_at: datetime
    succeeded: bool
    error: str = ""

    def __post_init__(self) -> None:
        if self.number < 1:
            raise NotificationError("attempt numbers start at 1")
        if self.finished_at < self.started_at:
            raise NotificationError("an attempt cannot finish before it starts")
        if self.succeeded and self.error:
            raise NotificationError("a successful attempt carries no error")


def _default_actions() -> dict[Severity, NotificationAction]:
    return {
        Severity.CRITICAL: NotificationAction.NOTIFY_IMMEDIATE,
        Severity.HIGH: NotificationAction.NOTIFY_IMMEDIATE,
        Severity.MEDIUM: NotificationAction.NOTIFY,
        Severity.LOW: NotificationAction.IGNORE,
    }


@dataclass(frozen=True, slots=True)
class NotificationPolicy:
    """Which incidents become notifications, and how urgently.

    Defaults: CRITICAL/HIGH immediate, MEDIUM standard, LOW ignored.
    Escalations re-notify by default (a situation that got worse is news);
    resolutions do not (the reviewer already knows — they resolved it).
    """

    severity_actions: dict[Severity, NotificationAction] = field(default_factory=_default_actions)
    notify_on_escalation: bool = True
    notify_on_resolution: bool = False

    def __post_init__(self) -> None:
        missing = [s.value for s in Severity if s not in self.severity_actions]
        if missing:
            raise VisionConfigurationError(f"policy must cover every severity; missing {missing}")

    def action_for(self, severity: Severity) -> NotificationAction:
        return self.severity_actions[severity]


@dataclass(frozen=True, slots=True)
class Notification:
    """A metadata-only message about one SafetyIncident."""

    notification_id: UUID
    incident_id: UUID
    camera_id: str
    track_id: UUID
    track_display_id: int
    correlation_id: UUID
    severity: Severity
    risk_confidence: float
    incident_status: IncidentStatus
    summary: str
    event_count: int
    occurred_at: datetime
    """When the underlying evidence was last observed."""

    created_at: datetime
    priority: NotificationPriority
    channel: str
    status: NotificationStatus = NotificationStatus.PENDING
    attempts: tuple[DeliveryAttempt, ...] = ()

    @classmethod
    def for_incident(
        cls,
        incident: SafetyIncident,
        priority: NotificationPriority,
        channel: str,
        notification_id: UUID,
        created_at: datetime,
    ) -> Notification:
        return cls(
            notification_id=notification_id,
            incident_id=incident.incident_id,
            camera_id=incident.camera_id,
            track_id=incident.track_id,
            track_display_id=incident.track_display_id,
            correlation_id=incident.correlation_id,
            severity=incident.severity,
            risk_confidence=incident.risk_confidence,
            incident_status=incident.status,
            summary=incident.summary,
            event_count=len(incident.events),
            occurred_at=incident.last_event_at,
            created_at=created_at,
            priority=priority,
            channel=channel,
        )

    # ----------------------------------------------------------- lifecycle

    def queued(self) -> Notification:
        return self._transition(NotificationStatus.QUEUED)

    def sending(self) -> Notification:
        return self._transition(NotificationStatus.SENDING)

    def delivered(self, attempt: DeliveryAttempt) -> Notification:
        if not attempt.succeeded:
            raise NotificationError("DELIVERED requires a successful attempt")
        return self._transition(NotificationStatus.DELIVERED, attempt)

    def retrying(self, attempt: DeliveryAttempt) -> Notification:
        if attempt.succeeded:
            raise NotificationError("RETRYING requires a failed attempt")
        return self._transition(NotificationStatus.RETRYING, attempt)

    def failed(self, attempt: DeliveryAttempt) -> Notification:
        if attempt.succeeded:
            raise NotificationError("FAILED requires a failed attempt")
        return self._transition(NotificationStatus.FAILED, attempt)

    def _transition(
        self, to_status: NotificationStatus, attempt: DeliveryAttempt | None = None
    ) -> Notification:
        if to_status not in _LEGAL_TRANSITIONS[self.status]:
            raise IllegalTransitionError(
                f"notification {self.notification_id}: {self.status.value} -> "
                f"{to_status.value} is not a legal transition"
            )
        attempts = self.attempts if attempt is None else (*self.attempts, attempt)
        if attempt is not None and attempt.number != len(self.attempts) + 1:
            raise NotificationError(
                f"attempt {attempt.number} out of order (expected {len(self.attempts) + 1})"
            )
        return replace(self, status=to_status, attempts=attempts)

    # ------------------------------------------------------------- payload

    def to_payload(self) -> dict[str, Any]:
        """The wire payload. Metadata only — never images, video, or PII."""
        return {
            "notification_id": str(self.notification_id),
            "incident_id": str(self.incident_id),
            "camera_id": self.camera_id,
            "track_id": str(self.track_id),
            "track_display_id": self.track_display_id,
            "correlation_id": str(self.correlation_id),
            "type": "safety_incident",
            "severity": self.severity.value,
            "confidence": self.risk_confidence,
            "incident_status": self.incident_status.value,
            "timestamp": self.occurred_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "summary": self.summary,
            "event_count": self.event_count,
            "priority": self.priority.value,
        }
