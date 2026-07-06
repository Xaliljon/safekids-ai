"""EvidenceRecorder: incident -> encrypted clip, asynchronously, recoverably."""

from __future__ import annotations

import tempfile
import time
from datetime import timedelta
from pathlib import Path

import cv2
import pytest
from camera_fakes import wait_until
from evidence_fixtures import BASE, FrozenClock, make_frame, make_incident

from guardian_edge.application.evidence.recorder import EvidenceRecorder
from guardian_edge.domain.evidence import ClipVariant, EvidenceStatus
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.rings import FrameRingBuffer, TrackRingBuffer
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore


@pytest.fixture()
def store(tmp_path: Path) -> FileSystemEvidenceStore:
    return FileSystemEvidenceStore(
        tmp_path / "evidence", EvidenceVault(tmp_path / "keys" / "evidence.key")
    )


def fill_ring(ring: FrameRingBuffer, frames: int = 60) -> None:
    """~6 seconds of tiny frames, 0.1s apart, starting at BASE."""
    for sequence in range(frames):
        ring.on_frame(make_frame(sequence))
    assert wait_until(lambda: ring.stats()["encoded"] == frames)


def make_recorder(
    ring: FrameRingBuffer,
    store: FileSystemEvidenceStore,
    clock: FrozenClock,
    pre: float = 2.0,
    post: float = 2.0,
) -> EvidenceRecorder:
    return EvidenceRecorder(
        ring,
        TrackRingBuffer(),
        store,
        pre_seconds=pre,
        post_seconds=post,
        clock=clock,  # type: ignore[arg-type]
        post_roll_poll_seconds=0.01,
    )


class TestExport:
    def test_incident_becomes_ready_encrypted_evidence(
        self, store: FileSystemEvidenceStore, tmp_path: Path
    ) -> None:
        ring = FrameRingBuffer(queue_capacity=256)
        ring.start()
        try:
            fill_ring(ring)
            incident_at = BASE + timedelta(seconds=3)  # mid-buffer
            clock = FrozenClock(incident_at + timedelta(seconds=10))  # post-roll done
            recorder = make_recorder(ring, store, clock)
            recorder.start()
            try:
                recorder.on_incident(make_incident(opened_at=incident_at))
                assert wait_until(
                    lambda: (
                        (records := store.list_evidence())
                        and records[0].status is EvidenceStatus.READY
                    ),
                    timeout=15.0,
                )
            finally:
                recorder.stop()
        finally:
            ring.stop()

        evidence = store.list_evidence()[0]
        assert evidence.metadata is not None
        assert evidence.metadata.frame_count > 10
        assert {clip.variant for clip in evidence.clips} == {
            ClipVariant.ORIGINAL,
            ClipVariant.OVERLAY,
        }
        # both variants decode as playable mp4 files
        for variant in ClipVariant:
            payload = store.open_clip(evidence, variant)
            with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
                handle.write(payload)
                handle.flush()
                capture = cv2.VideoCapture(handle.name)
                try:
                    ok, image = capture.read()
                finally:
                    capture.release()
            assert ok and image is not None, f"{variant} clip did not decode"
        assert store.open_thumbnail(evidence)[:2] == b"\xff\xd8", "JPEG magic"

    def test_identity_chain_matches_the_incident(self, store: FileSystemEvidenceStore) -> None:
        ring = FrameRingBuffer(queue_capacity=256)
        ring.start()
        try:
            fill_ring(ring)
            incident = make_incident(opened_at=BASE + timedelta(seconds=3))
            clock = FrozenClock(incident.opened_at + timedelta(seconds=10))
            recorder = make_recorder(ring, store, clock)
            recorder.start()
            try:
                recorder.on_incident(incident)
                assert wait_until(
                    lambda: (
                        (records := store.list_evidence())
                        and records[0].status is EvidenceStatus.READY
                    ),
                    timeout=15.0,
                )
            finally:
                recorder.stop()
        finally:
            ring.stop()
        evidence = store.list_evidence()[0]
        assert evidence.incident_id == incident.incident_id
        assert evidence.track_id == incident.track_id
        assert evidence.correlation_id == incident.correlation_id
        assert evidence.frame_id == incident.events[-1].frame_id
        assert evidence.detection_id == incident.events[-1].track.last_detection.detection_id

    def test_duplicate_incident_exports_once(self, store: FileSystemEvidenceStore) -> None:
        ring = FrameRingBuffer(queue_capacity=256)
        ring.start()
        try:
            fill_ring(ring)
            incident = make_incident(opened_at=BASE + timedelta(seconds=3))
            clock = FrozenClock(incident.opened_at + timedelta(seconds=10))
            recorder = make_recorder(ring, store, clock)
            recorder.start()
            try:
                recorder.on_incident(incident)
                recorder.on_incident(incident)  # escalation of the same incident
                assert wait_until(
                    lambda: (
                        (records := store.list_evidence())
                        and records[0].status is EvidenceStatus.READY
                    ),
                    timeout=15.0,
                )
                time.sleep(0.2)
            finally:
                recorder.stop()
        finally:
            ring.stop()
        assert len(store.list_evidence()) == 1
        assert recorder.stats()["exported"] == 1


class TestFailureAndRecovery:
    def test_empty_buffer_marks_evidence_failed(self, store: FileSystemEvidenceStore) -> None:
        ring = FrameRingBuffer()  # empty: camera never produced frames
        incident = make_incident(opened_at=BASE)
        clock = FrozenClock(BASE + timedelta(seconds=10))
        recorder = make_recorder(ring, store, clock)
        recorder.start()
        try:
            recorder.on_incident(incident)
            assert wait_until(
                lambda: (
                    (record := store.for_incident(incident.incident_id)) is not None
                    and record.status is EvidenceStatus.FAILED
                ),
                timeout=10.0,
            )
        finally:
            recorder.stop()
        record = store.for_incident(incident.incident_id)
        assert record is not None
        assert "buffered frame" in (record.error or "")
        assert recorder.stats()["status"] == "degraded"

    def test_recorder_survives_a_failure_and_keeps_exporting(
        self, store: FileSystemEvidenceStore
    ) -> None:
        ring = FrameRingBuffer(queue_capacity=256)
        ring.start()
        try:
            # First incident on a camera with no frames -> FAILED.
            broken = make_incident(camera_id="cam-none", opened_at=BASE)
            # Second incident on the healthy camera -> READY.
            fill_ring(ring)
            healthy = make_incident(opened_at=BASE + timedelta(seconds=3))
            clock = FrozenClock(BASE + timedelta(seconds=10))
            recorder = make_recorder(ring, store, clock)
            recorder.start()
            try:
                recorder.on_incident(broken)
                recorder.on_incident(healthy)
                assert wait_until(
                    lambda: (
                        (record := store.for_incident(healthy.incident_id)) is not None
                        and record.status is EvidenceStatus.READY
                    ),
                    timeout=15.0,
                )
            finally:
                recorder.stop()
        finally:
            ring.stop()
        failed = store.for_incident(broken.incident_id)
        assert failed is not None and failed.status is EvidenceStatus.FAILED

    def test_stop_mid_post_roll_still_exports(self, store: FileSystemEvidenceStore) -> None:
        """Shutdown during the post-roll: export what the ring holds."""
        ring = FrameRingBuffer(queue_capacity=256)
        ring.start()
        try:
            fill_ring(ring)
            incident = make_incident(opened_at=BASE + timedelta(seconds=3))
            clock = FrozenClock(incident.opened_at)  # post-roll would never finish
            recorder = make_recorder(ring, store, clock, post=999.0)
            recorder.start()
            recorder.on_incident(incident)
            assert wait_until(
                lambda: store.for_incident(incident.incident_id) is not None, timeout=5.0
            )
            recorder.stop()  # stop flag breaks the post-roll wait -> export runs
        finally:
            ring.stop()
        record = store.for_incident(incident.incident_id)
        assert record is not None
        assert record.status in (EvidenceStatus.READY, EvidenceStatus.FAILED)
        if record.status is EvidenceStatus.READY:
            assert record.metadata is not None and record.metadata.frame_count > 0
