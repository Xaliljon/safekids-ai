"""OpenCV/FFmpeg implementation of the VideoStream port for RTSP cameras."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import cv2

from guardian_edge.domain.camera import Camera
from guardian_edge.domain.errors import CameraConnectionError, CameraReadError
from guardian_edge.domain.frame import Frame

DEFAULT_OPEN_TIMEOUT_MS = 10_000
DEFAULT_READ_TIMEOUT_MS = 10_000


class SupportsCapture(Protocol):
    """The slice of cv2.VideoCapture this adapter needs (kept narrow for tests)."""

    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...


class OpenCvRtspStream:
    """One open RTSP stream. Not thread-safe; owned by a single CaptureSession."""

    def __init__(self, camera: Camera, capture: SupportsCapture) -> None:
        self._camera = camera
        self._capture = capture
        self._sequence = 0

    def read(self) -> Frame:
        """Read the next frame; bounded by the FFmpeg read timeout."""
        ok, image = self._capture.read()
        if not ok or image is None:
            raise CameraReadError(f"camera '{self._camera.camera_id}': stream returned no frame")
        height, width = image.shape[:2]
        self._sequence += 1
        return Frame(
            camera_id=self._camera.camera_id,
            sequence=self._sequence,
            captured_at=datetime.now(tz=timezone.utc),
            width=int(width),
            height=int(height),
            data=image,
        )

    def close(self) -> None:
        self._capture.release()


class OpenCvRtspStreamFactory:
    """Opens RTSP streams via FFmpeg with open/read timeouts.

    The timeouts are what guarantee a dead camera can never block a capture
    thread forever — the capture loop's recovery logic depends on them.
    """

    def __init__(
        self,
        open_timeout_ms: int = DEFAULT_OPEN_TIMEOUT_MS,
        read_timeout_ms: int = DEFAULT_READ_TIMEOUT_MS,
    ) -> None:
        self._open_timeout_ms = open_timeout_ms
        self._read_timeout_ms = read_timeout_ms

    def open(self, camera: Camera) -> OpenCvRtspStream:
        capture = cv2.VideoCapture(
            camera.rtsp_url,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                self._open_timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                self._read_timeout_ms,
            ],
        )
        if not capture.isOpened():
            capture.release()
            # Redacted URL only — credentials never reach logs or errors.
            raise CameraConnectionError(
                f"camera '{camera.camera_id}': could not open {camera.redacted_url}"
            )
        return OpenCvRtspStream(camera, capture)
