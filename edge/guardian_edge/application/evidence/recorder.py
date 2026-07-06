"""EvidenceRecorder: SafetyIncident -> encrypted evidence clip (ADR-0017).

Composition seam: the recorder is an IncidentConsumer, fanned out next to
the NotificationEngine in the supervisor. ``on_incident`` only enqueues —
the Risk Engine NEVER waits for clip generation. A worker thread then:

  1. waits until the post-roll window has filled in the frame ring,
  2. pulls [incident - pre, incident + post] frames from the ring,
  3. encodes the ORIGINAL clip (mp4) and the AI-ANALYSIS overlay clip
     (boxes, track ids, confidence, timeline, incident marker),
  4. renders the thumbnail (the frame closest to the incident moment),
  5. hands everything to the encrypted store.

One evidence record per incident (the first alert wins; escalations of the
same incident do not re-export).
"""

from __future__ import annotations

import logging
import queue
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import cv2

from guardian_edge.domain.evidence import (
    Evidence,
    EvidenceMetadata,
    EvidenceStatus,
    EvidenceType,
)
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.infrastructure.evidence.overlay import render_overlay
from guardian_edge.infrastructure.evidence.rings import (
    BufferedFrame,
    FrameRingBuffer,
    TrackRingBuffer,
    TrackSnapshot,
)
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore

logger = logging.getLogger(__name__)

DEFAULT_PRE_SECONDS = 15.0
DEFAULT_POST_SECONDS = 15.0
_MIN_FRAMES = 5  # fewer than this is not evidence, it's a corrupt file
_FALLBACK_FPS = 10.0


class EvidenceRecorder:
    """Turns safety incidents into encrypted evidence clips, asynchronously."""

    def __init__(
        self,
        frame_ring: FrameRingBuffer,
        track_ring: TrackRingBuffer,
        store: FileSystemEvidenceStore,
        pre_seconds: float = DEFAULT_PRE_SECONDS,
        post_seconds: float = DEFAULT_POST_SECONDS,
        clock: type[datetime] = datetime,
        post_roll_poll_seconds: float = 0.5,
    ) -> None:
        self._frame_ring = frame_ring
        self._track_ring = track_ring
        self._store = store
        self._pre = pre_seconds
        self._post = post_seconds
        self._clock = clock
        self._poll = post_roll_poll_seconds

        self._queue: queue.Queue[SafetyIncident] = queue.Queue()
        self._seen: set[UUID] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exported = 0
        self._failed = 0

    # ------------------------------------------------------------ hot path

    def on_incident(self, incident: SafetyIncident) -> None:
        """IncidentConsumer seam: constant-time, the risk engine never waits."""
        with self._lock:
            if incident.incident_id in self._seen:
                return  # escalation of an incident we are already exporting
            self._seen.add(incident.incident_id)
        self._queue.put(incident)

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="evidence-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._thread = None

    def stats(self) -> dict[str, object]:
        return {
            "status": "ok" if self._failed == 0 else "degraded",
            "exported": self._exported,
            "failed": self._failed,
            "queued": self._queue.qsize(),
        }

    # ------------------------------------------------------------ internals

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                incident = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._export(incident)
                self._exported += 1
            except Exception as error:
                self._failed += 1
                logger.exception("evidence: export failed for incident %s", incident.incident_id)
                self._mark_failed(incident, str(error))

    def _export(self, incident: SafetyIncident) -> None:
        evidence = self._new_record(incident)
        self._store.save_record(evidence)

        # Wait until the post-roll has filled (or the recorder is stopping —
        # then export whatever the ring holds rather than losing evidence).
        window_end = incident.opened_at + timedelta(seconds=self._post)
        while self._clock.now(tz=timezone.utc) < window_end and not self._stop.is_set():
            self._stop.wait(self._poll)

        evidence = evidence.with_status(EvidenceStatus.RECORDING)
        self._store.save_record(evidence)

        window_start = incident.opened_at - timedelta(seconds=self._pre)
        frames = self._frame_ring.snapshot(incident.camera_id, window_start, window_end)
        if len(frames) < _MIN_FRAMES:
            raise RuntimeError(
                f"only {len(frames)} buffered frame(s) for camera "
                f"'{incident.camera_id}' in the incident window"
            )

        fps = self._measure_fps(frames)
        tracks = self._track_ring.by_frame_id(incident.camera_id)

        original = self._encode_clip(frames, fps, overlay=False, incident=incident, tracks={})
        overlay = self._encode_clip(frames, fps, overlay=True, incident=incident, tracks=tracks)
        thumbnail = self._thumbnail(frames, tracks, incident)

        metadata = EvidenceMetadata(
            duration_seconds=round(len(frames) / fps, 2),
            fps=round(fps, 2),
            width=frames[0].width,
            height=frames[0].height,
            frame_count=len(frames),
            pre_seconds=self._pre,
            post_seconds=self._post,
        )
        self._store.save_media(evidence, original, overlay, thumbnail, metadata)
        self._store.audit("export", evidence.evidence_id, "evidence-recorder")
        logger.info(
            "evidence ready for incident %s (%d frames, %.1fs)",
            incident.incident_id,
            len(frames),
            metadata.duration_seconds,
        )

    def _new_record(self, incident: SafetyIncident) -> Evidence:
        # ADR-0007: reference the exact detection/frame that evidenced the
        # incident (the latest corroborating candidate's track detection).
        last_event = incident.events[-1]
        detection = last_event.track.last_detection
        return Evidence(
            evidence_id=Evidence.new_id(),
            evidence_type=EvidenceType.VIDEO_CLIP,
            status=EvidenceStatus.PENDING,
            incident_id=incident.incident_id,
            camera_id=incident.camera_id,
            track_id=incident.track_id,
            detection_id=detection.detection_id,
            frame_id=last_event.frame_id,
            correlation_id=incident.correlation_id,
            incident_severity=incident.severity,
            incident_status=incident.status,
            incident_opened_at=incident.opened_at,
            created_at=self._clock.now(tz=timezone.utc),
        )

    @staticmethod
    def _measure_fps(frames: list[BufferedFrame]) -> float:
        if len(frames) < 2:
            return _FALLBACK_FPS
        elapsed = (frames[-1].captured_at - frames[0].captured_at).total_seconds()
        if elapsed <= 0:
            return _FALLBACK_FPS
        return max((len(frames) - 1) / elapsed, 1.0)

    def _encode_clip(
        self,
        frames: list[BufferedFrame],
        fps: float,
        overlay: bool,
        incident: SafetyIncident,
        tracks: dict[UUID, TrackSnapshot],
    ) -> bytes:
        """Encode frames to an mp4 in a temp file, return (and remove) bytes."""
        clip_start, clip_end = frames[0].captured_at, frames[-1].captured_at
        with tempfile.TemporaryDirectory(prefix="guardian-evidence-") as workdir:
            path = Path(workdir) / "clip.mp4"
            writer = cv2.VideoWriter(
                str(path),
                cv2.VideoWriter.fourcc(*"mp4v"),
                fps,
                (frames[0].width, frames[0].height),
            )
            try:
                for frame in frames:
                    image = frame.decode()
                    if overlay:
                        image = render_overlay(
                            image,
                            tracks.get(frame.frame_id),
                            frame.captured_at,
                            clip_start,
                            clip_end,
                            incident.opened_at,
                        )
                    writer.write(image)
            finally:
                writer.release()
            return path.read_bytes()

    def _thumbnail(
        self,
        frames: list[BufferedFrame],
        tracks: dict[UUID, TrackSnapshot],
        incident: SafetyIncident,
    ) -> bytes:
        """Poster frame: the overlay view at the incident moment."""
        at_incident = min(
            frames, key=lambda f: abs((f.captured_at - incident.opened_at).total_seconds())
        )
        image = render_overlay(
            at_incident.decode(),
            tracks.get(at_incident.frame_id),
            at_incident.captured_at,
            frames[0].captured_at,
            frames[-1].captured_at,
            incident.opened_at,
        )
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("thumbnail encoding failed")
        return encoded.tobytes()

    def _mark_failed(self, incident: SafetyIncident, error: str) -> None:
        try:
            record = self._store.for_incident(incident.incident_id)
            if record is not None:
                self._store.save_record(record.with_status(EvidenceStatus.FAILED, error=error))
        except Exception:
            logger.exception("evidence: could not record failure state")
