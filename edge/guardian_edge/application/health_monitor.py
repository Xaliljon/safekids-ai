"""Periodic camera health evaluation.

Second line of defense against silent stalls: a stream that stays "connected"
but stops delivering frames is asked to recover (the first line is the
stream implementation's own read timeout). Also notifies a listener whenever
a camera's health status changes — that hook is where the future notification
engine attaches. This module never decides what humans do (docs/04).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping

from guardian_edge.domain.camera import CameraState
from guardian_edge.domain.health import CameraHealth, HealthStatus

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS = 5.0
DEFAULT_STALE_FRAME_AFTER_SECONDS = 10.0

HealthProvider = Callable[[], Mapping[str, CameraHealth]]
StallHandler = Callable[[str], None]
StatusListener = Callable[[CameraHealth], None]


class HealthMonitor:
    """Evaluates camera health on an interval; requests recovery on stalls.

    A failing check never stops the monitor (no single failure crashes the
    platform — docs/03). ``check_once()`` is public so callers and tests can
    drive evaluation without threads.
    """

    def __init__(
        self,
        health_provider: HealthProvider,
        stall_handler: StallHandler,
        status_listener: StatusListener | None = None,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        stale_frame_after_seconds: float = DEFAULT_STALE_FRAME_AFTER_SECONDS,
    ) -> None:
        self._health_provider = health_provider
        self._stall_handler = stall_handler
        self._status_listener = status_listener
        self._check_interval = check_interval_seconds
        self._stale_frame_after = stale_frame_after_seconds

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_status: dict[str, HealthStatus] = {}

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start periodic checks on a dedicated thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="camera-health-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop periodic checks. Idempotent."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._check_interval + 5.0)
        self._thread = None

    # ------------------------------------------------------------- checking

    def check_once(self) -> None:
        """Evaluate all cameras once: trigger recovery on stalls, notify changes."""
        report = self._health_provider()
        for camera_id, health in report.items():
            if self._is_stalled(health):
                logger.warning(
                    "camera %s: streaming but no frames for %.1fs; requesting stream recovery",
                    camera_id,
                    health.last_frame_age_seconds,
                )
                self._stall_handler(camera_id)
            self._notify_if_changed(health)
        self._forget_removed(report)

    def _is_stalled(self, health: CameraHealth) -> bool:
        return (
            health.state is CameraState.STREAMING
            and health.last_frame_age_seconds is not None
            and health.last_frame_age_seconds > self._stale_frame_after
        )

    def _notify_if_changed(self, health: CameraHealth) -> None:
        previous = self._last_status.get(health.camera_id)
        if previous is health.status:
            return
        self._last_status[health.camera_id] = health.status
        logger.info(
            "camera %s: health %s -> %s",
            health.camera_id,
            previous.value if previous is not None else "unknown",
            health.status.value,
        )
        if self._status_listener is None:
            return
        try:
            self._status_listener(health)
        except Exception:
            logger.exception("camera %s: status listener raised", health.camera_id)

    def _forget_removed(self, report: Mapping[str, CameraHealth]) -> None:
        for camera_id in list(self._last_status):
            if camera_id not in report:
                del self._last_status[camera_id]

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception:
                logger.exception("health check failed; monitor continues")
            self._stop_event.wait(self._check_interval)
