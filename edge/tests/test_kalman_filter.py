"""Constant-velocity Kalman filter behavior."""

import pytest

from guardian_edge.infrastructure.tracking.kalman import KalmanBoxFilter


def test_stationary_box_stays_put() -> None:
    kalman = KalmanBoxFilter((0.5, 0.5, 0.2, 0.3))
    for _ in range(10):
        kalman.predict()
        kalman.update((0.5, 0.5, 0.2, 0.3))
    cx, cy, w, h = kalman.box
    assert cx == pytest.approx(0.5, abs=1e-3)
    assert cy == pytest.approx(0.5, abs=1e-3)
    assert (w, h) == (pytest.approx(0.2, abs=1e-3), pytest.approx(0.3, abs=1e-3))


def test_learns_constant_velocity_and_predicts_ahead() -> None:
    kalman = KalmanBoxFilter((0.10, 0.5, 0.1, 0.2))
    x = 0.10
    for _ in range(20):
        x += 0.01
        kalman.predict()
        kalman.update((x, 0.5, 0.1, 0.2))
    # Coast without measurements: prediction should keep moving right.
    coasted = [kalman.predict()[0] for _ in range(5)]
    assert coasted[0] > x - 0.005
    assert coasted[-1] > coasted[0] + 0.02, "learned velocity must carry the box forward"


def test_update_pulls_prediction_toward_measurement() -> None:
    kalman = KalmanBoxFilter((0.2, 0.2, 0.1, 0.1))
    kalman.predict()
    kalman.update((0.3, 0.2, 0.1, 0.1))
    cx = kalman.box[0]
    assert 0.2 < cx <= 0.3, "estimate must move toward the measurement"
