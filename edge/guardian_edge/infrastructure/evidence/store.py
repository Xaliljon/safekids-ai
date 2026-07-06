"""Encrypted filesystem evidence store + access audit (ADR-0017).

Layout — evidence lives apart from logs and models by construction:

    $GUARDIAN_HOME/evidence/
      audit.jsonl                      every access, append-only
      <incident-id>/
        metadata.json                  Evidence record (no imagery)
        clip.mp4.enc                   original view (AES-256-GCM)
        clip-overlay.mp4.enc           AI analysis view (AES-256-GCM)
        thumbnail.jpg.enc              poster frame (AES-256-GCM)

metadata.json is plaintext on purpose: it contains identifiers and clip
facts only (never pixels), and the retention sweeper must be able to scan
expiry without touching the vault key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.domain.evidence import (
    ClipReference,
    ClipVariant,
    Evidence,
    EvidenceMetadata,
    EvidenceStatus,
)
from guardian_edge.domain.incident import IncidentStatus
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault, secure_delete

logger = logging.getLogger(__name__)

METADATA_FILE = "metadata.json"
AUDIT_FILE = "audit.jsonl"
_CLIP_FILE = {ClipVariant.ORIGINAL: "clip.mp4.enc", ClipVariant.OVERLAY: "clip-overlay.mp4.enc"}
_THUMBNAIL_FILE = "thumbnail.jpg.enc"


class UnknownEvidenceError(GuardianEdgeError):
    """No evidence with that identifier exists (or it was deleted)."""


class FileSystemEvidenceStore:
    """Owns the evidence directory: save, serve, audit, delete."""

    def __init__(self, evidence_dir: Path, vault: EvidenceVault) -> None:
        self._dir = evidence_dir
        self._vault = vault
        self._lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- writing

    def save_record(self, evidence: Evidence) -> None:
        """Persist the metadata record (created/updated atomically)."""
        folder = self._dir / str(evidence.incident_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / METADATA_FILE
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(evidence.to_dict(), indent=2), encoding="utf-8")
        temp.replace(target)

    def save_media(
        self,
        evidence: Evidence,
        original_mp4: bytes,
        overlay_mp4: bytes,
        thumbnail_jpeg: bytes,
        metadata: EvidenceMetadata,
    ) -> Evidence:
        """Encrypt + store the media; returns the READY evidence record."""
        folder = self._dir / str(evidence.incident_id)
        clips = []
        for variant, payload in (
            (ClipVariant.ORIGINAL, original_mp4),
            (ClipVariant.OVERLAY, overlay_mp4),
        ):
            file_name = _CLIP_FILE[variant]
            size = self._vault.encrypt_to_file(payload, folder / file_name)
            clips.append(
                ClipReference(
                    variant=variant,
                    file_name=file_name,
                    size_bytes=size,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        self._vault.encrypt_to_file(thumbnail_jpeg, folder / _THUMBNAIL_FILE)
        ready = evidence.with_result(
            metadata=metadata, clips=tuple(clips), thumbnail_file=_THUMBNAIL_FILE
        )
        self.save_record(ready)
        return ready

    # ------------------------------------------------------------- reading

    def list_evidence(self) -> list[Evidence]:
        """All evidence records, newest first."""
        records = []
        for metadata_path in self._dir.glob(f"*/{METADATA_FILE}"):
            record = self._read_record(metadata_path)
            if record is not None:
                records.append(record)
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records

    def get(self, evidence_id: UUID) -> Evidence:
        for record in self.list_evidence():
            if record.evidence_id == evidence_id:
                return record
        raise UnknownEvidenceError(f"no evidence with id {evidence_id}")

    def for_incident(self, incident_id: UUID) -> Evidence | None:
        path = self._dir / str(incident_id) / METADATA_FILE
        return self._read_record(path) if path.is_file() else None

    def open_clip(self, evidence: Evidence, variant: ClipVariant) -> bytes:
        """Decrypted clip bytes (memory only — plaintext never hits disk)."""
        reference = evidence.clip(variant)
        if reference is None:
            raise UnknownEvidenceError(
                f"evidence {evidence.evidence_id} has no {variant.value} clip"
            )
        path = self._dir / str(evidence.incident_id) / reference.file_name
        return self._vault.decrypt_file(path)

    def open_thumbnail(self, evidence: Evidence) -> bytes:
        if not evidence.thumbnail_file:
            raise UnknownEvidenceError(f"evidence {evidence.evidence_id} has no thumbnail")
        path = self._dir / str(evidence.incident_id) / evidence.thumbnail_file
        return self._vault.decrypt_file(path)

    # ----------------------------------------------------------- mutations

    def update_incident_status(self, incident_id: UUID, status: IncidentStatus) -> None:
        """Reflect a review decision so retention can apply the right policy."""
        record = self.for_incident(incident_id)
        if record is not None:
            self.save_record(record.with_incident_status(status))

    def delete(self, evidence: Evidence, final_status: EvidenceStatus, actor: str) -> None:
        """Securely delete the media; the metadata records what happened."""
        with self._lock:
            folder = self._dir / str(evidence.incident_id)
            for file in folder.iterdir() if folder.is_dir() else ():
                if file.name != METADATA_FILE:
                    secure_delete(file)
            self.save_record(evidence.with_status(final_status).without_media())
        self.audit("delete", evidence.evidence_id, actor, {"final": final_status.value})

    # --------------------------------------------------------------- audit

    def audit(
        self, action: str, evidence_id: UUID, actor: str, detail: dict[str, Any] | None = None
    ) -> None:
        """Append-only access trail: who touched which evidence, when, how."""
        entry = {
            "at": datetime.now(tz=timezone.utc).isoformat(),
            "action": action,
            "evidence_id": str(evidence_id),
            "actor": actor,
            **({"detail": detail} if detail else {}),
        }
        with self._lock, (self._dir / AUDIT_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def audit_entries(self) -> list[dict[str, Any]]:
        path = self._dir / AUDIT_FILE
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # ----------------------------------------------------------- internals

    def _read_record(self, path: Path) -> Evidence | None:
        try:
            return Evidence.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("evidence: unreadable metadata at %s", path)
            return None
