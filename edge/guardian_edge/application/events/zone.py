"""Zone-exit candidate detection (ADR-0018).

A child outside a declared safe area, for long enough and far enough that
it is not a wobble at the boundary. Geometry and a calendar — no model, no
inference about intent, and above all no conclusion: like every candidate,
this is a suspicion a human reviews (docs/04).

Two rules carry most of the safety weight here:

* **Absence is never evidence.** Only CONFIRMED observations exist for this
  detector (ADR-0012 §4). A track that vanished — occluded, lost, walked
  out of frame — produces nothing. The child who leaves through a doorway
  is caught by *where the polygon was drawn*, which is why the boundary
  must sit inside the frame with margin on every exit route.
* **A schedule may only suppress.** When the box cannot trust its clock,
  every zone is enforced regardless of its hours (ADR-0018 §5): a clock
  fault must cost a director one extra glance, never an unwatched child.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any
from uuid import UUID, uuid4

from guardian_edge.application.debugging.explain import (
    MotionAnalysis,
    TrackEvaluation,
    TrackEvaluationObserver,
    motion_analysis,
)
from guardian_edge.application.events.history import TrackObservation
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType, EventSignal
from guardian_edge.domain.track import Track, TrackingResult
from guardian_edge.domain.zone import Zone
from guardian_edge.ops.clock import ClockStatus, ClockStatusProvider

logger = logging.getLogger(__name__)

_PRUNE_GRACE_SECONDS = 60.0
"""Slack beyond the cooldown before per-track state is forgotten."""


@dataclass(frozen=True, slots=True)
class ZoneSignalBreakdown:
    """The weighted zone signals; None when an earlier gate cut evaluation.

    Separate from the fall detector's ``SignalBreakdown`` because these are
    different measurements — forcing both into one shape would produce a
    record where most fields are meaningless for whichever detector wrote it.
    """

    dwell_score: float | None = None
    distance_score: float | None = None
    consistency_score: float | None = None
    confidence: float | None = None
    zone_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dwell_score": self.dwell_score,
            "distance_score": self.distance_score,
            "consistency_score": self.consistency_score,
            "confidence": self.confidence,
            "zone_id": self.zone_id,
        }


@dataclass(slots=True)
class _OutsideSince:
    """How long this track has been continuously outside one zone.

    Held per (track, zone) rather than derived from TrackHistoryStore: the
    shared history keeps a few seconds, while a dwell gate is measured in
    tens. Deriving it from a bounded buffer would silently cap the dwell at
    whatever the buffer happens to hold.
    """

    since: datetime
    last_seen: datetime
    largest_gap: float = 0.0


@dataclass(frozen=True, slots=True)
class ZoneExitDetectorConfig:
    """Tuning of the zone heuristic; every value is a physical statement."""

    monitored_labels: tuple[str, ...] = ("person", "child", "adult")

    min_dwell_seconds: float = 10.0
    """Continuous time outside before anything is a candidate. A product
    decision about how long an unattended child is acceptable (ADR-0018
    §10), not an engineering constant."""

    dwell_reference_seconds: float = 30.0
    """Time outside at which the dwell signal saturates to 1.0."""

    boundary_margin: float = 0.02
    """Hysteresis: how far past the edge (normalized units) a track must be
    before it counts as outside at all. A child standing on the line must
    not oscillate between candidate and not."""

    distance_reference: float = 0.15
    """Distance past the boundary at which the distance signal saturates."""

    max_gap_seconds: float = 1.5
    """A history gap longer than this breaks the dwell: we cannot claim a
    child was continuously outside across a stretch we did not observe."""

    weight_dwell: float = 0.5
    weight_distance: float = 0.3
    weight_consistency: float = 0.2
    confidence_threshold: float = 0.6
    cooldown_seconds: float = 60.0
    """One candidate per track per zone per cooldown. Longer than the fall
    detector's: a child who is out of the area stays out while a human walks
    over, and repeating that every ten seconds is noise, not evidence."""

    def __post_init__(self) -> None:
        if not self.monitored_labels:
            raise VisionConfigurationError("monitored_labels must not be empty")
        if self.min_dwell_seconds <= 0 or self.dwell_reference_seconds < self.min_dwell_seconds:
            raise VisionConfigurationError(
                "dwell must be positive and its reference at least the minimum"
            )
        if self.boundary_margin < 0 or self.distance_reference <= 0:
            raise VisionConfigurationError("boundary margin/reference must be non-negative")
        if self.max_gap_seconds <= 0:
            raise VisionConfigurationError("max_gap_seconds must be positive")
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise VisionConfigurationError(
                f"confidence_threshold out of range: {self.confidence_threshold}"
            )
        weights = (self.weight_dwell, self.weight_distance, self.weight_consistency)
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise VisionConfigurationError("signal weights must be non-negative, sum positive")


class ZoneExitDetector:
    """CandidateDetector for children outside a safe area (geometry only).

    Holds the zones for every camera; each evaluation uses only those
    belonging to the track's own camera. The optional ``observer`` receives
    a TrackEvaluation for EVERY decision — candidate or rejection with its
    exact reason. It is explanation only: attaching it changes nothing.
    """

    def __init__(
        self,
        zones: Sequence[Zone],
        clock_status: ClockStatusProvider,
        config: ZoneExitDetectorConfig | None = None,
        observer: TrackEvaluationObserver | None = None,
        local_zone: tzinfo | None = None,
    ) -> None:
        self._config = config or ZoneExitDetectorConfig()
        self._clock_status = clock_status
        self._observer = observer
        self._local_zone = local_zone
        """The box's configured zone, resolved once by the runtime from the
        clock's provenance. None means the system's local zone — the same
        answer, without an OS lookup inside a detector."""

        self._by_camera: dict[str, tuple[Zone, ...]] = {}
        for zone in zones:
            self._by_camera[zone.camera_id] = (*self._by_camera.get(zone.camera_id, ()), zone)
        self._cooldown_until: dict[tuple[UUID, str], datetime] = {}
        self._outside: dict[tuple[UUID, str], _OutsideSince] = {}

    @property
    def event_type(self) -> CandidateEventType:
        return CandidateEventType.ZONE_EXIT

    def evaluate(
        self,
        history: Sequence[TrackObservation],
        track: Track,
        result: TrackingResult,
    ) -> CandidateEvent | None:
        config = self._config
        if track.label not in config.monitored_labels:
            self._explain(
                track, result, history, "rejected", f"label '{track.label}' is not monitored"
            )
            return None

        zones = self._by_camera.get(result.camera_id, ())
        if not zones:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"no safe area is declared for camera '{result.camera_id}'",
            )
            return None
        if not history:
            self._explain(track, result, history, "rejected", "no confirmed observations yet")
            return None

        self._prune(result.captured_at)
        status = self._status()
        local_now = result.captured_at.astimezone(self._local_zone)
        best: CandidateEvent | None = None
        for zone in zones:
            candidate = self._evaluate_zone(zone, history, track, result, status, local_now)
            if candidate is not None and (best is None or candidate.confidence > best.confidence):
                best = candidate
        return best

    # ------------------------------------------------------------ per zone

    def _evaluate_zone(
        self,
        zone: Zone,
        history: Sequence[TrackObservation],
        track: Track,
        result: TrackingResult,
        status: ClockStatus,
        local_now: datetime,
    ) -> CandidateEvent | None:
        config = self._config

        # A schedule may only ever suppress: an untrusted clock enforces
        # every zone, and a stale one widens both edges by its error bound
        # (ADR-0018 §5-7). Under-alerting is the unacceptable failure.
        if status.trusted and not zone.is_active_at(local_now, status.error_bound_minutes):
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"zone '{zone.name}' is not active at {local_now:%H:%M} "
                f"(schedule: {zone.describe_schedule()})",
                zone_id=zone.zone_id,
            )
            return None

        cooldown_until = self._cooldown_until.get((track.track_id, zone.zone_id))
        if cooldown_until is not None and result.captured_at < cooldown_until:
            remaining = (cooldown_until - result.captured_at).total_seconds()
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"zone '{zone.name}' cooldown active ({remaining:.0f}s remaining "
                "after the previous candidate on this track)",
                zone_id=zone.zone_id,
            )
            return None

        key = (track.track_id, zone.zone_id)
        # Feet, not centre: a standing child meets the floor at the box's
        # bottom edge, and the floor is what the polygon describes.
        foot_x = track.box.x + track.box.width / 2.0
        foot_y = track.box.y + track.box.height

        if zone.contains(foot_x, foot_y):
            self._outside.pop(key, None)  # back inside: the dwell restarts
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"inside safe area '{zone.name}'",
                zone_id=zone.zone_id,
            )
            return None

        distance = zone.distance_to_boundary(foot_x, foot_y)
        if distance < config.boundary_margin:
            self._outside.pop(key, None)
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"on the boundary of '{zone.name}' ({distance:.3f} < "
                f"{config.boundary_margin:.3f} margin) — not yet out",
                zone_id=zone.zone_id,
            )
            return None

        dwell, largest_gap = self._accumulate_dwell(key, result.captured_at)
        if dwell < config.min_dwell_seconds:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"outside '{zone.name}' for only {dwell:.1f}s "
                f"(< {config.min_dwell_seconds:.0f}s required)",
                zone_id=zone.zone_id,
            )
            return None

        dwell_score = min(dwell / config.dwell_reference_seconds, 1.0)
        distance_score = min(distance / config.distance_reference, 1.0)
        # Consistency: how much of the stretch is a hole, not how close the
        # worst gap came to its limit. Measured against the dwell, a blink
        # costs little in a long exit and a lot in a short one — scaling it
        # to max_gap_seconds instead let one 1.2 s blink veto a real
        # thirteen-second exit, which is the under-alerting this whole
        # feature exists to avoid.
        consistency_score = max(0.0, 1.0 - largest_gap / dwell) if dwell > 0 else 0.0

        total_weight = config.weight_dwell + config.weight_distance + config.weight_consistency
        confidence = (
            config.weight_dwell * dwell_score
            + config.weight_distance * distance_score
            + config.weight_consistency * consistency_score
        ) / total_weight
        breakdown = ZoneSignalBreakdown(
            dwell_score=round(dwell_score, 3),
            distance_score=round(distance_score, 3),
            consistency_score=round(consistency_score, 3),
            confidence=round(confidence, 3),
            zone_id=zone.zone_id,
        )
        if confidence < config.confidence_threshold:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"confidence below threshold ({confidence:.2f} < "
                f"{config.confidence_threshold:.2f}) for '{zone.name}'",
                zone_id=zone.zone_id,
                breakdown=breakdown,
            )
            return None

        self._cooldown_until[key] = result.captured_at + timedelta(seconds=config.cooldown_seconds)
        self._outside.pop(key, None)
        self._explain(
            track,
            result,
            history,
            "candidate",
            f"outside '{zone.name}' for {dwell:.0f}s, {distance:.3f} past the boundary",
            zone_id=zone.zone_id,
            breakdown=breakdown,
        )
        return CandidateEvent(
            event_id=uuid4(),
            event_type=CandidateEventType.ZONE_EXIT,
            camera_id=result.camera_id,
            observed_at=result.captured_at,
            frame_id=result.frame_id,
            correlation_id=result.correlation_id,
            confidence=round(confidence, 3),
            track=track,
            signals=(
                EventSignal("dwell_outside", dwell_score, f"{dwell:.0f}s outside '{zone.name}'"),
                EventSignal(
                    "distance_past_boundary", distance_score, f"{distance:.3f} beyond the edge"
                ),
                EventSignal(
                    "observation_consistency",
                    consistency_score,
                    f"largest gap between sightings {largest_gap:.2f}s of {dwell:.0f}s",
                ),
            ),
        )

    # -------------------------------------------------------- explanation

    def _status(self) -> ClockStatus:
        try:
            return self._clock_status()
        except Exception:  # noqa: BLE001 - a clock fault must not stop detection
            logger.exception("clock status unavailable; enforcing every zone")
            return ClockStatus(trusted=False, reason="clock status unavailable")

    def _explain(
        self,
        track: Track,
        result: TrackingResult,
        history: Sequence[TrackObservation],
        outcome: str,
        reason: str,
        zone_id: str | None = None,
        breakdown: ZoneSignalBreakdown | None = None,
    ) -> None:
        """Emit the decision explanation; never influences the decision."""
        observer = self._observer
        if observer is None:
            return
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
                    outcome=outcome,
                    reason=reason,
                    motion=motion_analysis(history) if history else MotionAnalysis(),
                    signals=breakdown or ZoneSignalBreakdown(zone_id=zone_id),
                )
            )
        except Exception:  # noqa: BLE001 - explanations must never break detection
            logger.exception("zone decision observer failed; detection unaffected")

    def _accumulate_dwell(self, key: tuple[UUID, str], now: datetime) -> tuple[float, float]:
        """Advance this track's continuous time outside, and the largest gap.

        A gap longer than ``max_gap_seconds`` restarts the dwell: we do not
        get to claim a child was outside during a stretch nobody watched
        (ADR-0018 §9). The largest gap within the stretch is what makes the
        consistency signal meaningful — every gap is under the limit by
        construction, but a stretch sampled every 100 ms is far better
        evidence than one held together by a single 1.4-second bridge.
        """
        state = self._outside.get(key)
        if state is None:
            self._outside[key] = _OutsideSince(since=now, last_seen=now)
            return 0.0, 0.0
        gap = (now - state.last_seen).total_seconds()
        if gap > self._config.max_gap_seconds or gap < 0:
            self._outside[key] = _OutsideSince(since=now, last_seen=now)
            return 0.0, 0.0
        state.largest_gap = max(state.largest_gap, gap)
        state.last_seen = now
        return (now - state.since).total_seconds(), state.largest_gap

    def _prune(self, now: datetime) -> None:
        """Forget tracks nobody has seen for a while — both dicts are keyed
        by track id, and track ids are created for every child, all day."""
        horizon = timedelta(seconds=self._config.cooldown_seconds + _PRUNE_GRACE_SECONDS)
        self._outside = {
            key: state for key, state in self._outside.items() if now - state.last_seen <= horizon
        }
        self._cooldown_until = {
            key: until for key, until in self._cooldown_until.items() if until + horizon > now
        }
