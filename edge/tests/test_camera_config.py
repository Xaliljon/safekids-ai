"""Camera configuration loading and environment expansion."""

from pathlib import Path

import pytest

from guardian_edge.domain.errors import CameraConfigurationError
from guardian_edge.infrastructure.camera.config import load_cameras

VALID_CONFIG = """\
cameras:
  - id: classroom-1-cam-1
    name: "Classroom 1"
    location: "Classroom 1"
    rtsp_url: "rtsp://${TEST_CAM_USER}:${TEST_CAM_PASSWORD}@192.168.10.11:554/stream1"
  - id: playground-cam-1
    name: "Playground"
    rtsp_url: "rtsp://192.168.10.12:554/stream1"
"""


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "cameras.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_cameras_with_env_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CAM_USER", "svc-account")
    monkeypatch.setenv("TEST_CAM_PASSWORD", "s3cret")
    cameras = load_cameras(write_config(tmp_path, VALID_CONFIG))
    assert [camera.camera_id for camera in cameras] == ["classroom-1-cam-1", "playground-cam-1"]
    assert cameras[0].rtsp_url == "rtsp://svc-account:s3cret@192.168.10.11:554/stream1"
    assert cameras[0].location == "Classroom 1"
    assert cameras[1].location == ""


def test_missing_environment_variable_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CAM_USER", "svc-account")
    monkeypatch.delenv("TEST_CAM_PASSWORD", raising=False)
    with pytest.raises(CameraConfigurationError, match="TEST_CAM_PASSWORD"):
        load_cameras(write_config(tmp_path, VALID_CONFIG))


def test_missing_file_raises_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(CameraConfigurationError, match="cannot read"):
        load_cameras(tmp_path / "nope.yaml")


def test_invalid_yaml_raises_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(CameraConfigurationError, match="not valid YAML"):
        load_cameras(write_config(tmp_path, "cameras: [unclosed"))


def test_missing_cameras_key_raises(tmp_path: Path) -> None:
    with pytest.raises(CameraConfigurationError, match="'cameras' list"):
        load_cameras(write_config(tmp_path, "other: 1"))


def test_missing_required_field_raises(tmp_path: Path) -> None:
    config = "cameras:\n  - id: cam-1\n    name: Cam\n"
    with pytest.raises(CameraConfigurationError, match="rtsp_url"):
        load_cameras(write_config(tmp_path, config))


def test_duplicate_camera_id_raises(tmp_path: Path) -> None:
    config = (
        "cameras:\n"
        "  - {id: cam-1, name: A, rtsp_url: 'rtsp://192.168.10.11/s'}\n"
        "  - {id: cam-1, name: B, rtsp_url: 'rtsp://192.168.10.12/s'}\n"
    )
    with pytest.raises(CameraConfigurationError, match="duplicates"):
        load_cameras(write_config(tmp_path, config))


def test_invalid_rtsp_url_raises(tmp_path: Path) -> None:
    config = "cameras:\n  - {id: cam-1, name: A, rtsp_url: 'http://192.168.10.11/s'}\n"
    with pytest.raises(CameraConfigurationError, match="rtsp"):
        load_cameras(write_config(tmp_path, config))
