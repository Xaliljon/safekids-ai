"""Live vision demo: RTSP cameras -> YOLOX detections -> MJPEG in the browser.

Pure composition of existing components (nothing is bypassed):

    CameraService --FrameConsumer--> VisionPipeline --Detector port--> YOLOX
                                          |--DetectionConsumer--> log summary
                                          '--AnnotatedFrameConsumer--> MJPEG server

Usage:
    uv run python -m guardian_edge.tools.live_demo \
        --cameras edge/config/cameras.yaml --models models --port 8080

Then open http://127.0.0.1:8080/ in a browser. The server binds localhost
only — this is a development tool, not the device API.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.application.vision.ports import AnnotatedFrame
from guardian_edge.domain.detection import DetectionResult
from guardian_edge.infrastructure.camera.config import load_cameras
from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.tracking.bytetrack import ByteTracker
from guardian_edge.infrastructure.vision.overlay import OpenCvOverlayRenderer
from guardian_edge.infrastructure.vision.track_overlay import OpenCvTrackOverlayRenderer
from guardian_edge.infrastructure.vision.yolox import create_yolox_detector

logger = logging.getLogger("live_demo")

_STREAM_FPS = 10.0
_LOG_EVERY_N_RESULTS = 30


class LatestJpegStore:
    """Most recent annotated JPEG per camera; AnnotatedFrameConsumer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpegs: dict[str, bytes] = {}

    def __call__(self, annotated: AnnotatedFrame) -> None:
        ok, encoded = cv2.imencode(".jpg", annotated.image)
        if not ok:
            return
        with self._lock:
            self._jpegs[annotated.frame.camera_id] = encoded.tobytes()

    def get(self, camera_id: str) -> bytes | None:
        with self._lock:
            return self._jpegs.get(camera_id)

    def camera_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._jpegs)


class DetectionLogger:
    """DetectionConsumer: periodic one-line summaries, never frame spam."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def __call__(self, result: DetectionResult) -> None:
        count = self._counts.get(result.camera_id, 0) + 1
        self._counts[result.camera_id] = count
        if count % _LOG_EVERY_N_RESULTS == 1:
            summary = ", ".join(
                f"{detection.label} {detection.confidence:.0%}"
                for detection in result.detections[:5]
            )
            logger.info(
                "camera %s frame %d: %d detection(s) in %.1f ms%s",
                result.camera_id,
                result.frame_sequence,
                len(result.detections),
                result.inference_ms,
                f" [{summary}]" if summary else "",
            )


def _make_handler(store: LatestJpegStore) -> type[BaseHTTPRequestHandler]:
    class DemoHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/":
                self._index()
            elif self.path.startswith("/stream/"):
                self._stream(self.path.removeprefix("/stream/"))
            else:
                self.send_error(404)

        def _index(self) -> None:
            cameras = store.camera_ids()
            body = "<html><body><h1>Guardian AI — live vision demo</h1>"
            if cameras:
                body += "".join(
                    f'<h2>{camera_id}</h2><img src="/stream/{camera_id}" />'
                    for camera_id in cameras
                )
            else:
                body += "<p>No annotated frames yet — waiting for cameras…</p>"
            body += "</body></html>"
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _stream(self, camera_id: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    jpeg = store.get(camera_id)
                    if jpeg is not None:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(1.0 / _STREAM_FPS)
            except (BrokenPipeError, ConnectionResetError):
                return  # viewer closed the tab

        def log_message(self, *_args: object) -> None:
            return  # our logging, not http.server's

    return DemoHandler


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", type=Path, required=True, help="camera config YAML")
    parser.add_argument("--models", type=Path, default=Path("models"), help="model zoo root")
    parser.add_argument("--model", default="yolox-tiny", help="detection model name")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--confidence", type=float, default=None, help="threshold override")
    parser.add_argument(
        "--tracking", action="store_true", help="run ByteTrack and show persistent track ids"
    )
    args = parser.parse_args(argv)

    overrides = {} if args.confidence is None else {"confidence_threshold": args.confidence}
    detector = create_yolox_detector(
        FileSystemModelRegistry(args.models), model_name=args.model, **overrides
    )
    store = LatestJpegStore()
    tracker = ByteTracker() if args.tracking else None
    pipeline = VisionPipeline(
        detector=detector,
        detection_consumer=DetectionLogger(),
        overlay_renderer=None if args.tracking else OpenCvOverlayRenderer(),
        annotated_consumer=store,
        tracker=tracker,
        track_overlay_renderer=OpenCvTrackOverlayRenderer() if args.tracking else None,
    )
    service = CameraService(
        stream_factory=OpenCvRtspStreamFactory(),
        frame_consumer=pipeline.on_frame,
    )
    for camera in load_cameras(args.cameras):
        service.add_camera(camera)

    pipeline.start()
    service.start()
    server = ThreadingHTTPServer((args.host, args.port), _make_handler(store))
    logger.info(
        "model %s v%s live — open http://%s:%d/",
        detector.descriptor.name,
        detector.descriptor.version,
        args.host,
        args.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()
        service.stop()
        pipeline.stop()
        detector.close()
        for camera_id, stats in sorted(pipeline.stats().items()):
            logger.info(
                "camera %s: received=%d processed=%d dropped=%d fps=%.1f",
                camera_id,
                stats.frames_received,
                stats.frames_processed,
                stats.frames_dropped,
                stats.frames_per_second,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
