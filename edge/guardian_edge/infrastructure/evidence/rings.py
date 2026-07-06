"""Circular in-memory buffers feeding evidence clips (ADR-0017).

FrameRingBuffer keeps the last N seconds of video per camera as JPEG bytes.
TrackRingBuffer keeps the matching tracker conclusions per frame. Both are
RAM-only and continuously overwrite themselves — there is no continuous
recording anywhere; an incident is the only thing that turns a slice of
these rings into a file.

Hot-path guarantee: ``on_frame``/``on_tracking`` never block and never do
heavy work. Frames are handed to an encoder thread through a bounded
queue; when the encoder falls behind, the OLDEST queued frame is dropped
(a slightly sparser clip beats added AI latency, docs/03 performance).
"""

from __future__ import annotations

import logging
import queue
import threading
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import cv2
import numpy as np

from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import TrackingResult, TrackState

logger = logging.getLogger(__name__)

DEFAULT_BUFFER_SECONDS = 30.0
_JPEG_QUALITY = 80
_QUEUE_CAPACITY = 8  # tiny on purpose: backlog means drop, not lag


@dataclass(frozen=True, slots=True)
class BufferedFrame:
    """One ring entry: compressed pixels + the ADR-0007 identity."""

    camera_id: str
    sequence: int
    captured_at: datetime
    frame_id: UUID
    correlation_id: UUID
    width: int
    height: int
    jpeg: bytes

    def decode(self) -> np.ndarray:
        image = cv2.imdecode(np.frombuffer(self.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("buffered frame failed to decode")
        return np.asarray(image)


@dataclass(frozen=True, slots=True)
class TrackSnapshot:
    """The tracker's conclusion about one frame, kept tiny for the ring."""

    frame_id: UUID
    captured_at: datetime
    tracks: tuple[tuple[int, float, float, float, float, float, str], ...]
    """(display_id, confidence, x, y, w, h, state) per track — plain data."""


class FrameRingBuffer:
    """Per-camera rolling window of JPEG-compressed frames.

    Memory bound: ~seconds x fps x jpeg_size (≈30 MB per camera at
    10 fps / 100 KB). Old frames fall off the deque automatically.
    """

    def __init__(
        self,
        buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
        jpeg_quality: int = _JPEG_QUALITY,
        queue_capacity: int = _QUEUE_CAPACITY,
    ) -> None:
        self._seconds = buffer_seconds
        self._quality = jpeg_quality
        self._lock = threading.Lock()
        self._rings: dict[str, deque[BufferedFrame]] = {}
        self._queue: queue.Queue[Frame] = queue.Queue(maxsize=queue_capacity)
        self._dropped = 0
        self._encoded = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ hot path

    def on_frame(self, frame: Frame) -> None:
        """FrameConsumer seam. Constant-time; never blocks the camera."""
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:  # drop the OLDEST queued frame, keep the newest
                self._queue.get_nowait()
                self._dropped += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self._dropped += 1

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="evidence-frame-ring", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    # -------------------------------------------------------------- queries

    def snapshot(self, camera_id: str, start: datetime, end: datetime) -> list[BufferedFrame]:
        """Frames captured in [start, end], oldest first. Copy — safe to use."""
        with self._lock:
            ring = self._rings.get(camera_id)
            if not ring:
                return []
            frames = list(ring)
        times = [entry.captured_at for entry in frames]
        return frames[bisect_left(times, start) : bisect_right(times, end)]

    def stats(self) -> dict[str, object]:
        with self._lock:
            per_camera = {camera: len(ring) for camera, ring in self._rings.items()}
        return {
            "status": "ok",
            "buffer_seconds": self._seconds,
            "frames": per_camera,
            "encoded": self._encoded,
            "dropped": self._dropped,
        }

    # ------------------------------------------------------------ internals

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._encode(frame)
            except Exception:
                logger.exception("frame ring: encode failed; frame skipped")

    def _encode(self, frame: Frame) -> None:
        ok, encoded = cv2.imencode(
            ".jpg", frame.data, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality]
        )
        if not ok:
            return
        entry = BufferedFrame(
            camera_id=frame.camera_id,
            sequence=frame.sequence,
            captured_at=frame.captured_at,
            frame_id=frame.frame_id,
            correlation_id=frame.correlation_id,
            width=frame.width,
            height=frame.height,
            jpeg=encoded.tobytes(),
        )
        with self._lock:
            ring = self._rings.setdefault(frame.camera_id, deque())
            ring.append(entry)
            self._encoded += 1
            cutoff = entry.captured_at.timestamp() - self._seconds
            while ring and ring[0].captured_at.timestamp() < cutoff:
                ring.popleft()


class TrackRingBuffer:
    """Per-camera rolling window of tracker conclusions (metadata only).

    A few hundred tuples of floats — negligible memory next to the frames.
    Used at export time to draw the AI-analysis overlay variant.
    """

    def __init__(self, buffer_seconds: float = DEFAULT_BUFFER_SECONDS) -> None:
        self._seconds = buffer_seconds
        self._lock = threading.Lock()
        self._rings: dict[str, deque[TrackSnapshot]] = {}

    def on_tracking(self, result: TrackingResult) -> None:
        """TrackConsumer seam. Tiny tuple copy; never blocks the pipeline."""
        snapshot = TrackSnapshot(
            frame_id=result.frame_id,
            captured_at=result.captured_at,
            tracks=tuple(
                (
                    track.display_id,
                    track.confidence,
                    track.box.x,
                    track.box.y,
                    track.box.width,
                    track.box.height,
                    track.state.value if isinstance(track.state, TrackState) else str(track.state),
                )
                for track in result.tracks
            ),
        )
        with self._lock:
            ring = self._rings.setdefault(result.camera_id, deque())
            ring.append(snapshot)
            cutoff = snapshot.captured_at.timestamp() - self._seconds
            while ring and ring[0].captured_at.timestamp() < cutoff:
                ring.popleft()

    def by_frame_id(self, camera_id: str) -> dict[UUID, TrackSnapshot]:
        """Frame-id index of the current window (copy; safe to use)."""
        with self._lock:
            ring = self._rings.get(camera_id)
            if not ring:
                return {}
            return {snapshot.frame_id: snapshot for snapshot in ring}
