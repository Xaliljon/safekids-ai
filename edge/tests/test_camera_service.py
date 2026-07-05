"""Camera service facade: registration, lifecycle, health aggregation."""

import pytest
from camera_fakes import ScriptedStreamFactory, make_camera, wait_until

from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.camera import CameraState
from guardian_edge.domain.errors import CameraConfigurationError
from guardian_edge.domain.frame import Frame


def make_service(factory: ScriptedStreamFactory, frames: list[Frame]) -> CameraService:
    return CameraService(
        stream_factory=factory,
        frame_consumer=frames.append,
        retry_policy=RetryPolicy(initial_delay_seconds=0.01, max_delay_seconds=0.02),
        health_check_interval_seconds=0.05,
    )


def test_captures_from_all_registered_cameras() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    service = make_service(factory, frames)
    service.add_camera(make_camera("cam-1"))
    service.add_camera(make_camera("cam-2"))
    service.start()
    try:
        assert wait_until(
            lambda: {frame.camera_id for frame in frames} == {"cam-1", "cam-2"},
        )
        report = service.health_report()
        assert set(report) == {"cam-1", "cam-2"}
        assert all(h.state is CameraState.STREAMING for h in report.values())
    finally:
        service.stop()


def test_rejects_duplicate_camera_id() -> None:
    service = make_service(ScriptedStreamFactory(), [])
    service.add_camera(make_camera("cam-1"))
    with pytest.raises(CameraConfigurationError):
        service.add_camera(make_camera("cam-1"))


def test_remove_unknown_camera_raises() -> None:
    service = make_service(ScriptedStreamFactory(), [])
    with pytest.raises(CameraConfigurationError):
        service.remove_camera("ghost")


def test_camera_added_while_running_starts_capturing() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    service = make_service(factory, frames)
    service.start()
    try:
        service.add_camera(make_camera("late-cam"))
        assert wait_until(lambda: any(f.camera_id == "late-cam" for f in frames))
    finally:
        service.stop()


def test_removed_camera_stops_capturing() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    service = make_service(factory, frames)
    service.add_camera(make_camera("cam-1"))
    service.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        service.remove_camera("cam-1")
        assert factory.streams[-1].closed.is_set()
        assert service.health_report() == {}
        assert service.cameras() == []
    finally:
        service.stop()


def test_stop_stops_everything() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    service = make_service(factory, frames)
    service.add_camera(make_camera("cam-1"))
    service.add_camera(make_camera("cam-2"))
    service.start()
    assert wait_until(lambda: len(frames) >= 2)
    service.stop()
    report = service.health_report()
    assert all(h.state is CameraState.STOPPED for h in report.values())
    assert all(stream.closed.is_set() for stream in factory.streams)


def test_start_is_idempotent() -> None:
    factory = ScriptedStreamFactory()
    frames: list[Frame] = []
    service = make_service(factory, frames)
    service.add_camera(make_camera("cam-1"))
    service.start()
    service.start()
    try:
        assert wait_until(lambda: len(frames) >= 1)
        assert factory.open_calls == 1
    finally:
        service.stop()
