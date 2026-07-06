"""Retention: dismissed 24h, confirmed 30d, critical 90d — then secure expiry."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from evidence_fixtures import BASE, FrozenClock
from test_evidence_domain import make_evidence

from guardian_edge.application.evidence.retention import EvidenceRetentionService
from guardian_edge.domain.evidence import EvidenceMetadata, EvidenceStatus
from guardian_edge.domain.incident import IncidentStatus, Severity
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore

METADATA = EvidenceMetadata(30.0, 10.0, 64, 48, 300, 15.0, 15.0)


@pytest.fixture()
def store(tmp_path: Path) -> FileSystemEvidenceStore:
    return FileSystemEvidenceStore(
        tmp_path / "evidence", EvidenceVault(tmp_path / "keys" / "evidence.key")
    )


def stored(store: FileSystemEvidenceStore, **kwargs):  # noqa: ANN201 - helper
    record = make_evidence(status=EvidenceStatus.PENDING, created_at=BASE, **kwargs)
    store.save_record(record)
    return store.save_media(record, b"o", b"v", b"t", METADATA)


class TestRetentionSweep:
    def test_dismissed_expires_after_24h(self, store, tmp_path: Path) -> None:
        record = stored(store, incident_status=IncidentStatus.DISMISSED)
        clock = FrozenClock(BASE + timedelta(hours=23))
        service = EvidenceRetentionService(store, clock=clock)  # type: ignore[arg-type]
        assert service.sweep_once() == 0, "not yet"
        clock.advance(3600 * 2)
        assert service.sweep_once() == 1
        tombstone = store.get(record.evidence_id)
        assert tombstone.status is EvidenceStatus.EXPIRED
        folder = tmp_path / "evidence" / str(record.incident_id)
        assert {file.name for file in folder.iterdir()} == {"metadata.json"}

    def test_confirmed_keeps_30_days(self, store) -> None:
        stored(store, incident_status=IncidentStatus.CONFIRMED)
        clock = FrozenClock(BASE + timedelta(days=29))
        service = EvidenceRetentionService(store, clock=clock)  # type: ignore[arg-type]
        assert service.sweep_once() == 0
        clock.advance(86400 * 2)
        assert service.sweep_once() == 1

    def test_critical_keeps_90_days_even_when_dismissed(self, store) -> None:
        stored(
            store,
            incident_status=IncidentStatus.DISMISSED,
            severity=Severity.CRITICAL,
        )
        clock = FrozenClock(BASE + timedelta(days=89))
        service = EvidenceRetentionService(store, clock=clock)  # type: ignore[arg-type]
        assert service.sweep_once() == 0
        clock.advance(86400 * 2)
        assert service.sweep_once() == 1

    def test_tombstones_are_not_reswept(self, store) -> None:
        stored(store, incident_status=IncidentStatus.DISMISSED)
        clock = FrozenClock(BASE + timedelta(days=2))
        service = EvidenceRetentionService(store, clock=clock)  # type: ignore[arg-type]
        assert service.sweep_once() == 1
        assert service.sweep_once() == 0, "expired evidence expires once"

    def test_review_decision_changes_the_lifetime(self, store) -> None:
        """Pending evidence dismissed by the director shortens to 24h."""
        record = stored(store, incident_status=IncidentStatus.PENDING_REVIEW)
        clock = FrozenClock(BASE + timedelta(days=2))
        service = EvidenceRetentionService(store, clock=clock)  # type: ignore[arg-type]
        assert service.sweep_once() == 0, "pending keeps 30 days"
        store.update_incident_status(record.incident_id, IncidentStatus.DISMISSED)
        assert service.sweep_once() == 1, "dismissed only keeps 24h"

    def test_sweeper_thread_runs_and_stops(self, store) -> None:
        service = EvidenceRetentionService(store, sweep_interval_seconds=0.05)
        service.start()
        try:
            import time

            time.sleep(0.15)
        finally:
            service.stop()
        assert service.stats()["status"] == "ok"
