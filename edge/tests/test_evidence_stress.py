"""Evidence under load: the hot path stays fast while exports run."""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pytest
from camera_fakes import wait_until
from evidence_fixtures import BASE, FrozenClock, make_frame, make_incident

from guardian_edge.application.evidence.recorder import EvidenceRecorder
from guardian_edge.domain.evidence import EvidenceStatus
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.rings import FrameRingBuffer, TrackRingBuffer
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore

pytestmark = pytest.mark.stress


def test_exports_do_not_slow_the_frame_path(tmp_path: Path) -> None:
    """Feed 1000 frames while several incidents export concurrently; the
    per-frame cost of on_frame must stay far below a frame interval."""
    store = FileSystemEvidenceStore(
        tmp_path / "evidence", EvidenceVault(tmp_path / "keys" / "evidence.key")
    )
    ring = FrameRingBuffer(buffer_seconds=300.0, queue_capacity=1024)
    ring.start()
    clock = FrozenClock(BASE + timedelta(seconds=120))
    recorder = EvidenceRecorder(
        ring,
        TrackRingBuffer(),
        store,
        pre_seconds=2.0,
        post_seconds=2.0,
        clock=clock,  # type: ignore[arg-type]
        post_roll_poll_seconds=0.01,
    )
    recorder.start()
    try:
        # Warm the ring with enough history for the incidents.
        for sequence in range(100):
            ring.on_frame(make_frame(sequence))
        assert wait_until(lambda: ring.stats()["encoded"] == 100)

        incidents = [
            make_incident(opened_at=BASE + timedelta(seconds=3 + offset)) for offset in range(5)
        ]
        for incident in incidents:
            recorder.on_incident(incident)

        # Keep streaming while the recorder crunches exports.
        worst = 0.0
        for sequence in range(100, 1100):
            started = time.perf_counter()
            ring.on_frame(make_frame(sequence))
            worst = max(worst, time.perf_counter() - started)
        assert worst < 0.01, f"worst on_frame under load: {worst * 1000:.2f} ms"

        assert wait_until(
            lambda: all(
                (record := store.for_incident(incident.incident_id)) is not None
                and record.status in (EvidenceStatus.READY, EvidenceStatus.FAILED)
                for incident in incidents
            ),
            timeout=60.0,
        )
        ready = [store.for_incident(incident.incident_id) for incident in incidents]
        assert all(record is not None and record.status is EvidenceStatus.READY for record in ready)
    finally:
        recorder.stop()
        ring.stop()
