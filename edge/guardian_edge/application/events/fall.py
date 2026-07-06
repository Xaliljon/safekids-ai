"""Potential-fall candidate detection.

A fall, seen by a fixed camera, is a *combination* of explainable signals:
rapid downward motion of the body center, the bounding box flipping from
tall to wide, ending low in the frame, followed by stillness. No single
signal is a fall; the weighted combination is a *candidate*, never a
conclusion (docs/04 — humans verify every event).

Heuristic and geometry-only by design (ADR-0012): no pose estimation, no
learned classifier — those come later, behind this same detector port,
trained on data the dataset platform (ADR-0010) collects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from guardian_edge.application.debugging.explain import (
    MotionAnalysis,
    SignalBreakdown,
    TrackEvaluation,
    TrackEvaluationObserver,
    motion_analysis,
)
from guardian_edge.application.events.features import (
    baseline_aspect_ratio,
    current_aspect_ratio,
    duration_seconds,
    ground_proximity,
    peak_downward_velocity,
    stillness_score,
)
from guardian_edge.application.events.history import TrackObservation
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType, EventSignal
from guardian_edge.domain.track import Track, TrackingResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FallDetectorConfig:
    """Tuning of the fall heuristic; every value is a physical statement."""

    monitored_labels: tuple[str, ...] = ("person", "child", "adult")
    min_history_seconds: float = 1.0
    velocity_window_seconds: float = 1.5
    drop_velocity_gate: float = 0.2
    """Below this downward speed (frame-heights/s) nothing is ever a fall."""

    drop_velocity_reference: float = 0.6
    """Downward speed at which the drop signal saturates to 1.0."""

    flip_reference: float = 1.0
    """Aspect-ratio increase (vs baseline) that scores 1.0 (tall -> wide)."""

    ground_reference: float = 0.55
    """Lower-edge position below which the ground signal is 0."""

    stillness_window_seconds: float = 1.0
    stillness_speed: float = 0.06
    """Speed (units/s) above which post-event stillness scores 0."""

    weight_drop: float = 0.35
    weight_flip: float = 0.25
    weight_ground: float = 0.20
    weight_stillness: float = 0.20
    confidence_threshold: float = 0.6
    cooldown_seconds: float = 10.0
    """One candidate per track per cooldown — evidence, not spam."""

    def __post_init__(self) -> None:
        if not self.monitored_labels:
            raise VisionConfigurationError("monitored_labels must not be empty")
        if not (0.0 < self.drop_velocity_gate <= self.drop_velocity_reference):
            raise VisionConfigurationError(
                "drop velocity gate must be positive and <= its reference"
            )
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise VisionConfigurationError(
                f"confidence_threshold out of range: {self.confidence_threshold}"
            )
        weights = (self.weight_drop, self.weight_flip, self.weight_ground, self.weight_stillness)
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise VisionConfigurationError("signal weights must be non-negative, sum positive")


class PotentialFallDetector:
    """CandidateDetector for potential falls (geometry heuristics only).

    The optional ``observer`` receives a TrackEvaluation for EVERY decision
    — candidate or rejection with its exact reason (Sprint 10.1). It is
    explanation only: attaching it changes no decision and no threshold.
    """

    def __init__(
        self,
        config: FallDetectorConfig | None = None,
        observer: TrackEvaluationObserver | None = None,
    ) -> None:
        self._config = config or FallDetectorConfig()
        self._cooldown_until: dict[UUID, datetime] = {}
        self._observer = observer

    @property
    def event_type(self) -> CandidateEventType:
        return CandidateEventType.POTENTIAL_FALL

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
        history_span = duration_seconds(history)
        if history_span < config.min_history_seconds:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"track history too short ({history_span:.2f}s < "
                f"{config.min_history_seconds:.2f}s required)",
            )
            return None
        cooldown_until = self._cooldown_until.get(track.track_id)
        if cooldown_until is not None and result.captured_at < cooldown_until:
            remaining = (cooldown_until - result.captured_at).total_seconds()
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"detector cooldown active ({remaining:.1f}s remaining after "
                "the previous candidate on this track)",
            )
            return None

        drop = peak_downward_velocity(history, config.velocity_window_seconds)
        if drop < config.drop_velocity_gate:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"downward velocity too low ({drop:.2f} < "
                f"{config.drop_velocity_gate:.2f} frame-heights/s gate)",
                peak_downward=drop,
            )
            return None  # hard gate: no downward motion, no fall candidate

        drop_score = min(drop / config.drop_velocity_reference, 1.0)
        baseline = baseline_aspect_ratio(history)
        current = current_aspect_ratio(history)
        flip_score = min(max((current - baseline) / config.flip_reference, 0.0), 1.0)
        bottom = ground_proximity(history)
        ground_score = min(
            max((bottom - config.ground_reference) / (1.0 - config.ground_reference), 0.0), 1.0
        )
        still_score = stillness_score(
            history, config.stillness_window_seconds, config.stillness_speed
        )

        total_weight = (
            config.weight_drop + config.weight_flip + config.weight_ground + config.weight_stillness
        )
        confidence = (
            config.weight_drop * drop_score
            + config.weight_flip * flip_score
            + config.weight_ground * ground_score
            + config.weight_stillness * still_score
        ) / total_weight
        breakdown = SignalBreakdown(
            velocity_score=round(drop_score, 3),
            aspect_ratio_score=round(flip_score, 3),
            ground_score=round(ground_score, 3),
            stillness_score=round(still_score, 3),
            confidence=round(confidence, 3),
        )
        if confidence < config.confidence_threshold:
            self._explain(
                track,
                result,
                history,
                "rejected",
                f"confidence below threshold ({confidence:.2f} < "
                f"{config.confidence_threshold:.2f})",
                peak_downward=drop,
                breakdown=breakdown,
            )
            return None

        self._cooldown_until[track.track_id] = result.captured_at + timedelta(
            seconds=config.cooldown_seconds
        )
        self._explain(
            track,
            result,
            history,
            "candidate",
            f"all signals combined to {confidence:.2f} >= "
            f"{config.confidence_threshold:.2f} threshold",
            peak_downward=drop,
            breakdown=breakdown,
        )
        return CandidateEvent(
            event_id=uuid4(),
            event_type=CandidateEventType.POTENTIAL_FALL,
            camera_id=result.camera_id,
            observed_at=result.captured_at,
            frame_id=result.frame_id,
            correlation_id=result.correlation_id,
            confidence=round(confidence, 3),
            track=track,
            signals=(
                EventSignal(
                    "downward_velocity", drop_score, f"{drop:.2f} frame-heights/s downward"
                ),
                EventSignal(
                    "aspect_ratio_flip",
                    flip_score,
                    f"width/height {baseline:.2f} -> {current:.2f}",
                ),
                EventSignal("ground_proximity", ground_score, f"lower edge at {bottom:.2f}"),
                EventSignal(
                    "stillness",
                    still_score,
                    f"movement over last {config.stillness_window_seconds:.1f}s",
                ),
            ),
        )

    # -------------------------------------------------------- explanation

    def _explain(
        self,
        track: Track,
        result: TrackingResult,
        history: Sequence[TrackObservation],
        outcome: str,
        reason: str,
        peak_downward: float | None = None,
        breakdown: SignalBreakdown | None = None,
    ) -> None:
        """Emit the decision explanation; never influences the decision."""
        observer = self._observer
        if observer is None:
            return
        try:
            motion = (
                motion_analysis(history, peak_downward)
                if history
                else MotionAnalysis(peak_downward_velocity=peak_downward)
            )
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
                    motion=motion,
                    signals=breakdown or SignalBreakdown(),
                )
            )
        except Exception:  # noqa: BLE001 - explanations must never break detection
            logger.exception("fall decision observer failed; detection unaffected")
