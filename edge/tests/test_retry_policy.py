"""Exponential backoff policy."""

import pytest

from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.errors import CameraConfigurationError


def test_delay_grows_exponentially_and_caps() -> None:
    policy = RetryPolicy(initial_delay_seconds=1.0, multiplier=2.0, max_delay_seconds=30.0)
    delays = [policy.delay_for_attempt(attempt) for attempt in range(1, 8)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_first_attempt_uses_initial_delay() -> None:
    policy = RetryPolicy(initial_delay_seconds=0.5)
    assert policy.delay_for_attempt(1) == 0.5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_delay_seconds": 0.0},
        {"initial_delay_seconds": -1.0},
        {"multiplier": 0.5},
        {"initial_delay_seconds": 10.0, "max_delay_seconds": 5.0},
        {"failed_after_attempts": 0},
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, float]) -> None:
    with pytest.raises(CameraConfigurationError):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]
