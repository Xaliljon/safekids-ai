"""OpenCV stream adapter (fake capture object; no real camera or network)."""

from typing import Any

import pytest
from camera_fakes import make_camera

from guardian_edge.domain.errors import CameraReadError
from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStream


class FakeImage:
    """Stands in for a numpy BGR array: only .shape is consumed."""

    shape = (480, 640, 3)


class FakeCapture:
    def __init__(self, results: list[tuple[bool, Any]]) -> None:
        self._results = results
        self.released = False

    def read(self) -> tuple[bool, Any]:
        return self._results.pop(0)

    def release(self) -> None:
        self.released = True


def test_wraps_images_into_frames_with_metadata() -> None:
    camera = make_camera()
    stream = OpenCvRtspStream(camera, FakeCapture([(True, FakeImage()), (True, FakeImage())]))
    first = stream.read()
    second = stream.read()
    assert first.camera_id == camera.camera_id
    assert (first.width, first.height) == (640, 480)
    assert (first.sequence, second.sequence) == (1, 2)
    assert first.captured_at.tzinfo is not None, "timestamps must be timezone-aware"
    assert isinstance(first.data, FakeImage)


def test_failed_read_raises_camera_read_error() -> None:
    stream = OpenCvRtspStream(make_camera(), FakeCapture([(False, None)]))
    with pytest.raises(CameraReadError):
        stream.read()


def test_close_releases_capture() -> None:
    capture = FakeCapture([])
    stream = OpenCvRtspStream(make_camera(), capture)
    stream.close()
    assert capture.released
