"""Exponential retry strategy for notification delivery."""

from __future__ import annotations

from dataclasses import dataclass

from guardian_edge.domain.errors import VisionConfigurationError

DEFAULT_RETRY_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0)


@dataclass(frozen=True, slots=True)
class RetryStrategy:
    """Delay ladder between failed attempts; the end of the ladder is
    permanent failure. Defaults: 1s → 2s → 5s → 10s → 30s → FAILED
    (six attempts total)."""

    delays_seconds: tuple[float, ...] = DEFAULT_RETRY_DELAYS

    def __post_init__(self) -> None:
        if not self.delays_seconds:
            raise VisionConfigurationError("retry ladder must have at least one delay")
        if any(delay <= 0 for delay in self.delays_seconds):
            raise VisionConfigurationError("retry delays must be positive")
        if list(self.delays_seconds) != sorted(self.delays_seconds):
            raise VisionConfigurationError("retry delays must be non-decreasing")

    @property
    def max_attempts(self) -> int:
        """Total send attempts before permanent failure."""
        return len(self.delays_seconds) + 1

    def delay_after_failure(self, failures: int) -> float | None:
        """Delay before the next attempt after ``failures`` failed attempts;
        None means permanent failure."""
        if failures < 1:
            raise VisionConfigurationError("failures must be >= 1")
        if failures > len(self.delays_seconds):
            return None
        return self.delays_seconds[failures - 1]
