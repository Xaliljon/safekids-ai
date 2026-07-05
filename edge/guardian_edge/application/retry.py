"""Stream recovery policy."""

from __future__ import annotations

from dataclasses import dataclass

from guardian_edge.domain.errors import CameraConfigurationError


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff for stream recovery.

    Recovery never gives up: after ``failed_after_attempts`` consecutive
    failures the camera is reported FAILED (so humans get alerted), but
    reconnection keeps retrying at ``max_delay_seconds`` — a camera must
    come back on its own once power or network returns.
    """

    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    failed_after_attempts: int = 5

    def __post_init__(self) -> None:
        if self.initial_delay_seconds <= 0:
            raise CameraConfigurationError("initial_delay_seconds must be positive")
        if self.multiplier < 1.0:
            raise CameraConfigurationError("multiplier must be >= 1.0")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise CameraConfigurationError("max_delay_seconds must be >= initial_delay_seconds")
        if self.failed_after_attempts < 1:
            raise CameraConfigurationError("failed_after_attempts must be >= 1")

    def delay_for_attempt(self, attempt: int) -> float:
        """Backoff delay in seconds before reconnect ``attempt`` (1-based)."""
        exponent = max(attempt - 1, 0)
        delay = self.initial_delay_seconds * (self.multiplier**exponent)
        return min(delay, self.max_delay_seconds)
