"""Production wiring: config file -> registered (not started) CameraService."""

from pathlib import Path

from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.camera.wiring import create_camera_service


def test_builds_registered_but_unstarted_service(tmp_path: Path) -> None:
    config = tmp_path / "cameras.yaml"
    config.write_text(
        "cameras:\n"
        "  - {id: cam-1, name: A, rtsp_url: 'rtsp://192.168.10.11:554/s'}\n"
        "  - {id: cam-2, name: B, rtsp_url: 'rtsp://192.168.10.12:554/s'}\n",
        encoding="utf-8",
    )
    frames: list[Frame] = []
    service = create_camera_service(config, frames.append)
    assert {camera.camera_id for camera in service.cameras()} == {"cam-1", "cam-2"}
    report = service.health_report()
    assert all(health.frames_total == 0 for health in report.values())
    assert frames == [], "service must not start capturing until start() is called"
