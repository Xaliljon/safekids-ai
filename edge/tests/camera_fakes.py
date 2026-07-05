"""Test doubles for the camera application layer."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

from guardian_edge.domain.camera import Camera
from guardian_edge.domain.errors import CameraConnectionError
from guardian_edge.domain.frame import Frame

FRAME = "frame"
"""Script marker: produce one frame."""


def make_camera(camera_id: str = "cam-1") -> Camera:
    return Camera(
        camera_id=camera_id,
        name=f"Test camera {camera_id}",
        rtsp_url=f"rtsp://user:secret@192.0.2.10:554/{camera_id}",
        location="Classroom 1",
    )


def make_frame(camera_id: str, sequence: int) -> Frame:
    return Frame(
        camera_id=camera_id,
        sequence=sequence,
        captured_at=datetime.now(tz=timezone.utc),
        width=2,
        height=2,
        data=object(),
    )


class ScriptedStream:
    """VideoStream fake driven by a script.

    Script items are either FRAME (produce a frame) or an exception instance
    (raise it). Once the script is exhausted the stream produces frames
    forever, pacing them by ``frame_interval`` so tests never busy-spin.
    """

    def __init__(
        self,
        camera: Camera,
        script: list[object] | None = None,
        frame_interval: float = 0.001,
    ) -> None:
        self._camera = camera
        self._script: Iterator[object] = iter(script or [])
        self._frame_interval = frame_interval
        self._sequence = 0
        self.closed = threading.Event()

    def read(self) -> Frame:
        time.sleep(self._frame_interval)
        item = next(self._script, FRAME)
        if isinstance(item, Exception):
            raise item
        self._sequence += 1
        return make_frame(self._camera.camera_id, self._sequence)

    def close(self) -> None:
        self.closed.set()


class ScriptedStreamFactory:
    """VideoStreamFactory fake.

    Fails the first ``fail_first`` open() calls with CameraConnectionError,
    then opens ScriptedStreams, consuming ``scripts`` in order (an exhausted
    scripts list yields default frames-forever streams).
    """

    def __init__(self, fail_first: int = 0, scripts: list[list[object]] | None = None) -> None:
        self._fail_remaining = fail_first
        self._scripts = list(scripts or [])
        self._lock = threading.Lock()
        self.open_calls = 0
        self.streams: list[ScriptedStream] = []

    def open(self, camera: Camera) -> ScriptedStream:
        with self._lock:
            self.open_calls += 1
            if self._fail_remaining > 0:
                self._fail_remaining -= 1
                raise CameraConnectionError(
                    f"camera '{camera.camera_id}': simulated connect failure"
                )
            script = self._scripts.pop(0) if self._scripts else None
            stream = ScriptedStream(camera, script)
            self.streams.append(stream)
            return stream


def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 5.0,
    interval: float = 0.005,
) -> bool:
    """Poll until the predicate holds or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
