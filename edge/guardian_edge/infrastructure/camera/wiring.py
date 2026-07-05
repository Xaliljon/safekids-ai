"""Production wiring for the Edge Camera Service.

The composition point where infrastructure implementations meet the
application layer. The future runtime supervisor calls this; tests wire
their own fakes directly.
"""

from __future__ import annotations

from pathlib import Path

from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.health_monitor import StatusListener
from guardian_edge.application.ports import FrameConsumer
from guardian_edge.infrastructure.camera.config import load_cameras
from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory


def create_camera_service(
    config_path: Path,
    frame_consumer: FrameConsumer,
    status_listener: StatusListener | None = None,
) -> CameraService:
    """Build a CameraService from a config file, using the OpenCV RTSP backend.

    The service is returned registered but not started; the caller decides
    when capture begins (``service.start()``).
    """
    service = CameraService(
        stream_factory=OpenCvRtspStreamFactory(),
        frame_consumer=frame_consumer,
        status_listener=status_listener,
    )
    for camera in load_cameras(config_path):
        service.add_camera(camera)
    return service
