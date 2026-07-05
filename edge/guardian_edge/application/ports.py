"""Ports (interfaces) the camera application layer depends on.

Infrastructure provides implementations; tests provide fakes.
Dependencies point inward (ADR-0001): this module imports domain only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from guardian_edge.domain.camera import Camera
from guardian_edge.domain.discovery import DiscoveredCamera
from guardian_edge.domain.frame import Frame

FrameConsumer = Callable[[Frame], None]
"""Receives every captured frame on the capture thread.

Consumers must be fast and must not block; a consumer that raises loses that
frame but never stops capture. The future AI pipeline attaches here.
"""


class VideoStream(Protocol):
    """One open video stream. Owned by a single capture session."""

    def read(self) -> Frame:
        """Block until the next frame arrives.

        Raises CameraReadError when the stream stalls or ends.
        Implementations must enforce a read timeout so a dead camera can
        never block a capture thread forever.
        """
        ...

    def close(self) -> None:
        """Release the stream. Idempotent."""
        ...


class VideoStreamFactory(Protocol):
    """Opens video streams for cameras."""

    def open(self, camera: Camera) -> VideoStream:
        """Open a stream for the camera.

        Raises CameraConnectionError when the stream cannot be opened.
        Error messages must use ``camera.redacted_url``, never the raw URL.
        """
        ...


class CameraDiscovery(Protocol):
    """Finds camera candidates on the local network."""

    def discover(self, timeout_seconds: float) -> list[DiscoveredCamera]:
        """Probe the network and return candidates found within the timeout.

        Raises DiscoveryError when the probe itself cannot be performed.
        """
        ...
