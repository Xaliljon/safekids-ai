"""Health monitor: stall detection, status-change notifications, resilience."""

from camera_fakes import wait_until

from guardian_edge.application.health_monitor import HealthMonitor
from guardian_edge.domain.camera import CameraState
from guardian_edge.domain.health import CameraHealth, HealthStatus


def make_health(
    camera_id: str = "cam-1",
    state: CameraState = CameraState.STREAMING,
    status: HealthStatus = HealthStatus.HEALTHY,
    last_frame_age_seconds: float | None = 0.1,
) -> CameraHealth:
    return CameraHealth(
        camera_id=camera_id,
        state=state,
        status=status,
        frames_total=100,
        frames_per_second=25.0,
        last_frame_age_seconds=last_frame_age_seconds,
        reconnects_total=0,
        consecutive_failures=0,
    )


class Collector:
    def __init__(self) -> None:
        self.stalled: list[str] = []
        self.notified: list[CameraHealth] = []

    def on_stall(self, camera_id: str) -> None:
        self.stalled.append(camera_id)

    def on_status(self, health: CameraHealth) -> None:
        self.notified.append(health)


def test_requests_recovery_for_stale_streaming_camera() -> None:
    collector = Collector()
    stale = make_health(status=HealthStatus.DEGRADED, last_frame_age_seconds=99.0)
    monitor = HealthMonitor(
        health_provider=lambda: {"cam-1": stale},
        stall_handler=collector.on_stall,
        stale_frame_after_seconds=10.0,
    )
    monitor.check_once()
    assert collector.stalled == ["cam-1"]


def test_does_not_touch_healthy_or_reconnecting_cameras() -> None:
    collector = Collector()
    report = {
        "fresh": make_health("fresh", last_frame_age_seconds=0.5),
        "reconnecting": make_health(
            "reconnecting",
            state=CameraState.RECONNECTING,
            status=HealthStatus.DEGRADED,
            last_frame_age_seconds=99.0,
        ),
        "never-streamed": make_health("never-streamed", last_frame_age_seconds=None),
    }
    monitor = HealthMonitor(
        health_provider=lambda: report,
        stall_handler=collector.on_stall,
        stale_frame_after_seconds=10.0,
    )
    monitor.check_once()
    assert collector.stalled == []


def test_notifies_listener_only_on_status_change() -> None:
    collector = Collector()
    current = {"cam-1": make_health()}
    monitor = HealthMonitor(
        health_provider=lambda: current,
        stall_handler=collector.on_stall,
        status_listener=collector.on_status,
    )
    monitor.check_once()
    monitor.check_once()
    assert [h.status for h in collector.notified] == [HealthStatus.HEALTHY]

    current["cam-1"] = make_health(status=HealthStatus.DEGRADED)
    monitor.check_once()
    assert [h.status for h in collector.notified] == [
        HealthStatus.HEALTHY,
        HealthStatus.DEGRADED,
    ]


def test_removed_camera_is_forgotten_and_renotified_on_return() -> None:
    collector = Collector()
    current: dict[str, CameraHealth] = {"cam-1": make_health()}
    monitor = HealthMonitor(
        health_provider=lambda: current,
        stall_handler=collector.on_stall,
        status_listener=collector.on_status,
    )
    monitor.check_once()
    current.clear()
    monitor.check_once()
    current["cam-1"] = make_health()
    monitor.check_once()
    assert len(collector.notified) == 2, "re-added camera must notify again"


def test_listener_exception_does_not_break_monitoring() -> None:
    def broken_listener(_health: CameraHealth) -> None:
        raise RuntimeError("listener bug")

    stalled: list[str] = []
    stale = make_health(status=HealthStatus.DEGRADED, last_frame_age_seconds=99.0)
    monitor = HealthMonitor(
        health_provider=lambda: {"cam-1": stale},
        stall_handler=stalled.append,
        status_listener=broken_listener,
        stale_frame_after_seconds=10.0,
    )
    monitor.check_once()
    assert stalled == ["cam-1"], "stall handling must survive a broken listener"


def test_periodic_checking_runs_and_stops() -> None:
    calls: list[int] = []

    def provider() -> dict[str, CameraHealth]:
        calls.append(1)
        return {}

    monitor = HealthMonitor(
        health_provider=provider,
        stall_handler=lambda _cid: None,
        check_interval_seconds=0.01,
    )
    monitor.start()
    monitor.start()  # idempotent
    assert wait_until(lambda: len(calls) >= 3)
    monitor.stop()
    monitor.stop()  # idempotent
    settled = len(calls)
    assert not wait_until(lambda: len(calls) > settled + 1, timeout=0.1)
