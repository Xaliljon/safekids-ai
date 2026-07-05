"""Capture session: frame delivery, recovery, and lifecycle."""

from camera_fakes import FRAME, ScriptedStreamFactory, make_camera, wait_until

from guardian_edge.application.capture_session import CaptureSession
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.camera import CameraState
from guardian_edge.domain.errors import CameraReadError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.health import HealthStatus


def fast_policy(failed_after: int = 3) -> RetryPolicy:
    return RetryPolicy(
        initial_delay_seconds=0.01,
        multiplier=2.0,
        max_delay_seconds=0.02,
        failed_after_attempts=failed_after,
    )


def make_session(
    factory: ScriptedStreamFactory,
    frames: list[Frame],
    failed_after: int = 3,
) -> CaptureSession:
    return CaptureSession(
        camera=make_camera(),
        stream_factory=factory,
        frame_consumer=frames.append,
        retry_policy=fast_policy(failed_after),
    )


def test_delivers_frames_to_consumer() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    session = make_session(factory, frames)
    session.start()
    try:
        assert wait_until(lambda: len(frames) >= 5)
        health = session.health()
        assert health.state is CameraState.STREAMING
        assert health.status is HealthStatus.HEALTHY
        assert health.frames_total >= 5
        assert frames[0].camera_id == "cam-1"
    finally:
        session.stop()


def test_recovers_after_read_failure() -> None:
    factory = ScriptedStreamFactory(
        scripts=[[FRAME, FRAME, CameraReadError("simulated stall")]],
    )
    frames: list[Frame] = []
    session = make_session(factory, frames)
    session.start()
    try:
        assert wait_until(lambda: len(frames) >= 5)
        health = session.health()
        assert health.reconnects_total == 1
        assert factory.open_calls == 2
        assert factory.streams[0].closed.is_set(), "failed stream must be released"
    finally:
        session.stop()


def test_reports_failed_after_repeated_connect_failures() -> None:
    factory = ScriptedStreamFactory(fail_first=100)
    frames: list[Frame] = []
    session = make_session(factory, frames, failed_after=3)
    session.start()
    try:
        assert wait_until(lambda: session.health().consecutive_failures >= 3)
        health = session.health()
        assert health.state is CameraState.FAILED
        assert health.status is HealthStatus.UNHEALTHY
        assert frames == []
    finally:
        session.stop()


def test_keeps_retrying_and_recovers_when_camera_returns() -> None:
    factory = ScriptedStreamFactory(fail_first=5)
    frames: list[Frame] = []
    session = make_session(factory, frames, failed_after=3)
    session.start()
    try:
        # Passes through FAILED (5 > 3 failures), then the camera "comes back".
        assert wait_until(lambda: len(frames) >= 1)
        health = session.health()
        assert health.state is CameraState.STREAMING
        assert health.consecutive_failures == 0
        assert factory.open_calls == 6
    finally:
        session.stop()


def test_consumer_exception_does_not_stop_capture() -> None:
    received: list[Frame] = []

    def flaky_consumer(frame: Frame) -> None:
        if frame.sequence <= 2:
            raise ValueError("consumer bug")
        received.append(frame)

    session = CaptureSession(
        camera=make_camera(),
        stream_factory=ScriptedStreamFactory(),
        frame_consumer=flaky_consumer,
        retry_policy=fast_policy(),
    )
    session.start()
    try:
        assert wait_until(lambda: len(received) >= 3)
        health = session.health()
        assert health.reconnects_total == 0
        assert health.frames_total >= 5  # dropped frames still counted as captured
    finally:
        session.stop()


def test_request_reconnect_reopens_stream() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    session = make_session(factory, frames)
    session.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        session.request_reconnect()
        assert wait_until(lambda: factory.open_calls == 2)
        before = len(frames)
        assert wait_until(lambda: len(frames) > before), "frames must continue after recovery"
        assert factory.streams[0].closed.is_set()
        assert session.health().reconnects_total == 1
    finally:
        session.stop()


def test_stop_is_clean_and_idempotent() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    session = make_session(factory, frames)
    session.start()
    assert wait_until(lambda: len(frames) >= 1)
    session.stop()
    session.stop()
    health = session.health()
    assert health.state is CameraState.STOPPED
    assert health.status is HealthStatus.UNHEALTHY
    assert factory.streams[-1].closed.is_set(), "stream must be released on stop"


def test_start_is_idempotent() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    session = make_session(factory, frames)
    session.start()
    session.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        assert factory.open_calls == 1
    finally:
        session.stop()


def test_health_before_start_is_idle_and_unhealthy() -> None:
    session = make_session(ScriptedStreamFactory(), [])
    health = session.health()
    assert health.state is CameraState.IDLE
    assert health.status is HealthStatus.UNHEALTHY
    assert health.frames_total == 0
    assert health.last_frame_age_seconds is None


def test_stale_stream_reports_degraded() -> None:
    clock_now = [100.0]
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    session = CaptureSession(
        camera=make_camera(),
        stream_factory=factory,
        frame_consumer=frames.append,
        retry_policy=fast_policy(),
        stale_frame_after_seconds=10.0,
        clock=lambda: clock_now[0],
    )
    session.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        clock_now[0] += 60.0  # a minute passes with the injected clock
        health = session.health()
        assert health.status is HealthStatus.DEGRADED
        assert health.last_frame_age_seconds is not None
        assert health.last_frame_age_seconds >= 10.0
    finally:
        session.stop()
