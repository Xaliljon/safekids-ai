"""The vision pipeline: frames in, detection results out.

Attaches to the camera service as a plain FrameConsumer (``on_frame``) —
capture knows nothing about AI. Inference runs on the pipeline's own worker
thread so a slow detector can never block capture threads.

Frame handoff is latest-frame-wins per camera (ADR-0006): each camera has a
one-slot mailbox where a newer frame replaces an unprocessed older one.
Real-time safety monitoring must analyze the present, not work through a
backlog — frames are dropped by design and the drops are counted, never
silent (docs/03: no silent caps).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from guardian_edge.application.vision.ports import (
    AnnotatedFrame,
    AnnotatedFrameConsumer,
    DetectionConsumer,
    Detector,
    OverlayRenderer,
)
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame

logger = logging.getLogger(__name__)

FPS_WINDOW_SECONDS = 10.0
_IDLE_WAIT_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class PipelineStats:
    """Point-in-time processing statistics for one camera."""

    camera_id: str
    frames_received: int
    frames_processed: int
    frames_dropped: int
    detector_errors: int
    frames_per_second: float


class _CameraCounters:
    """Mutable per-camera counters; guarded by the pipeline lock."""

    __slots__ = ("dropped", "errors", "processed", "processed_times", "received")

    def __init__(self) -> None:
        self.received = 0
        self.processed = 0
        self.dropped = 0
        self.errors = 0
        self.processed_times: deque[float] = deque()


class VisionPipeline:
    """Runs a Detector over the freshest frame of each camera.

    ``on_frame`` satisfies the camera service's FrameConsumer contract: it
    only stores the frame and returns — capture threads never wait on
    inference. One worker thread serializes detector calls (edge boxes have
    one accelerator; ADR-0006).

    A failing detector, detection consumer, or overlay consumer is logged
    and counted but never stops the pipeline.
    """

    def __init__(
        self,
        detector: Detector,
        detection_consumer: DetectionConsumer,
        overlay_renderer: OverlayRenderer | None = None,
        annotated_consumer: AnnotatedFrameConsumer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (overlay_renderer is None) != (annotated_consumer is None):
            raise VisionConfigurationError(
                "overlay_renderer and annotated_consumer must be provided together"
            )
        self._detector = detector
        self._detection_consumer = detection_consumer
        self._overlay_renderer = overlay_renderer
        self._annotated_consumer = annotated_consumer
        self._clock = clock

        self._lock = threading.Lock()
        self._pending: dict[str, Frame] = {}
        self._counters: dict[str, _CameraCounters] = {}

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

    # ------------------------------------------------------- frame intake

    def on_frame(self, frame: Frame) -> None:
        """FrameConsumer entry point: store the freshest frame, never block."""
        with self._lock:
            counters = self._counters_for(frame.camera_id)
            counters.received += 1
            if frame.camera_id in self._pending:
                counters.dropped += 1
            self._pending[frame.camera_id] = frame
        self._wake_event.set()

    # ---------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the inference worker thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="vision-pipeline", daemon=True)
        self._thread.start()

    def stop(self, join_timeout_seconds: float = 15.0) -> None:
        """Stop the worker thread. Idempotent; pending frames are discarded."""
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout_seconds)
            if thread.is_alive():
                logger.warning(
                    "vision pipeline thread did not stop within %.1fs", join_timeout_seconds
                )
        self._thread = None

    # ----------------------------------------------------------- processing

    def process_once(self) -> bool:
        """Process one pending camera's frame; False when nothing is pending.

        Public so tests (and callers that manage their own scheduling) can
        drive the pipeline deterministically without the worker thread.
        """
        frame = self._take_pending()
        if frame is None:
            return False
        self._process(frame)
        return True

    def stats(self) -> dict[str, PipelineStats]:
        """Processing statistics per camera."""
        now = self._clock()
        with self._lock:
            return {
                camera_id: PipelineStats(
                    camera_id=camera_id,
                    frames_received=c.received,
                    frames_processed=c.processed,
                    frames_dropped=c.dropped,
                    detector_errors=c.errors,
                    frames_per_second=round(
                        sum(1 for t in c.processed_times if t >= now - FPS_WINDOW_SECONDS)
                        / FPS_WINDOW_SECONDS,
                        2,
                    ),
                )
                for camera_id, c in self._counters.items()
            }

    # ------------------------------------------------------------ internals

    def _counters_for(self, camera_id: str) -> _CameraCounters:
        counters = self._counters.get(camera_id)
        if counters is None:
            counters = _CameraCounters()
            self._counters[camera_id] = counters
        return counters

    def _take_pending(self) -> Frame | None:
        with self._lock:
            if not self._pending:
                return None
            camera_id = next(iter(self._pending))  # oldest-registered camera first
            return self._pending.pop(camera_id)

    def _process(self, frame: Frame) -> None:
        try:
            result = self._detector.detect(frame)
        except Exception:
            with self._lock:
                self._counters_for(frame.camera_id).errors += 1
            logger.exception(
                "camera %s: detector failed on frame %d; frame skipped",
                frame.camera_id,
                frame.sequence,
            )
            return

        fps = self._record_processed(frame.camera_id)

        try:
            self._detection_consumer(result)
        except Exception:
            logger.exception(
                "camera %s: detection consumer raised; result %d dropped",
                frame.camera_id,
                frame.sequence,
            )

        if self._overlay_renderer is not None and self._annotated_consumer is not None:
            try:
                image = self._overlay_renderer.render(frame, result, fps)
                self._annotated_consumer(AnnotatedFrame(frame=frame, result=result, image=image))
            except Exception:
                logger.exception(
                    "camera %s: overlay rendering/consumer raised; annotation %d dropped",
                    frame.camera_id,
                    frame.sequence,
                )

    def _record_processed(self, camera_id: str) -> float:
        now = self._clock()
        with self._lock:
            counters = self._counters_for(camera_id)
            counters.processed += 1
            counters.processed_times.append(now)
            cutoff = now - FPS_WINDOW_SECONDS
            while counters.processed_times and counters.processed_times[0] < cutoff:
                counters.processed_times.popleft()
            return len(counters.processed_times) / FPS_WINDOW_SECONDS

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self.process_once():
                self._wake_event.wait(_IDLE_WAIT_SECONDS)
                self._wake_event.clear()
