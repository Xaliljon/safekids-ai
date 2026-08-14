"""Decision explanations: what the engines concluded, and exactly why.

These are pure data carriers emitted through OPTIONAL observer hooks on
the fall detector, event engine and risk engine. When no observer is
attached the engines behave byte-for-byte as before — explainability is
composition, not behavioral change (Sprint 10.1 constraint).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import hypot
from typing import Any, Protocol
from uuid import UUID

from guardian_edge.application.events.history import TrackObservation


class SignalScores(Protocol):
    """The weighted signals behind one detector's decision.

    Each detector carries its own shape — a fall's velocity and aspect-ratio
    scores mean nothing to a zone exit, and a single flat record would leave
    most fields empty whichever detector wrote it. The recorder only needs
    to serialize them.
    """

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MotionAnalysis:
    """Motion numbers behind a decision (frame-relative units per second)."""

    vertical_velocity: float | None = None
    horizontal_velocity: float | None = None
    peak_downward_velocity: float | None = None
    movement_delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertical_velocity": self.vertical_velocity,
            "horizontal_velocity": self.horizontal_velocity,
            "peak_downward_velocity": self.peak_downward_velocity,
            "movement_delta": self.movement_delta,
        }


@dataclass(frozen=True, slots=True)
class SignalBreakdown:
    """The weighted fall signals; None when an earlier gate cut evaluation."""

    velocity_score: float | None = None
    aspect_ratio_score: float | None = None
    ground_score: float | None = None
    stillness_score: float | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "velocity_score": self.velocity_score,
            "aspect_ratio_score": self.aspect_ratio_score,
            "ground_score": self.ground_score,
            "stillness_score": self.stillness_score,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class TrackEvaluation:
    """One decision about one track on one frame — always with a reason."""

    at: datetime
    camera_id: str
    frame_id: UUID
    correlation_id: UUID
    track_id: UUID
    display_id: int
    state: str
    label: str
    outcome: str  # "candidate" | "rejected"
    reason: str  # exact, human-readable; never empty
    motion: MotionAnalysis = field(default_factory=MotionAnalysis)
    signals: SignalScores = field(default_factory=SignalBreakdown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "camera_id": self.camera_id,
            "frame_id": str(self.frame_id),
            "correlation_id": str(self.correlation_id),
            "track_id": str(self.track_id),
            "display_id": self.display_id,
            "state": self.state,
            "label": self.label,
            "outcome": self.outcome,
            "reason": self.reason,
            "motion": self.motion.to_dict(),
            "signals": self.signals.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """One risk-engine decision about one candidate — always with a reason."""

    at: datetime
    camera_id: str
    track_id: UUID
    display_id: int
    event_type: str
    candidate_confidence: float
    outcome: str  # "incident_opened" | "corroborated" | "escalated" | "rejected"
    reason: str
    risk_confidence: float | None = None
    severity: str | None = None
    incident_id: UUID | None = None
    corroborating_events: int | None = None
    seconds_remaining: float | None = None  # for suppression/corroboration windows

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "camera_id": self.camera_id,
            "track_id": str(self.track_id),
            "display_id": self.display_id,
            "event_type": self.event_type,
            "candidate_confidence": self.candidate_confidence,
            "outcome": self.outcome,
            "reason": self.reason,
            "risk_confidence": self.risk_confidence,
            "severity": self.severity,
            "incident_id": str(self.incident_id) if self.incident_id else None,
            "corroborating_events": self.corroborating_events,
            "seconds_remaining": self.seconds_remaining,
        }


TrackEvaluationObserver = Callable[[TrackEvaluation], None]
RiskDecisionObserver = Callable[[RiskDecision], None]


def motion_analysis(
    history: Sequence[TrackObservation],
    peak_downward: float | None = None,
    window_seconds: float = 1.5,
) -> MotionAnalysis:
    """Motion numbers computed from history — for explanation ONLY.

    This never feeds a decision; the detector's own feature functions do.
    """
    if len(history) < 2:
        return MotionAnalysis(peak_downward_velocity=peak_downward)
    cutoff = history[-1].captured_at.timestamp() - window_seconds
    window = [obs for obs in history if obs.captured_at.timestamp() >= cutoff]
    if len(window) < 2:
        window = list(history[-2:])
    first, last = window[0], window[-1]
    dt = (last.captured_at - first.captured_at).total_seconds()
    if dt <= 0:
        return MotionAnalysis(peak_downward_velocity=peak_downward)
    return MotionAnalysis(
        vertical_velocity=round((last.center_y - first.center_y) / dt, 4),
        horizontal_velocity=round((last.center_x - first.center_x) / dt, 4),
        peak_downward_velocity=peak_downward if peak_downward is None else round(peak_downward, 4),
        movement_delta=round(
            hypot(last.center_x - first.center_x, last.center_y - first.center_y), 4
        ),
    )
