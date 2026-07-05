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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

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
    """CandidateDetector for potential falls (geometry heuristics only)."""

    def __init__(self, config: FallDetectorConfig | None = None) -> None:
        self._config = config or FallDetectorConfig()
        self._cooldown_until: dict[UUID, datetime] = {}

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
            return None
        if duration_seconds(history) < config.min_history_seconds:
            return None
        cooldown_until = self._cooldown_until.get(track.track_id)
        if cooldown_until is not None and result.captured_at < cooldown_until:
            return None

        drop = peak_downward_velocity(history, config.velocity_window_seconds)
        if drop < config.drop_velocity_gate:
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
        if confidence < config.confidence_threshold:
            return None

        self._cooldown_until[track.track_id] = result.captured_at + timedelta(
            seconds=config.cooldown_seconds
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
