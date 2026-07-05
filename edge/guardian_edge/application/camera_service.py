"""The Edge Camera Service — facade over all camera capture sessions.

Owns one CaptureSession per registered camera plus the HealthMonitor.
This is the single entry point other edge subsystems use; nothing outside
the application layer touches sessions directly.

Responsibilities end at delivering frames and health. No AI, no storage,
no event generation (those are separate engines — docs/03, modular design).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from guardian_edge.application.capture_session import (
    DEFAULT_STALE_FRAME_AFTER_SECONDS,
    CaptureSession,
)
from guardian_edge.application.health_monitor import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    HealthMonitor,
    StatusListener,
)
from guardian_edge.application.ports import FrameConsumer, VideoStreamFactory
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.camera import Camera
from guardian_edge.domain.errors import CameraConfigurationError
from guardian_edge.domain.health import CameraHealth


class CameraService:
    """Manages the full set of cameras: registration, capture, health, recovery.

    All methods are safe to call from any thread. Cameras can be added and
    removed while the service is running.
    """

    def __init__(
        self,
        stream_factory: VideoStreamFactory,
        frame_consumer: FrameConsumer,
        retry_policy: RetryPolicy | None = None,
        status_listener: StatusListener | None = None,
        health_check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        stale_frame_after_seconds: float = DEFAULT_STALE_FRAME_AFTER_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream_factory = stream_factory
        self._frame_consumer = frame_consumer
        self._retry_policy = retry_policy
        self._stale_frame_after = stale_frame_after_seconds
        self._clock = clock

        self._lock = threading.Lock()
        self._sessions: dict[str, CaptureSession] = {}
        self._started = False

        self._monitor = HealthMonitor(
            health_provider=self.health_report,
            stall_handler=self._request_reconnect,
            status_listener=status_listener,
            check_interval_seconds=health_check_interval_seconds,
            stale_frame_after_seconds=stale_frame_after_seconds,
        )

    # --------------------------------------------------------- registration

    def add_camera(self, camera: Camera) -> None:
        """Register a camera; starts capturing immediately if the service runs.

        Raises CameraConfigurationError on a duplicate camera_id.
        """
        session = CaptureSession(
            camera=camera,
            stream_factory=self._stream_factory,
            frame_consumer=self._frame_consumer,
            retry_policy=self._retry_policy,
            stale_frame_after_seconds=self._stale_frame_after,
            clock=self._clock,
        )
        with self._lock:
            if camera.camera_id in self._sessions:
                raise CameraConfigurationError(f"camera '{camera.camera_id}' is already registered")
            self._sessions[camera.camera_id] = session
            started = self._started
        if started:
            session.start()

    def remove_camera(self, camera_id: str) -> None:
        """Unregister a camera and stop its capture.

        Raises CameraConfigurationError if the camera is not registered.
        """
        with self._lock:
            session = self._sessions.pop(camera_id, None)
        if session is None:
            raise CameraConfigurationError(f"camera '{camera_id}' is not registered")
        session.stop()

    def cameras(self) -> list[Camera]:
        """Registered cameras."""
        with self._lock:
            return [session.camera for session in self._sessions.values()]

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start capture for all registered cameras and health monitoring."""
        with self._lock:
            if self._started:
                return
            self._started = True
            sessions = list(self._sessions.values())
        for session in sessions:
            session.start()
        self._monitor.start()

    def stop(self) -> None:
        """Stop health monitoring and all capture sessions."""
        with self._lock:
            self._started = False
            sessions = list(self._sessions.values())
        self._monitor.stop()
        for session in sessions:
            session.stop()

    # --------------------------------------------------------------- health

    def health_report(self) -> dict[str, CameraHealth]:
        """Health snapshot for every registered camera."""
        with self._lock:
            sessions = list(self._sessions.values())
        return {session.camera.camera_id: session.health() for session in sessions}

    def _request_reconnect(self, camera_id: str) -> None:
        with self._lock:
            session = self._sessions.get(camera_id)
        if session is not None:
            session.request_reconnect()
