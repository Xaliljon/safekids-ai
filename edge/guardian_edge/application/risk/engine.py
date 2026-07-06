"""The risk engine: candidate events in, reviewable safety incidents out.

Attaches to the event engine as a plain EventConsumer — the fourth layer
in a row to compose through a callable seam (detections → tracks →
candidates → incidents), each one untouched by the next.

Responsibilities: apply risk policies (suppression gates), correlate
candidates on the same track into one incident, aggregate risk confidence
(noisy-or), rate severity, and hand PENDING_REVIEW incidents to the
incident consumer. Resolution happens only through confirm()/dismiss()
with an identified reviewer — this engine cannot close its own incidents.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from guardian_edge.application.debugging.explain import RiskDecision, RiskDecisionObserver
from guardian_edge.application.risk.policy import RiskPolicy, RiskPolicySet
from guardian_edge.domain.errors import UnknownIncidentError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType
from guardian_edge.domain.incident import SafetyIncident

logger = logging.getLogger(__name__)

_MAX_RISK = 0.999

_CorrelationKey = tuple[str, UUID, CandidateEventType]


class IncidentConsumer(Protocol):
    """Receives every incident snapshot: opened, corroborated, resolved.

    Snapshots share incident_id across updates. The notification engine
    attaches here; a consumer that raises loses that snapshot only.
    """

    def __call__(self, incident: SafetyIncident) -> None: ...


@dataclass(frozen=True, slots=True)
class RiskEngineStats:
    candidates_received: int
    ignored_no_policy: int
    suppressed_low_confidence: int
    suppressed_after_dismissal: int
    incidents_opened: int
    events_correlated: int
    escalations: int
    confirmed: int
    dismissed: int
    consumer_errors: int
    open_incidents: int
    opened_by_severity: Mapping[str, int]


class RiskEngine:
    """EventConsumer turning candidates into human-reviewable incidents."""

    def __init__(
        self,
        incident_consumer: IncidentConsumer,
        policies: RiskPolicySet | None = None,
        observer: RiskDecisionObserver | None = None,
    ) -> None:
        self._consumer = incident_consumer
        self._policies = policies or RiskPolicySet()
        self._observer = observer

        self._lock = threading.Lock()
        self._open: dict[_CorrelationKey, SafetyIncident] = {}
        self._corroboration: dict[_CorrelationKey, list[CandidateEvent]] = {}
        self._suppressed_until: dict[_CorrelationKey, datetime] = {}
        self._counters: dict[str, int] = {}
        self._opened_by_severity: dict[str, int] = {}

    # -------------------------------------------------------- event intake

    def __call__(self, event: CandidateEvent) -> None:
        """EventConsumer entry point."""
        self._count("candidates_received")
        policy = self._policies.for_event(event.event_type)
        if policy is None:
            self._count("ignored_no_policy")
            self._explain(
                event,
                "rejected",
                f"no risk policy registered for event type "
                f"'{event.event_type.value}' — candidate ignored",
            )
            return
        key: _CorrelationKey = (event.camera_id, event.track.track_id, event.event_type)
        emit: SafetyIncident | None = None
        explain_after: RiskDecision | None = None
        rejection: tuple[str, float | None] | None = None
        with self._lock:
            suppressed_until = self._suppressed_until.get(key)
            if suppressed_until is not None and event.observed_at < suppressed_until:
                self._count_locked("suppressed_after_dismissal")
                remaining = (suppressed_until - event.observed_at).total_seconds()
                rejection = (
                    f"suppressed after human dismissal ({remaining:.1f}s of suppression remaining)",
                    round(remaining, 1),
                )
            elif event.confidence < policy.min_event_confidence:
                self._count_locked("suppressed_low_confidence")
                rejection = (
                    f"candidate confidence below policy minimum "
                    f"({event.confidence:.2f} < {policy.min_event_confidence:.2f})",
                    None,
                )
            elif (open_incident := self._open.get(key)) is not None:
                emit = self._correlate(key, open_incident, event, policy)
                if emit is not None:
                    escalated = emit.severity.rank > open_incident.severity.rank
                    explain_after = RiskDecision(
                        at=event.observed_at,
                        camera_id=event.camera_id,
                        track_id=event.track.track_id,
                        display_id=event.track.display_id,
                        event_type=event.event_type.value,
                        candidate_confidence=event.confidence,
                        outcome="escalated" if escalated else "corroborated",
                        reason=(
                            f"candidate corroborates open incident "
                            f"{emit.incident_id} (risk {emit.risk_confidence:.2f}, "
                            f"severity {emit.severity.value}"
                            + (", escalated" if escalated else "")
                            + ")"
                        ),
                        risk_confidence=emit.risk_confidence,
                        severity=emit.severity.value,
                        incident_id=emit.incident_id,
                        corroborating_events=len(emit.events),
                    )
            else:
                emit = self._maybe_open(key, event, policy)
                if emit is not None:
                    explain_after = RiskDecision(
                        at=event.observed_at,
                        camera_id=event.camera_id,
                        track_id=event.track.track_id,
                        display_id=event.track.display_id,
                        event_type=event.event_type.value,
                        candidate_confidence=event.confidence,
                        outcome="incident_opened",
                        reason=(
                            f"candidate accepted: risk confidence "
                            f"{emit.risk_confidence:.2f} -> severity "
                            f"{emit.severity.value} -> incident created"
                        ),
                        risk_confidence=emit.risk_confidence,
                        severity=emit.severity.value,
                        incident_id=emit.incident_id,
                        corroborating_events=len(emit.events),
                    )
                else:
                    pending = len(self._corroboration.get(key, []))
                    rejection = (
                        f"awaiting corroboration ({pending}/"
                        f"{policy.min_events_to_open} candidate(s) within the "
                        f"{policy.aggregation_window_seconds:.0f}s window; "
                        f"confidence {event.confidence:.2f} is below the "
                        f"{policy.fast_path_confidence:.2f} fast path)",
                        policy.aggregation_window_seconds,
                    )
        # Explanations are emitted OUTSIDE the lock: observers may do
        # arbitrary work, and explanation must never risk a deadlock.
        if rejection is not None:
            self._explain(event, "rejected", rejection[0], seconds_remaining=rejection[1])
            return
        if explain_after is not None:
            self._emit_explanation(explain_after)
        if emit is not None:
            self._emit(emit)

    # ------------------------------------------------------- human review

    def confirm(
        self,
        incident_id: UUID,
        reviewer: str,
        note: str = "",
        decided_at: datetime | None = None,
    ) -> SafetyIncident:
        """Record a human confirmation; returns the resolved incident."""
        return self._resolve(incident_id, reviewer, note, decided_at, confirm=True)

    def dismiss(
        self,
        incident_id: UUID,
        reviewer: str,
        note: str = "",
        decided_at: datetime | None = None,
    ) -> SafetyIncident:
        """Record a human dismissal and suppress that track for a while —
        a dismissed false positive must not ring again seconds later."""
        return self._resolve(incident_id, reviewer, note, decided_at, confirm=False)

    def open_incidents(self) -> tuple[SafetyIncident, ...]:
        with self._lock:
            return tuple(self._open.values())

    def stats(self) -> RiskEngineStats:
        with self._lock:
            get = self._counters.get
            return RiskEngineStats(
                candidates_received=get("candidates_received", 0),
                ignored_no_policy=get("ignored_no_policy", 0),
                suppressed_low_confidence=get("suppressed_low_confidence", 0),
                suppressed_after_dismissal=get("suppressed_after_dismissal", 0),
                incidents_opened=get("incidents_opened", 0),
                events_correlated=get("events_correlated", 0),
                escalations=get("escalations", 0),
                confirmed=get("confirmed", 0),
                dismissed=get("dismissed", 0),
                consumer_errors=get("consumer_errors", 0),
                open_incidents=len(self._open),
                opened_by_severity=dict(sorted(self._opened_by_severity.items())),
            )

    # ---------------------------------------------------------- internals

    def _correlate(
        self,
        key: _CorrelationKey,
        incident: SafetyIncident,
        event: CandidateEvent,
        policy: RiskPolicy,
    ) -> SafetyIncident:
        """Attach evidence to the still-unresolved incident on this track."""
        risk = _noisy_or([e.confidence for e in incident.events] + [event.confidence])
        severity = policy.severity_for(risk)
        escalated = severity.rank > incident.severity.rank
        updated = incident.with_event(event, risk, severity)
        updated = _with_summary(updated)
        self._open[key] = updated
        self._count_locked("events_correlated")
        if escalated:
            self._count_locked("escalations")
            logger.warning(
                "incident %s escalated to %s (risk %.2f, %d events)",
                updated.incident_id,
                severity.value,
                risk,
                len(updated.events),
            )
        return updated

    def _maybe_open(
        self, key: _CorrelationKey, event: CandidateEvent, policy: RiskPolicy
    ) -> SafetyIncident | None:
        window = timedelta(seconds=policy.aggregation_window_seconds)
        recent = [
            candidate
            for candidate in self._corroboration.get(key, [])
            if event.observed_at - candidate.observed_at <= window
        ]
        recent.append(event)
        if (
            event.confidence < policy.fast_path_confidence
            and len(recent) < policy.min_events_to_open
        ):
            self._corroboration[key] = recent
            return None
        self._corroboration.pop(key, None)
        risk = _noisy_or([candidate.confidence for candidate in recent])
        severity = policy.severity_for(risk)
        incident = _with_summary(
            SafetyIncident(
                incident_id=uuid4(),
                incident_type=event.event_type,
                camera_id=event.camera_id,
                track_id=event.track.track_id,
                track_display_id=event.track.display_id,
                severity=severity,
                risk_confidence=risk,
                opened_at=recent[0].observed_at,
                last_event_at=event.observed_at,
                correlation_id=recent[0].correlation_id,
                events=tuple(recent),
                summary="",
            )
        )
        self._open[key] = incident
        self._count_locked("incidents_opened")
        severity_key = severity.value
        self._opened_by_severity[severity_key] = self._opened_by_severity.get(severity_key, 0) + 1
        logger.warning(
            "incident %s opened: %s %s on track #%d (risk %.2f) — pending human review",
            incident.incident_id,
            severity.value,
            incident.incident_type.value,
            incident.track_display_id,
            risk,
        )
        return incident

    def _resolve(
        self,
        incident_id: UUID,
        reviewer: str,
        note: str,
        decided_at: datetime | None,
        confirm: bool,
    ) -> SafetyIncident:
        decided = decided_at or datetime.now(tz=timezone.utc)
        with self._lock:
            key = next(
                (k for k, incident in self._open.items() if incident.incident_id == incident_id),
                None,
            )
            if key is None:
                raise UnknownIncidentError(f"incident {incident_id} is not open")
            incident = self._open.pop(key)
            if confirm:
                resolved = incident.confirmed(reviewer, decided, note)
                self._count_locked("confirmed")
            else:
                resolved = incident.dismissed(reviewer, decided, note)
                self._count_locked("dismissed")
                policy = self._policies.for_event(incident.incident_type)
                if policy is not None and policy.dismissal_suppression_seconds > 0:
                    self._suppressed_until[key] = decided + timedelta(
                        seconds=policy.dismissal_suppression_seconds
                    )
        logger.info(
            "incident %s %s by %s",
            incident_id,
            resolved.status.value,
            reviewer,
        )
        self._emit(resolved)
        return resolved

    def _emit(self, incident: SafetyIncident) -> None:
        try:
            self._consumer(incident)
        except Exception:
            self._count("consumer_errors")
            logger.exception("incident consumer raised; snapshot %s dropped", incident.incident_id)

    def _explain(
        self,
        event: CandidateEvent,
        outcome: str,
        reason: str,
        seconds_remaining: float | None = None,
    ) -> None:
        """Explanation only (Sprint 10.1): never influences the decision."""
        if self._observer is None:
            return
        self._emit_explanation(
            RiskDecision(
                at=event.observed_at,
                camera_id=event.camera_id,
                track_id=event.track.track_id,
                display_id=event.track.display_id,
                event_type=event.event_type.value,
                candidate_confidence=event.confidence,
                outcome=outcome,
                reason=reason,
                seconds_remaining=seconds_remaining,
            )
        )

    def _emit_explanation(self, decision: RiskDecision) -> None:
        observer = self._observer
        if observer is None:
            return
        try:
            observer(decision)
        except Exception:  # noqa: BLE001 - explanations must never break risk handling
            logger.exception("risk decision observer failed; engine continues")

    def _count(self, name: str) -> None:
        with self._lock:
            self._count_locked(name)

    def _count_locked(self, name: str) -> None:
        self._counters[name] = self._counters.get(name, 0) + 1


def _noisy_or(confidences: list[float]) -> float:
    survival = 1.0
    for confidence in confidences:
        survival *= 1.0 - confidence
    return round(min(1.0 - survival, _MAX_RISK), 3)


def _with_summary(incident: SafetyIncident) -> SafetyIncident:
    peak = max(event.confidence for event in incident.events)
    summary = (
        f"{len(incident.events)} corroborating {incident.incident_type.value} candidate(s) "
        f"on track #{incident.track_display_id}; peak candidate confidence {peak:.2f}; "
        f"awaiting human review"
    )
    return replace(incident, summary=summary)
