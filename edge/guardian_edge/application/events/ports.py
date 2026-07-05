"""Ports (interfaces) of the event engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from guardian_edge.application.events.history import TrackObservation
from guardian_edge.domain.event import CandidateEvent, CandidateEventType
from guardian_edge.domain.track import Track, TrackingResult


class EventConsumer(Protocol):
    """Receives every candidate event (the future risk engine attaches here).

    A consumer that raises loses that event only; the engine never stops.
    """

    def __call__(self, event: CandidateEvent) -> None: ...


class CandidateDetector(Protocol):
    """Evaluates one track's history for one kind of potential event.

    Detectors are pure evaluators: they return a candidate (or None) and
    never publish, alert, or mutate shared state beyond their own cooldown
    bookkeeping.
    """

    @property
    def event_type(self) -> CandidateEventType: ...

    def evaluate(
        self,
        history: Sequence[TrackObservation],
        track: Track,
        result: TrackingResult,
    ) -> CandidateEvent | None:
        """Return a candidate when this track's recent history warrants one."""
        ...
