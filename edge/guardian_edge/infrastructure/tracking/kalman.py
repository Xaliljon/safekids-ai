"""Constant-velocity Kalman filter over normalized box coordinates.

State: [cx, cy, w, h, vcx, vcy, vw, vh] in normalized frame units.
Standard predict/update; noise magnitudes are tuned for [0, 1] coordinate
space. This is what lets a LOST track keep a plausible position through
occlusion so it can be re-associated instead of re-identified.
"""

from __future__ import annotations

import numpy as np

_STATE_SIZE = 8
_MEASUREMENT_SIZE = 4

# Noise in normalized units: measurements are trusted to ~1% of the frame;
# the process drifts slowly (velocities change little frame to frame).
_MEASUREMENT_VARIANCE = 1e-4
_PROCESS_POSITION_VARIANCE = 1e-6
_PROCESS_VELOCITY_VARIANCE = 1e-5
_INITIAL_VELOCITY_VARIANCE = 1e-2

BoxTuple = tuple[float, float, float, float]
"""(cx, cy, w, h) — center-form normalized box."""


class KalmanBoxFilter:
    """Tracks one box; one instance per track."""

    def __init__(self, box: BoxTuple) -> None:
        self._x = np.zeros(_STATE_SIZE, dtype=np.float64)
        self._x[:_MEASUREMENT_SIZE] = box

        self._F = np.eye(_STATE_SIZE, dtype=np.float64)
        for axis in range(_MEASUREMENT_SIZE):
            self._F[axis, axis + _MEASUREMENT_SIZE] = 1.0  # x += v each frame

        self._H = np.zeros((_MEASUREMENT_SIZE, _STATE_SIZE), dtype=np.float64)
        self._H[:, :_MEASUREMENT_SIZE] = np.eye(_MEASUREMENT_SIZE)

        self._P = np.eye(_STATE_SIZE, dtype=np.float64) * _MEASUREMENT_VARIANCE
        self._P[_MEASUREMENT_SIZE:, _MEASUREMENT_SIZE:] = (
            np.eye(_MEASUREMENT_SIZE) * _INITIAL_VELOCITY_VARIANCE
        )

        self._Q = np.eye(_STATE_SIZE, dtype=np.float64) * _PROCESS_POSITION_VARIANCE
        self._Q[_MEASUREMENT_SIZE:, _MEASUREMENT_SIZE:] = (
            np.eye(_MEASUREMENT_SIZE) * _PROCESS_VELOCITY_VARIANCE
        )

        self._R = np.eye(_MEASUREMENT_SIZE, dtype=np.float64) * _MEASUREMENT_VARIANCE

    def predict(self) -> BoxTuple:
        """Advance one frame; returns the predicted box."""
        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + self._Q
        return self.box

    def update(self, box: BoxTuple) -> None:
        """Correct the state with a measured box."""
        z = np.asarray(box, dtype=np.float64)
        innovation = z - self._H @ self._x
        s = self._H @ self._P @ self._H.T + self._R
        gain = self._P @ self._H.T @ np.linalg.inv(s)
        self._x = self._x + gain @ innovation
        self._P = (np.eye(_STATE_SIZE) - gain @ self._H) @ self._P

    @property
    def box(self) -> BoxTuple:
        """Current (cx, cy, w, h) estimate."""
        return (
            float(self._x[0]),
            float(self._x[1]),
            float(self._x[2]),
            float(self._x[3]),
        )
