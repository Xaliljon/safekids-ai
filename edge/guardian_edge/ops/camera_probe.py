"""Camera probing for the setup wizard: connection, resolution, FPS.

No AI involved — a probe opens the stream through the existing camera
infrastructure, reads frames for a bounded time, and measures what the
installer needs to know before saving a configuration.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from guardian_edge.application.ports import VideoStreamFactory
from guardian_edge.domain.camera import Camera
from guardian_edge.domain.errors import CameraError

DEFAULT_PROBE_FRAMES = 30


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What the wizard learned about one camera."""

    ok: bool
    frames_read: int
    width: int | None = None
    height: int | None = None
    measured_fps: float | None = None
    error: str | None = None


def probe_camera(
    factory: VideoStreamFactory,
    camera: Camera,
    frames: int = DEFAULT_PROBE_FRAMES,
    clock: Callable[[], float] = time.monotonic,
) -> ProbeResult:
    """Open the stream, read ``frames`` frames, measure resolution and FPS."""
    try:
        stream = factory.open(camera)
    except CameraError as exc:
        return ProbeResult(ok=False, frames_read=0, error=str(exc))
    width = height = None
    read = 0
    started = clock()
    try:
        for _ in range(frames):
            frame = stream.read()
            width, height = frame.width, frame.height
            read += 1
    except CameraError as exc:
        if read == 0:
            return ProbeResult(ok=False, frames_read=0, error=str(exc))
    finally:
        stream.close()
    elapsed = clock() - started
    fps = round(read / elapsed, 1) if elapsed > 0 and read > 1 else None
    return ProbeResult(
        ok=read > 0,
        frames_read=read,
        width=width,
        height=height,
        measured_fps=fps,
        error=None if read > 0 else "stream opened but produced no frames",
    )
