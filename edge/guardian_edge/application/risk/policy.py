"""Risk policies: the rule engine's declarative rules.

A policy states, per event type, what it takes for suspicions to become an
incident and how severe the aggregate is. Every number is a reviewable
product decision, tunable per deployment without touching code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEventType
from guardian_edge.domain.incident import Severity


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """Rules converting one event type's candidates into incidents."""

    event_type: CandidateEventType

    min_event_confidence: float = 0.6
    """Candidates below this are suppressed outright (false-positive gate).
    Default aligns with the event engine's emission threshold — the layers
    agree by default and diverge only by deliberate per-deployment tuning."""

    fast_path_confidence: float = 0.85
    """A single candidate at/above this opens an incident immediately."""

    min_events_to_open: int = 1
    """Corroborating candidates required within the window otherwise."""

    aggregation_window_seconds: float = 30.0
    """Candidates on the same track within this window corroborate each other."""

    dismissal_suppression_seconds: float = 60.0
    """After a human dismisses, the same track+type stays quiet this long —
    a dismissed false positive must not ring again seconds later."""

    medium_at: float = 0.6
    high_at: float = 0.75
    critical_at: float = 0.85
    """Risk-confidence cutoffs mapping to severity (below medium_at = LOW)."""

    def __post_init__(self) -> None:
        for name, value in (
            ("min_event_confidence", self.min_event_confidence),
            ("fast_path_confidence", self.fast_path_confidence),
        ):
            if not (0.0 <= value <= 1.0):
                raise VisionConfigurationError(f"{name} out of range: {value}")
        if self.min_event_confidence > self.fast_path_confidence:
            raise VisionConfigurationError(
                "min_event_confidence cannot exceed fast_path_confidence"
            )
        if self.min_events_to_open < 1:
            raise VisionConfigurationError("min_events_to_open must be >= 1")
        if self.aggregation_window_seconds <= 0 or self.dismissal_suppression_seconds < 0:
            raise VisionConfigurationError("windows must be positive")
        if not (0.0 <= self.medium_at <= self.high_at <= self.critical_at <= 1.0):
            raise VisionConfigurationError(
                "severity cutoffs must satisfy 0 <= medium <= high <= critical <= 1"
            )

    def severity_for(self, risk_confidence: float) -> Severity:
        if risk_confidence >= self.critical_at:
            return Severity.CRITICAL
        if risk_confidence >= self.high_at:
            return Severity.HIGH
        if risk_confidence >= self.medium_at:
            return Severity.MEDIUM
        return Severity.LOW


def default_policies() -> Mapping[CandidateEventType, RiskPolicy]:
    """SafeKids V1 defaults. Falls open on a single qualifying candidate:
    when a child might be hurt, the safe failure mode is a pending incident
    a human glances at, not a suppressed signal.

    Zone exits are a slower kind of news — the detector already required a
    sustained absence from the safe area (ADR-0018 §10), so nothing is
    urgent by the time a candidate exists. They therefore open at the same
    single-candidate threshold but carry a longer dismissal suppression: a
    director who has just decided "that one is fine, a teacher is with her"
    should not be asked again a minute later about the same child in the
    same place."""
    return {
        CandidateEventType.POTENTIAL_FALL: RiskPolicy(event_type=CandidateEventType.POTENTIAL_FALL),
        CandidateEventType.ZONE_EXIT: RiskPolicy(
            event_type=CandidateEventType.ZONE_EXIT,
            dismissal_suppression_seconds=300.0,
            # A child out of the area is a supervision question, not an
            # injury: severity rises with confidence more slowly than a fall.
            medium_at=0.6,
            high_at=0.85,
            critical_at=0.95,
        ),
    }


@dataclass(frozen=True, slots=True)
class RiskPolicySet:
    """The rule engine's rule book: one policy per event type."""

    policies: Mapping[CandidateEventType, RiskPolicy] = field(default_factory=default_policies)

    def __post_init__(self) -> None:
        for event_type, policy in self.policies.items():
            if policy.event_type is not event_type:
                raise VisionConfigurationError(
                    f"policy for {event_type.value} declares {policy.event_type.value}"
                )

    def for_event(self, event_type: CandidateEventType) -> RiskPolicy | None:
        return self.policies.get(event_type)
