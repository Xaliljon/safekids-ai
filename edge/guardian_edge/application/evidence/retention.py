"""Evidence retention: nothing is kept forever (ADR-0017).

A background sweeper applies the EvidenceRetentionPolicy to every READY or
FAILED record: dismissed incidents keep evidence briefly (default 24 h),
confirmed ones for the pilot's review horizon (30 days), critical ones
longest (90 days). Expired media is securely deleted; the metadata record
remains as a tombstone so the audit trail stays complete.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from guardian_edge.domain.evidence import EvidenceRetentionPolicy, EvidenceStatus
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore

logger = logging.getLogger(__name__)

_SWEEPABLE = {EvidenceStatus.READY, EvidenceStatus.FAILED}


class EvidenceRetentionService:
    """Periodic sweeper enforcing the retention policy."""

    def __init__(
        self,
        store: FileSystemEvidenceStore,
        policy: EvidenceRetentionPolicy | None = None,
        sweep_interval_seconds: float = 600.0,
        clock: type[datetime] = datetime,
    ) -> None:
        self._store = store
        self._policy = policy or EvidenceRetentionPolicy()
        self._interval = sweep_interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._expired_total = 0

    @property
    def policy(self) -> EvidenceRetentionPolicy:
        return self._policy

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
        return expired

    def stats(self) -> dict[str, object]:
        return {"status": "ok", "expired_total": self._expired_total}

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
