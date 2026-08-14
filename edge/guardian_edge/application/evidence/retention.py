"""Evidence retention: nothing is kept forever (ADR-0017).

A background sweeper applies the EvidenceRetentionPolicy to every READY or
FAILED record: dismissed incidents keep evidence briefly (default 24 h),
confirmed ones for the pilot's review horizon (30 days), critical ones
longest (90 days). Expired media is securely deleted; the metadata record
remains as a tombstone so the audit trail stays complete.

Age alone does not bound the disk (ADR-0019). A box that opens incidents
faster than its shortest window expires them fills its storage with nothing
expired — measured at 2602 records and 152 GB, with this sweeper running
correctly throughout. So after the age pass comes a budget pass, evicting
least-needed-first until the evidence directory is inside its ceiling and
the filesystem is above its floor.

Evicting evidence nobody has reviewed is never silent: it is logged,
counted, and reported as degraded through /health, because losing the
unseen record of a possible injury is the failure this guards against.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from guardian_edge.domain.evidence import (
    Evidence,
    EvidenceRetentionPolicy,
    EvidenceStatus,
    EvidenceStorageBudget,
)
from guardian_edge.domain.incident import IncidentStatus
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore

logger = logging.getLogger(__name__)

_SWEEPABLE = {EvidenceStatus.READY, EvidenceStatus.FAILED}


class EvidenceRetentionService:
    """Periodic sweeper enforcing the retention policy."""

    def __init__(
        self,
        store: FileSystemEvidenceStore,
        policy: EvidenceRetentionPolicy | None = None,
        budget: EvidenceStorageBudget | None = None,
        sweep_interval_seconds: float = 600.0,
        clock: type[datetime] = datetime,
    ) -> None:
        self._store = store
        self._policy = policy or EvidenceRetentionPolicy()
        self._budget = budget or EvidenceStorageBudget()
        self._interval = sweep_interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._expired_total = 0
        self._evicted_total = 0
        self._unreviewed_evicted_total = 0

    @property
    def policy(self) -> EvidenceRetentionPolicy:
        return self._policy

    @property
    def budget(self) -> EvidenceStorageBudget:
        return self._budget

    def stats(self) -> dict[str, object]:
        """What /health reports. Evicting unreviewed evidence degrades the
        subsystem: it means the box is producing incidents faster than
        anyone can review them, and the fix is upstream in the risk policy,
        not more disk."""
        return {
            "status": "degraded" if self._unreviewed_evicted_total else "ok",
            "expired_total": self._expired_total,
            "evicted_total": self._evicted_total,
            "unreviewed_evicted_total": self._unreviewed_evicted_total,
        }

    def sweep_once(self) -> int:
        """Expire everything past its lifetime; returns how many expired."""
        now = self._clock.now(tz=timezone.utc)
        expired = 0
        for evidence in self._store.list_evidence():
            if evidence.status not in _SWEEPABLE:
                continue
            if self._policy.expires_at(evidence) <= now:
                self._store.delete(evidence, EvidenceStatus.EXPIRED, actor="retention-policy")
                expired += 1
                logger.info(
                    "evidence expired for incident %s (%s/%s, kept %s)",
                    evidence.incident_id,
                    evidence.incident_status.value,
                    evidence.incident_severity.value,
                    self._policy.lifetime_for(evidence.incident_status, evidence.incident_severity),
                )
        self._expired_total += expired
        expired += self._enforce_budget()
        return expired

    def _enforce_budget(self) -> int:
        """Evict least-needed-first until the box is inside its budget.

        Runs after the age pass, so a quiet box never reaches this code and
        behaves exactly as ADR-0017 described.
        """
        records = [e for e in self._store.list_evidence() if e.status in _SWEEPABLE]
        used = sum(record.stored_bytes for record in records)
        free = self._free_bytes()
        if not self._budget.over_budget(used, free):
            return 0

        evicted = 0
        for evidence in EvidenceStorageBudget.eviction_order(records):
            if not self._budget.over_budget(used, free):
                break
            freed = evidence.stored_bytes
            self._store.delete(evidence, EvidenceStatus.EXPIRED, actor="storage-budget")
            used -= freed
            free += freed
            evicted += 1
            self._note_eviction(evidence, freed)
        self._evicted_total += evicted
        return evicted

    def _note_eviction(self, evidence: Evidence, freed_bytes: int) -> None:
        if evidence.incident_status is IncidentStatus.PENDING_REVIEW:
            self._unreviewed_evicted_total += 1
            logger.warning(
                "evidence for UNREVIEWED incident %s evicted to stay inside the storage "
                "budget (%.1f MB freed) — the box is opening incidents faster than they "
                "are reviewed; tune the risk policy, not the disk",
                evidence.incident_id,
                freed_bytes / (1024 * 1024),
            )
            return
        logger.info(
            "evidence for incident %s evicted by storage budget (%s, %.1f MB freed)",
            evidence.incident_id,
            evidence.incident_status.value,
            freed_bytes / (1024 * 1024),
        )

    def _free_bytes(self) -> int:
        import shutil

        try:
            return shutil.disk_usage(self._store.evidence_dir).free
        except OSError:
            logger.exception("could not read free disk; treating as unconstrained")
            return self._budget.min_free_bytes

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="evidence-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep_once()
            except Exception:
                logger.exception("evidence retention sweep failed; sweeper continues")
            self._stop.wait(self._interval)
