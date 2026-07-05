"""Camera entity validation and credential redaction."""

import pytest

from guardian_edge.domain.camera import Camera, CameraState
from guardian_edge.domain.errors import CameraConfigurationError


def make(url: str) -> Camera:
    return Camera(camera_id="cam-1", name="Cam", rtsp_url=url)


class TestCameraValidation:
    def test_accepts_valid_rtsp_url(self) -> None:
        camera = make("rtsp://192.0.2.10:554/stream1")
        assert camera.camera_id == "cam-1"

    def test_accepts_rtsps_scheme(self) -> None:
        assert make("rtsps://cam.local/stream").rtsp_url.startswith("rtsps://")

    @pytest.mark.parametrize("url", ["http://192.0.2.10/x", "not-a-url", "rtsp://", ""])
    def test_rejects_non_rtsp_urls(self, url: str) -> None:
        with pytest.raises(CameraConfigurationError):
            make(url)

    def test_rejects_malformed_port(self) -> None:
        with pytest.raises(CameraConfigurationError):
            make("rtsp://192.0.2.10:notaport/stream")

    def test_rejects_blank_camera_id(self) -> None:
        with pytest.raises(CameraConfigurationError):
            Camera(camera_id="   ", name="Cam", rtsp_url="rtsp://192.0.2.10/s")


class TestRedactedUrl:
    def test_masks_credentials(self) -> None:
        camera = make("rtsp://admin:hunter2@192.0.2.10:554/stream1")
        assert "hunter2" not in camera.redacted_url
        assert "admin" not in camera.redacted_url
        assert camera.redacted_url == "rtsp://***:***@192.0.2.10:554/stream1"

    def test_leaves_credential_free_url_unchanged(self) -> None:
        url = "rtsp://192.0.2.10:554/stream1"
        assert make(url).redacted_url == url


def test_camera_states_are_distinct() -> None:
    values = {state.value for state in CameraState}
    assert len(values) == len(CameraState)
