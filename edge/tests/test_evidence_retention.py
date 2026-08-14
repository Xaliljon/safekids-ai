"""Retention: dismissed 24h, confirmed 30d, critical 90d — then secure expiry."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from evidence_fixtures import BASE, FrozenClock
from test_evidence_domain import make_evidence

from guardian_edge.application.evidence.retention import EvidenceRetentionService
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.evidence import (
    Evidence,
    EvidenceMetadata,
    EvidenceStatus,
    EvidenceStorageBudget,
)
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


class TestStorageBudget:
    """Age says when evidence may go; the budget says how much may exist.

    Without the second, a box that opens incidents faster than its shortest
    window expires them fills the disk with nothing expired — 2602 records
    and 152 GB, measured, with the sweeper running correctly (ADR-0019).
    """

    def test_a_quiet_box_never_reaches_the_budget(self) -> None:
        budget = EvidenceStorageBudget()
        assert not budget.over_budget(used_bytes=1_000, free_bytes=budget.min_free_bytes + 1)

    def test_the_ceiling_bites(self) -> None:
        budget = EvidenceStorageBudget(max_total_bytes=100, min_free_bytes=0)
        assert budget.over_budget(used_bytes=101, free_bytes=1 << 40)

    def test_the_free_space_floor_bites_independently(self) -> None:
        # Evidence inside its ceiling must still not starve the rest of the box.
        budget = EvidenceStorageBudget(max_total_bytes=1 << 40, min_free_bytes=1_000)
        assert budget.over_budget(used_bytes=1, free_bytes=999)

    def test_an_impossible_budget_is_refused(self) -> None:
        with pytest.raises(VisionConfigurationError):
            EvidenceStorageBudget(max_total_bytes=0)


class TestEvictionOrder:
    """Review state leads, not age. Evidence nobody has looked at is the
    evidence most likely to be needed, so it goes last."""

    def _record(self, status: IncidentStatus, severity: Severity, minute: int) -> Evidence:
        return replace(
            make_evidence(),
            incident_status=status,
            incident_severity=severity,
            created_at=datetime(2026, 8, 15, 9, minute, tzinfo=timezone.utc),
        )

    def test_unreviewed_evidence_is_evicted_last(self) -> None:
        pending_old = self._record(IncidentStatus.PENDING_REVIEW, Severity.MEDIUM, 0)
        dismissed_new = self._record(IncidentStatus.DISMISSED, Severity.MEDIUM, 59)

        order = EvidenceStorageBudget.eviction_order([pending_old, dismissed_new])

        assert order[0] is dismissed_new, (
            "oldest-first would delete the record waiting longest for review, "
            "which is exactly the one most likely to be needed"
        )
        assert order[-1] is pending_old

    def test_dismissed_goes_before_confirmed(self) -> None:
        confirmed = self._record(IncidentStatus.CONFIRMED, Severity.MEDIUM, 0)
        dismissed = self._record(IncidentStatus.DISMISSED, Severity.MEDIUM, 30)

        assert EvidenceStorageBudget.eviction_order([confirmed, dismissed])[0] is dismissed

    def test_critical_goes_last_within_its_class(self) -> None:
        critical = self._record(IncidentStatus.DISMISSED, Severity.CRITICAL, 0)
        ordinary = self._record(IncidentStatus.DISMISSED, Severity.LOW, 30)

        order = EvidenceStorageBudget.eviction_order([critical, ordinary])

        assert order[0] is ordinary
        assert order[-1] is critical

    def test_a_dismissed_critical_still_outranks_a_pending_low(self) -> None:
        dismissed_critical = self._record(IncidentStatus.DISMISSED, Severity.CRITICAL, 0)
        pending_low = self._record(IncidentStatus.PENDING_REVIEW, Severity.LOW, 0)

        order = EvidenceStorageBudget.eviction_order([pending_low, dismissed_critical])

        assert order[0] is dismissed_critical
        assert order[-1] is pending_low

    def test_oldest_first_within_a_class(self) -> None:
        older = self._record(IncidentStatus.CONFIRMED, Severity.MEDIUM, 5)
        newer = self._record(IncidentStatus.CONFIRMED, Severity.MEDIUM, 45)

        assert EvidenceStorageBudget.eviction_order([newer, older])[0] is older


class TestUnreviewedEvictionIsVisible:
    """Losing the unseen record of a possible injury may never be silent."""

    def test_a_clean_sweeper_reports_ok(self) -> None:
        service = EvidenceRetentionService(_null_store())
        assert service.stats()["status"] == "ok"
        assert service.stats()["unreviewed_evicted_total"] == 0

    def test_evicting_unreviewed_evidence_degrades_the_subsystem(self) -> None:
        service = EvidenceRetentionService(_null_store())

        service._note_eviction(  # noqa: SLF001
            replace(make_evidence(), incident_status=IncidentStatus.PENDING_REVIEW), 1024
        )

        stats = service.stats()
        assert stats["unreviewed_evicted_total"] == 1
        assert stats["status"] == "degraded", (
            "sustained unreviewed eviction means the risk policy needs tuning, "
            "not that the box needs a bigger disk — it has to surface"
        )

    def test_evicting_reviewed_evidence_does_not_degrade(self) -> None:
        service = EvidenceRetentionService(_null_store())

        service._note_eviction(  # noqa: SLF001
            replace(make_evidence(), incident_status=IncidentStatus.DISMISSED), 1024
        )

        assert service.stats()["status"] == "ok"
        assert service.stats()["unreviewed_evicted_total"] == 0


def _null_store(tmp: Path | None = None) -> FileSystemEvidenceStore:
    """A store the stats-only tests never write through."""
    import tempfile

    root = tmp or Path(tempfile.mkdtemp())
    return FileSystemEvidenceStore(root / "evidence", EvidenceVault(root / "key"))
