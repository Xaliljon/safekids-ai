"""Camera entity and stream lifecycle states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
from urllib.parse import urlparse, urlunparse

from guardian_edge.domain.errors import CameraConfigurationError

_ALLOWED_SCHEMES = frozenset({"rtsp", "rtsps"})


@unique
class CameraState(Enum):
    """Lifecycle of a managed camera stream.

    IDLE -> CONNECTING -> STREAMING, with RECONNECTING on any stream loss.
    FAILED means repeated reconnects have not succeeded yet; recovery keeps
    retrying — a camera must come back on its own when power/network returns.
    STOPPED is terminal for a session (operator or shutdown).
    """

    IDLE = "idle"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class Camera:
    """A registered camera.

    Cameras are registered explicitly by an operator; the runtime never
    auto-trusts devices found on the network (docs/03, security by default).
    """

    camera_id: str
    name: str
    rtsp_url: str
    location: str = ""

    def __post_init__(self) -> None:
        if not self.camera_id.strip():
            raise CameraConfigurationError("camera_id must not be empty")
        try:
            parsed = urlparse(self.rtsp_url)
            hostname = parsed.hostname
            _ = parsed.port  # raises ValueError on malformed ports
        except ValueError as exc:
            raise CameraConfigurationError(
                f"camera '{self.camera_id}': malformed rtsp_url"
            ) from exc
        if parsed.scheme not in _ALLOWED_SCHEMES or not hostname:
            raise CameraConfigurationError(
                f"camera '{self.camera_id}': rtsp_url must look like rtsp://host[:port]/path"
            )

    @property
    def redacted_url(self) -> str:
        """The RTSP URL with credentials masked — the only form allowed in logs."""
        parsed = urlparse(self.rtsp_url)
        if not (parsed.username or parsed.password):
            return self.rtsp_url
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=f"***:***@{host}"))
