"""Record a sprint demo video: live RTSP -> detections -> annotated MP4.

Every sprint ends with a ~30-second demo clip published to GitHub Releases
(Sprint-NN-Topic.mp4) — six months of these is a ready-made investor reel.

Pure composition of existing components, exactly like live_demo: the
recorder is just another AnnotatedFrameConsumer.

Usage:
    uv run python -m guardian_edge.tools.record_demo \
        --cameras edge/config/cameras.yaml --models models \
        --duration 30 --output Sprint-08-YOLOX.mp4

The output uses the mp4v codec (what OpenCV ships); transcode to H.264
for web playback, e.g.:
    ffmpeg -i raw.mp4 -c:v libx264 -pix_fmt yuv420p -movflags +faststart out.mp4
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
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

logger = logging.getLogger("record_demo")

_FIRST_FRAME_TIMEOUT_SECONDS = 60.0


class Mp4Recorder:
    """AnnotatedFrameConsumer writing one camera's overlay frames to MP4."""

    def __init__(self, output: Path, camera_id: str | None, fps: float) -> None:
        self._output = output
        self._camera_id = camera_id
        self._fps = fps
        self._writer: cv2.VideoWriter | None = None
        self._lock = threading.Lock()
        self.frames_written = 0
        self.first_frame = threading.Event()

    def __call__(self, annotated: AnnotatedFrame) -> None:
        if self._camera_id is not None and annotated.frame.camera_id != self._camera_id:
            return
        image = annotated.image
        with self._lock:
            if self._writer is None:
                height, width = image.shape[:2]
                self._writer = cv2.VideoWriter(
                    str(self._output),
                    cv2.VideoWriter.fourcc(*"mp4v"),
                    self._fps,
                    (width, height),
                )
                logger.info(
                    "recording %dx%d @ %.0f fps -> %s", width, height, self._fps, self._output
                )
            self._writer.write(image)
            self.frames_written += 1
        self.first_frame.set()

    def close(self) -> None:
        with self._lock:
            if self._writer is not None:
                self._writer.release()
                self._writer = None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", type=Path, required=True, help="camera config YAML")
    parser.add_argument("--models", type=Path, default=Path("models"), help="model zoo root")
    parser.add_argument("--model", default="yolox-tiny", help="detection model name")
    parser.add_argument("--camera", default=None, help="camera id to record (default: all/first)")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to record")
    parser.add_argument("--fps", type=float, default=10.0, help="output video frame rate")
    parser.add_argument("--output", type=Path, required=True, help="output .mp4 path")
    parser.add_argument("--confidence", type=float, default=None, help="threshold override")
    parser.add_argument(
        "--tracking", action="store_true", help="run ByteTrack and record persistent track ids"
    )
    args = parser.parse_args(argv)

    overrides = {} if args.confidence is None else {"confidence_threshold": args.confidence}
    detector = create_yolox_detector(
        FileSystemModelRegistry(args.models), model_name=args.model, **overrides
    )
    recorder = Mp4Recorder(args.output, camera_id=args.camera, fps=args.fps)
    detections_seen = [0]

    def count_detections(result: DetectionResult) -> None:
        detections_seen[0] += len(result.detections)

    pipeline = VisionPipeline(
        detector=detector,
        detection_consumer=count_detections,
        overlay_renderer=None if args.tracking else OpenCvOverlayRenderer(),
        annotated_consumer=recorder,
        tracker=ByteTracker() if args.tracking else None,
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
    try:
        if not recorder.first_frame.wait(timeout=_FIRST_FRAME_TIMEOUT_SECONDS):
            logger.error(
                "no annotated frames within %.0fs — is the camera up?", _FIRST_FRAME_TIMEOUT_SECONDS
            )
            return 1
        logger.info("first frame received; recording %.0fs", args.duration)
        time.sleep(args.duration)
    finally:
        service.stop()
        pipeline.stop()
        recorder.close()
        detector.close()
    logger.info(
        "wrote %d frames (%d detections total) to %s",
        recorder.frames_written,
        detections_seen[0],
        args.output,
    )
    return 0 if recorder.frames_written > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
