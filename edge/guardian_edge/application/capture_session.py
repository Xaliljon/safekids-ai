"""One camera's capture lifecycle on a dedicated thread.

The session connects, reads frames, hands them to the frame consumer, and
recovers from failures with exponential backoff (see RetryPolicy — recovery
never gives up). Health metrics are tracked for the HealthMonitor.

Capture only — no AI, no encoding, no persistence (ADR-0001).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable

from guardian_edge.application.ports import FrameConsumer, VideoStream, VideoStreamFactory
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.camera import Camera, CameraState
from guardian_edge.domain.errors import CameraError
from guardian_edge.domain.health import CameraHealth, HealthStatus

logger = logging.getLogger(__name__)

FPS_WINDOW_SECONDS = 10.0
DEFAULT_STALE_FRAME_AFTER_SECONDS = 10.0
DEFAULT_STOP_JOIN_TIMEOUT_SECONDS = 15.0


class CaptureSession:
    """Owns one camera's stream: connect, capture, recover, report health.

    Thread model: ``start()`` spawns one daemon thread that runs the capture
    loop; all public methods are safe to call from any thread. A blocked
    ``read()`` is bounded by the stream implementation's read timeout, so the
    loop always regains control and can honor ``stop()``/``request_reconnect()``.
    """

    def __init__(
        self,
        camera: Camera,
        stream_factory: VideoStreamFactory,
        frame_consumer: FrameConsumer,
        retry_policy: RetryPolicy | None = None,
        stale_frame_after_seconds: float = DEFAULT_STALE_FRAME_AFTER_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._camera = camera
        self._stream_factory = stream_factory
        self._frame_consumer = frame_consumer
        self._retry_policy = retry_policy or RetryPolicy()
        self._stale_frame_after = stale_frame_after_seconds
        self._clock = clock

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._reconnect_event = threading.Event()

        self._lock = threading.Lock()
        self._state = CameraState.IDLE
        self._frames_total = 0
        self._reconnects_total = 0
        self._consecutive_failures = 0
        self._last_frame_at: float | None = None
        self._frame_times: deque[float] = deque()

    @property
    def camera(self) -> Camera:
        return self._camera

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start capturing on a dedicated thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._reconnect_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"camera-{self._camera.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout_seconds: float = DEFAULT_STOP_JOIN_TIMEOUT_SECONDS) -> None:
        """Stop capturing and wait for the thread to exit. Idempotent."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout_seconds)
            if thread.is_alive():
                logger.warning(
                    "camera %s: capture thread did not stop within %.1fs",
                    self._camera.camera_id,
                    join_timeout_seconds,
                )
        self._thread = None
        self._set_state(CameraState.STOPPED)

    def request_reconnect(self) -> None:
        """Ask the session to drop and re-open its stream.

        Used by the HealthMonitor on silent stalls. Takes effect before the
        next read; a read already in flight is bounded by the stream's
        read timeout.
        """
        self._reconnect_event.set()

    # -------------------------------------------------------------- health

    def health(self) -> CameraHealth:
        """Point-in-time health snapshot. Safe to call from any thread."""
        now = self._clock()
        with self._lock:
            state = self._state
            frames_total = self._frames_total
            reconnects_total = self._reconnects_total
            consecutive_failures = self._consecutive_failures
            last_frame_at = self._last_frame_at
            recent_frames = sum(1 for t in self._frame_times if t >= now - FPS_WINDOW_SECONDS)
        last_frame_age = None if last_frame_at is None else max(now - last_frame_at, 0.0)
        return CameraHealth(
            camera_id=self._camera.camera_id,
            state=state,
            status=self._derive_status(state, last_frame_age),
            frames_total=frames_total,
            frames_per_second=round(recent_frames / FPS_WINDOW_SECONDS, 2),
            last_frame_age_seconds=last_frame_age,
            reconnects_total=reconnects_total,
            consecutive_failures=consecutive_failures,
        )

    def _derive_status(self, state: CameraState, last_frame_age: float | None) -> HealthStatus:
        if state is CameraState.STREAMING:
            if last_frame_age is not None and last_frame_age > self._stale_frame_after:
                return HealthStatus.DEGRADED
            return HealthStatus.HEALTHY
        if state in (CameraState.CONNECTING, CameraState.RECONNECTING):
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY  # IDLE, FAILED, STOPPED

    # ------------------------------------------------------------ internals

    def _run(self) -> None:
        self._set_state(CameraState.CONNECTING)
        while not self._stop_event.is_set():
            stream = self._connect()
            if stream is None:
                continue  # backoff already applied inside _connect
            try:
                self._read_until_failure(stream)
            finally:
                self._close_quietly(stream)
        self._set_state(CameraState.STOPPED)

    def _connect(self) -> VideoStream | None:
        try:
            stream = self._stream_factory.open(self._camera)
        except CameraError as exc:
            self._on_connect_failure(exc)
            return None
        with self._lock:
            self._consecutive_failures = 0
        self._set_state(CameraState.STREAMING)
        logger.info(
            "camera %s: streaming from %s",
            self._camera.camera_id,
            self._camera.redacted_url,
        )
        return stream

    def _on_connect_failure(self, exc: CameraError) -> None:
        with self._lock:
            self._consecutive_failures += 1
            failures = self._consecutive_failures
        if failures >= self._retry_policy.failed_after_attempts:
            self._set_state(CameraState.FAILED)
        else:
            self._set_state(CameraState.RECONNECTING)
        delay = self._retry_policy.delay_for_attempt(failures)
        logger.warning(
            "camera %s: connect attempt %d failed (%s); retrying in %.1fs",
            self._camera.camera_id,
            failures,
            exc,
            delay,
        )
        self._stop_event.wait(delay)

    def _read_until_failure(self, stream: VideoStream) -> None:
        while not self._stop_event.is_set():
            if self._reconnect_event.is_set():
                self._reconnect_event.clear()
                self._begin_reconnect("stream recovery requested")
                return
            try:
                frame = stream.read()
            except CameraError as exc:
                self._begin_reconnect(f"read failed: {exc}")
                return
            self._record_frame()
            try:
                self._frame_consumer(frame)
            except Exception:
                logger.exception(
                    "camera %s: frame consumer raised; frame %d dropped",
                    self._camera.camera_id,
                    frame.sequence,
                )

    def _begin_reconnect(self, reason: str) -> None:
        with self._lock:
            self._reconnects_total += 1
        self._set_state(CameraState.RECONNECTING)
        logger.warning("camera %s: %s; reconnecting", self._camera.camera_id, reason)

    def _record_frame(self) -> None:
        now = self._clock()
        with self._lock:
            self._frames_total += 1
            self._last_frame_at = now
            self._frame_times.append(now)
            cutoff = now - FPS_WINDOW_SECONDS
            while self._frame_times and self._frame_times[0] < cutoff:
                self._frame_times.popleft()

    def _close_quietly(self, stream: VideoStream) -> None:
        try:
            stream.close()
        except Exception:
            logger.exception("camera %s: error while closing stream", self._camera.camera_id)

    def _set_state(self, new_state: CameraState) -> None:
        with self._lock:
            old_state = self._state
            self._state = new_state
        if old_state is not new_state:
            logger.info(
                "camera %s: %s -> %s",
                self._camera.camera_id,
                old_state.value,
                new_state.value,
            )
