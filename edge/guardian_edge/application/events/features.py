"""Motion and shape features over a track's observation history.

Pure functions, normalized coordinate space (ADR-0006): velocities are in
frame-heights (or -widths) per second, positions in [0, 1]. Every feature
is an explainable measurement — the numbers that end up in EventSignals.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

from guardian_edge.application.events.history import TrackObservation

_MIN_VELOCITY_DT_SECONDS = 0.15
"""Velocity pairs closer than this are noise, not motion."""

_BASELINE_FRACTION = 0.3
_CURRENT_SAMPLES = 3


def duration_seconds(history: Sequence[TrackObservation]) -> float:
    """Time span covered by the history."""
    if len(history) < 2:
        return 0.0
    return (history[-1].captured_at - history[0].captured_at).total_seconds()


def trailing(
    history: Sequence[TrackObservation], window_seconds: float
) -> Sequence[TrackObservation]:
    """Observations within the trailing window (always keeps the newest)."""
    if not history:
        return history
    cutoff = history[-1].captured_at
    return [
        observation
        for observation in history
        if (cutoff - observation.captured_at).total_seconds() <= window_seconds
    ]


def peak_downward_velocity(history: Sequence[TrackObservation], window_seconds: float) -> float:
    """Fastest sustained downward motion (frame-heights/s) in the window.

    Measured between observation pairs at least _MIN_VELOCITY_DT_SECONDS
    apart so frame-to-frame jitter never reads as a fall. Positive = down
    (image coordinates); never negative (upward motion returns 0).
    """
    observations = trailing(history, window_seconds)
    peak = 0.0
    end = 1
    for start in range(len(observations)):
        end = max(end, start + 1)
        while end < len(observations):
            dt = (observations[end].captured_at - observations[start].captured_at).total_seconds()
            if dt >= _MIN_VELOCITY_DT_SECONDS:
                velocity = (observations[end].center_y - observations[start].center_y) / dt
                peak = max(peak, velocity)
                break
            end += 1
    return peak


def average_speed(history: Sequence[TrackObservation], window_seconds: float) -> float:
    """Mean center speed (normalized units/s) over the trailing window."""
    observations = trailing(history, window_seconds)
    if len(observations) < 2:
        return 0.0
    distance = 0.0
    for previous, current in zip(observations, observations[1:], strict=False):
        distance += math.hypot(
            current.center_x - previous.center_x, current.center_y - previous.center_y
        )
    dt = (observations[-1].captured_at - observations[0].captured_at).total_seconds()
    return distance / dt if dt > 0 else 0.0


def baseline_aspect_ratio(history: Sequence[TrackObservation]) -> float:
    """Typical shape early in the history (median of the earliest 30%)."""
    if not history:
        return 0.0
    count = max(1, int(len(history) * _BASELINE_FRACTION))
    return median(observation.aspect_ratio for observation in history[:count])


def current_aspect_ratio(history: Sequence[TrackObservation]) -> float:
    """Recent shape (median of the last few observations, jitter-resistant)."""
    if not history:
        return 0.0
    return median(observation.aspect_ratio for observation in history[-_CURRENT_SAMPLES:])


def ground_proximity(history: Sequence[TrackObservation]) -> float:
    """Current lower-edge position in [0, 1]; 1.0 = the bottom of the frame.

    A proxy without scene calibration: floors are overwhelmingly in the
    lower image region for ceiling-mounted classroom cameras.
    """
    return history[-1].bottom if history else 0.0


def stillness_score(
    history: Sequence[TrackObservation], window_seconds: float, max_speed: float
) -> float:
    """1.0 = motionless over the trailing window, fading to 0 at max_speed."""
    observations = trailing(history, window_seconds)
    if len(observations) < 2:
        return 0.0
    speed = average_speed(observations, window_seconds)
    return max(0.0, 1.0 - speed / max_speed) if max_speed > 0 else 0.0
