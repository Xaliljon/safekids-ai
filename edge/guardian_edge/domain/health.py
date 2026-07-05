"""Camera health reporting model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique

from guardian_edge.domain.camera import CameraState


@unique
class HealthStatus(Enum):
    """Operator-facing health rollup for one camera.

    HEALTHY   — streaming and delivering recent frames.
    DEGRADED  — connecting, reconnecting, or streaming but stale.
    UNHEALTHY — failed, stopped, or never started.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class CameraHealth:
    """Point-in-time health snapshot of one camera session."""

    camera_id: str
    state: CameraState
    status: HealthStatus
    frames_total: int
    frames_per_second: float
    last_frame_age_seconds: float | None
    reconnects_total: int
    consecutive_failures: int
