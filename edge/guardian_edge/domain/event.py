"""Candidate safety events.

A CandidateEvent is what the AI *suspects*, never what it concludes: "this
track's motion looks like a potential fall, confidence 0.8, because of
these signals". Candidates feed the future risk engine; they are not
alerts, they trigger nothing by themselves, and they never accuse anyone
(docs/04: AI detects potential safety events; humans review and decide).

Every event is explainable by construction: it must carry the signals that
produced its confidence (docs/04: observed event, detection reason,
confidence, timestamp, evidence) and the full ADR-0007 identity chain via
its triggering frame and the track that evidences it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, unique
from uuid import UUID

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.track import Track


@unique
class CandidateEventType(Enum):
    POTENTIAL_FALL = "potential_fall"
    ZONE_EXIT = "zone_exit"
    """A child sustained outside a declared safe area (ADR-0018). Like every
    candidate: a suspicion about geometry, never a claim about supervision."""


@dataclass(frozen=True, slots=True)
class EventSignal:
    """One explainable contribution to an event's confidence."""

    name: str
    score: float
    """This signal's normalized contribution in [0, 1]."""

    detail: str
    """Human-readable measurement, e.g. '0.65 frame-heights/s downward'."""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise VisionConfigurationError("signal name must not be empty")
        if not (0.0 <= self.score <= 1.0):
            raise VisionConfigurationError(f"signal '{self.name}' score out of range: {self.score}")


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    """A potential safety event observed on one track."""

    event_id: UUID
    event_type: CandidateEventType
    camera_id: str
    observed_at: datetime
    frame_id: UUID
    """The frame whose evaluation produced this candidate."""

    correlation_id: UUID
    """Trace token of the triggering capture — propagated, never regenerated."""

    confidence: float
    track: Track
    """Snapshot of the track at emission; its last_detection carries the
    full detection-level identity (ADR-0007)."""

    signals: tuple[EventSignal, ...]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise VisionConfigurationError(f"event confidence out of range: {self.confidence}")
        if not self.signals:
            raise VisionConfigurationError(
                "an event without signals is an unexplainable event — refused (docs/04)"
            )
        if self.track.camera_id != self.camera_id:
            raise VisionConfigurationError(
                f"event on camera '{self.camera_id}' cannot be evidenced by a track "
                f"from camera '{self.track.camera_id}'"
            )
