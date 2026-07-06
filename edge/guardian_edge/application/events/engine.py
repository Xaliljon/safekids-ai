"""The event engine: tracking results in, candidate events out.

Attaches to the vision pipeline as a plain TrackConsumer (``engine(result)``)
— the pipeline is untouched, exactly as the tracker attaches to detections
(ADR-0006 §4, ADR-0012). Maintains per-track history, runs every registered
candidate detector over each confirmed track, and publishes candidates to
the event consumer. A failing detector or consumer is logged and counted,
never fatal.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from guardian_edge.application.debugging.explain import (
    TrackEvaluation,
    TrackEvaluationObserver,
)
from guardian_edge.application.events.history import TrackHistoryStore
from guardian_edge.application.events.ports import CandidateDetector, EventConsumer
from guardian_edge.domain.event import CandidateEvent
from guardian_edge.domain.track import TrackingResult, TrackState

logger = logging.getLogger(__name__)

_LATENCY_WINDOW = 240


@dataclass(frozen=True, slots=True)
class EventEngineStats:
    """Point-in-time statistics for the event engine."""

    frames_observed: int
    tracks_evaluated: int
    events_emitted: Mapping[str, int]
    detector_errors: int
    consumer_errors: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class EventEngine:
    """TrackConsumer that turns track histories into candidate events."""

    def __init__(
        self,
        detectors: Sequence[CandidateDetector],
        event_consumer: EventConsumer,
        history: TrackHistoryStore | None = None,
        clock: Callable[[], float] = time.perf_counter,
        evaluation_observer: TrackEvaluationObserver | None = None,
    ) -> None:
        self._detectors = tuple(detectors)
        self._event_consumer = event_consumer
        self._history = history or TrackHistoryStore()
        self._clock = clock
        self._evaluation_observer = evaluation_observer

        self._lock = threading.Lock()
        self._frames_observed = 0
        self._tracks_evaluated = 0
        self._events_emitted: dict[str, int] = {}
        self._detector_errors = 0
        self._consumer_errors = 0
        self._latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW)

    def __call__(self, result: TrackingResult) -> None:
        """TrackConsumer entry point: one tracking result per processed frame."""
        started = self._clock()
        self._history.observe(result)
        self._explain_unconfirmed(result)
        evaluated = 0
        for track in result.confirmed():
            evaluated += 1
            history = self._history.history(track.track_id)
            for detector in self._detectors:
                try:
                    event = detector.evaluate(history, track, result)
                except Exception:
                    with self._lock:
                        self._detector_errors += 1
                    logger.exception(
                        "camera %s: %s detector failed on track #%d; engine continues",
                        result.camera_id,
                        detector.event_type.value,
                        track.display_id,
                    )
                    continue
                if event is not None:
                    self._emit(event)
        with self._lock:
            self._frames_observed += 1
            self._tracks_evaluated += evaluated
            self._latencies.append((self._clock() - started) * 1000.0)

    def stats(self) -> EventEngineStats:
        with self._lock:
            ordered = sorted(self._latencies)
            return EventEngineStats(
                frames_observed=self._frames_observed,
                tracks_evaluated=self._tracks_evaluated,
                events_emitted=dict(sorted(self._events_emitted.items())),
                detector_errors=self._detector_errors,
                consumer_errors=self._consumer_errors,
                p50_latency_ms=_percentile(ordered, 0.50),
                p95_latency_ms=_percentile(ordered, 0.95),
            )

    def _explain_unconfirmed(self, result: TrackingResult) -> None:
        """Explanation only (Sprint 10.1): tracks the detectors never see
        still get an explicit reason — silent failures are forbidden. This
        changes no decision: unconfirmed tracks were always skipped."""
        observer = self._evaluation_observer
        if observer is None:
            return
        for track in result.tracks:
            if track.state is TrackState.CONFIRMED:
                continue
            reason = (
                f"track lost ({track.frames_since_update} frames without a detection)"
                if track.state is TrackState.LOST
                else f"track not confirmed (state: {track.state.value}, {track.hits} hit(s) so far)"
            )
            try:
                observer(
                    TrackEvaluation(
                        at=result.captured_at,
                        camera_id=result.camera_id,
                        frame_id=result.frame_id,
                        correlation_id=result.correlation_id,
                        track_id=track.track_id,
                        display_id=track.display_id,
                        state=track.state.value,
                        label=track.label,
                        outcome="rejected",
                        reason=reason,
                    )
                )
            except Exception:  # noqa: BLE001 - explanations must never break the engine
                logger.exception("evaluation observer failed; engine continues")

    def _emit(self, event: CandidateEvent) -> None:
        logger.warning(
            "camera %s: %s candidate on track #%d, confidence %.2f (%s)",
            event.camera_id,
            event.event_type.value,
            event.track.display_id,
            event.confidence,
            "; ".join(f"{signal.name}={signal.score:.2f}" for signal in event.signals),
        )
        with self._lock:
            key = event.event_type.value
            self._events_emitted[key] = self._events_emitted.get(key, 0) + 1
        try:
            self._event_consumer(event)
        except Exception:
            with self._lock:
                self._consumer_errors += 1
            logger.exception("event consumer raised; candidate %s dropped", event.event_id)


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index = min(int(fraction * len(sorted_values)), len(sorted_values) - 1)
    return round(sorted_values[index], 3)
