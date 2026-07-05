"""Safety incidents: candidate events promoted to actionable form.

An incident is the unit a human reviews. It is born PENDING_REVIEW and can
only leave that state through an identified reviewer's decision — the
domain makes auto-confirmation unrepresentable (docs/04: every AI alert
requires human review; AI never decides what happened).

An incident aggregates its corroborating CandidateEvents (event
correlation): the full evidence chain — incident → candidates → tracks →
detections → frames — stays intact per ADR-0007.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum, unique
from uuid import UUID

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType


@unique
class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


@unique
class IncidentStatus(Enum):
    PENDING_REVIEW = "pending_review"
    """Awaiting a human decision. Every incident starts — and stays — here
    until a person acts."""

    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class IncidentReview:
    """The human decision that closed an incident."""

    reviewer: str
    decided_at: datetime
    note: str = ""

    def __post_init__(self) -> None:
        if not self.reviewer.strip():
            raise VisionConfigurationError(
                "a review without an identified reviewer is not a review"
            )


@dataclass(frozen=True, slots=True)
class SafetyIncident:
    """One reviewable safety situation on one track."""

    incident_id: UUID
    incident_type: CandidateEventType
    camera_id: str
    track_id: UUID
    track_display_id: int
    severity: Severity
    risk_confidence: float
    """Aggregated confidence across all corroborating events (noisy-or)."""

    opened_at: datetime
    last_event_at: datetime
    correlation_id: UUID
    """Trace token of the first triggering capture (ADR-0007)."""

    events: tuple[CandidateEvent, ...]
    summary: str
    status: IncidentStatus = IncidentStatus.PENDING_REVIEW
    review: IncidentReview | None = None

    def __post_init__(self) -> None:
        if not self.events:
            raise VisionConfigurationError("an incident without evidence cannot exist")
        if not (0.0 <= self.risk_confidence <= 1.0):
            raise VisionConfigurationError(f"risk confidence out of range: {self.risk_confidence}")
        for event in self.events:
            if event.event_type is not self.incident_type:
                raise VisionConfigurationError("all evidence must match the incident type")
            if event.camera_id != self.camera_id or event.track.track_id != self.track_id:
                raise VisionConfigurationError(
                    "all evidence must come from the incident's own camera and track"
                )
        if self.opened_at > self.last_event_at:
            raise VisionConfigurationError("opened_at cannot be after last_event_at")
        pending = self.status is IncidentStatus.PENDING_REVIEW
        if pending == (self.review is not None):
            raise VisionConfigurationError(
                "review must be present exactly when the incident is resolved"
            )

    def with_event(
        self, event: CandidateEvent, risk_confidence: float, severity: Severity
    ) -> SafetyIncident:
        """Attach corroborating evidence; only pending incidents grow."""
        if self.status is not IncidentStatus.PENDING_REVIEW:
            raise VisionConfigurationError("a resolved incident does not accept new evidence")
        return replace(
            self,
            events=(*self.events, event),
            last_event_at=event.observed_at,
            risk_confidence=risk_confidence,
            severity=severity,
        )

    def confirmed(self, reviewer: str, decided_at: datetime, note: str = "") -> SafetyIncident:
        return self._resolved(IncidentStatus.CONFIRMED, reviewer, decided_at, note)

    def dismissed(self, reviewer: str, decided_at: datetime, note: str = "") -> SafetyIncident:
        return self._resolved(IncidentStatus.DISMISSED, reviewer, decided_at, note)

    def _resolved(
        self, status: IncidentStatus, reviewer: str, decided_at: datetime, note: str
    ) -> SafetyIncident:
        if self.status is not IncidentStatus.PENDING_REVIEW:
            raise VisionConfigurationError(
                f"incident {self.incident_id} was already resolved ({self.status.value})"
            )
        return replace(
            self,
            status=status,
            review=IncidentReview(reviewer=reviewer, decided_at=decided_at, note=note),
        )
