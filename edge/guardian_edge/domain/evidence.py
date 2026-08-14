"""Evidence domain: what the box keeps to justify a safety incident.

Design intent (ADR-0017):

- Evidence is generated ONLY for safety incidents — there is no continuous
  recording anywhere in the system. The circular buffer lives in RAM and
  overwrites itself; only an incident turns a slice of it into a file.
- The ADR-0007 identity chain stays intact: every Evidence carries the
  incident, track, detection, frame and correlation identifiers of the
  moment that triggered it.
- ``EvidenceType`` is open for growth (snapshots, pose skeletons, heatmaps,
  risk timelines, track replays) — video clips are only the first type.
  New types add enum members and producers, never architecture.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.incident import IncidentStatus, Severity


class EvidenceType(Enum):
    """What kind of artifact this evidence is. Video is only the first."""

    VIDEO_CLIP = "video_clip"
    SNAPSHOT = "snapshot"
    POSE_SKELETON = "pose_skeleton"
    HEATMAP = "heatmap"
    RISK_TIMELINE = "risk_timeline"
    TRACK_REPLAY = "track_replay"
    AI_EXPLAINABILITY = "ai_explainability"


class EvidenceStatus(Enum):
    PENDING = "pending"  # incident seen, post-roll still filling
    RECORDING = "recording"  # export in progress
    READY = "ready"  # stored, encrypted, servable
    FAILED = "failed"  # export failed (buffer empty, encoder error, ...)
    EXPIRED = "expired"  # retention passed; files securely deleted
    DELETED = "deleted"  # manually deleted by an operator/director


class ClipVariant(Enum):
    """The director can switch between the raw view and the AI's view."""

    ORIGINAL = "original"
    OVERLAY = "overlay"


@dataclass(frozen=True, slots=True)
class ClipReference:
    """One stored media file belonging to an evidence record."""

    variant: ClipVariant
    file_name: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant.value,
            "file_name": self.file_name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> ClipReference:
        return ClipReference(
            variant=ClipVariant(raw["variant"]),
            file_name=str(raw["file_name"]),
            size_bytes=int(raw["size_bytes"]),
            sha256=str(raw["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    """Facts about the clip itself (no imagery, safe to store in plaintext)."""

    duration_seconds: float
    fps: float
    width: int
    height: int
    frame_count: int
    pre_seconds: float
    post_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "pre_seconds": self.pre_seconds,
            "post_seconds": self.post_seconds,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> EvidenceMetadata:
        return EvidenceMetadata(
            duration_seconds=float(raw["duration_seconds"]),
            fps=float(raw["fps"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
            frame_count=int(raw["frame_count"]),
            pre_seconds=float(raw["pre_seconds"]),
            post_seconds=float(raw["post_seconds"]),
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """One evidence record for one safety incident.

    Identity chain (ADR-0007): the incident, track, detection, frame and
    correlation identifiers all reference the exact moment that opened the
    incident — evidence is traceable back through risk, tracking and
    detection to a single captured frame.
    """

    evidence_id: UUID
    evidence_type: EvidenceType
    status: EvidenceStatus
    incident_id: UUID
    camera_id: str
    track_id: UUID
    detection_id: UUID
    frame_id: UUID
    correlation_id: UUID
    incident_severity: Severity
    incident_status: IncidentStatus
    incident_opened_at: datetime
    created_at: datetime
    metadata: EvidenceMetadata | None = None
    clips: tuple[ClipReference, ...] = ()
    thumbnail_file: str | None = None
    error: str | None = None
    evidence_version: int = field(default=1)

    @property
    def stored_bytes(self) -> int:
        """Bytes this record occupies, from its own clip metadata.

        Read from the record rather than the filesystem so a retention
        sweep costs no directory walk (ADR-0019).
        """
        return sum(clip.size_bytes for clip in self.clips)

    @staticmethod
    def new_id() -> UUID:
        return uuid4()

    def with_status(self, status: EvidenceStatus, error: str | None = None) -> Evidence:
        return replace(self, status=status, error=error)

    def with_result(
        self,
        metadata: EvidenceMetadata,
        clips: tuple[ClipReference, ...],
        thumbnail_file: str,
    ) -> Evidence:
        return replace(
            self,
            status=EvidenceStatus.READY,
            metadata=metadata,
            clips=clips,
            thumbnail_file=thumbnail_file,
            error=None,
        )

    def with_incident_status(self, status: IncidentStatus) -> Evidence:
        return replace(self, incident_status=status)

    def without_media(self) -> Evidence:
        """Tombstone form: record stays, media references are gone."""
        return replace(self, clips=(), thumbnail_file=None)

    def clip(self, variant: ClipVariant) -> ClipReference | None:
        for reference in self.clips:
            if reference.variant is variant:
                return reference
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_version": self.evidence_version,
            "evidence_id": str(self.evidence_id),
            "evidence_type": self.evidence_type.value,
            "status": self.status.value,
            "incident_id": str(self.incident_id),
            "camera_id": self.camera_id,
            "track_id": str(self.track_id),
            "detection_id": str(self.detection_id),
            "frame_id": str(self.frame_id),
            "correlation_id": str(self.correlation_id),
            "incident_severity": self.incident_severity.value,
            "incident_status": self.incident_status.value,
            "incident_opened_at": self.incident_opened_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "clips": [clip.to_dict() for clip in self.clips],
            "thumbnail_file": self.thumbnail_file,
            "error": self.error,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> Evidence:
        return Evidence(
            evidence_id=UUID(raw["evidence_id"]),
            evidence_type=EvidenceType(raw["evidence_type"]),
            status=EvidenceStatus(raw["status"]),
            incident_id=UUID(raw["incident_id"]),
            camera_id=str(raw["camera_id"]),
            track_id=UUID(raw["track_id"]),
            detection_id=UUID(raw["detection_id"]),
            frame_id=UUID(raw["frame_id"]),
            correlation_id=UUID(raw["correlation_id"]),
            incident_severity=Severity(raw["incident_severity"]),
            incident_status=IncidentStatus(raw["incident_status"]),
            incident_opened_at=datetime.fromisoformat(raw["incident_opened_at"]),
            created_at=datetime.fromisoformat(raw["created_at"]),
            metadata=(EvidenceMetadata.from_dict(raw["metadata"]) if raw.get("metadata") else None),
            clips=tuple(ClipReference.from_dict(clip) for clip in raw.get("clips", [])),
            thumbnail_file=raw.get("thumbnail_file"),
            error=raw.get("error"),
            evidence_version=int(raw.get("evidence_version", 1)),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRetentionPolicy:
    """How long evidence lives, by review outcome (ADR-0017 defaults).

    CRITICAL incidents keep their evidence longest regardless of outcome —
    a dismissed critical may still matter to an investigation. Everything
    expires; nothing is kept forever.
    """

    dismissed: timedelta = timedelta(hours=24)
    confirmed: timedelta = timedelta(days=30)
    critical: timedelta = timedelta(days=90)
    pending: timedelta = timedelta(days=30)

    def lifetime_for(self, status: IncidentStatus, severity: Severity) -> timedelta:
        if severity is Severity.CRITICAL:
            return self.critical
        if status is IncidentStatus.DISMISSED:
            return self.dismissed
        if status is IncidentStatus.CONFIRMED:
            return self.confirmed
        return self.pending

    def expires_at(self, evidence: Evidence) -> datetime:
        return evidence.created_at + self.lifetime_for(
            evidence.incident_status, evidence.incident_severity
        )


@dataclass(frozen=True, slots=True)
class EvidenceStorageBudget:
    """How much disk evidence may occupy at once (ADR-0019).

    Age answers *when may this be deleted*. It does not answer *how much may
    exist*, and a box that opens incidents faster than its shortest window
    expires them fills the disk with nothing expired: 2602 records and
    152 GB were measured that way, with the sweeper running correctly the
    whole time.

    This is the backstop, applied after the age pass. Defaults are a
    starting point — the real numbers need a pilot's incident rate, which
    does not exist yet.
    """

    max_total_bytes: int = 20 * 1024**3
    """Ceiling on the evidence directory."""

    min_free_bytes: int = 10 * 1024**3
    """Floor on the filesystem — twice the installer's own 5 GB refusal
    threshold, so the budget bites before the box endangers anything else."""

    def __post_init__(self) -> None:
        if self.max_total_bytes <= 0 or self.min_free_bytes < 0:
            raise VisionConfigurationError("evidence budget must be positive")

    def over_budget(self, used_bytes: int, free_bytes: int) -> bool:
        return used_bytes > self.max_total_bytes or free_bytes < self.min_free_bytes

    @staticmethod
    def eviction_order(records: Iterable[Evidence]) -> list[Evidence]:
        """Least-needed first.

        Review state leads, not age. Evidence nobody has looked at is the
        evidence most likely to be needed, so PENDING_REVIEW goes last —
        evicting strictly oldest-first would delete exactly those, because
        on a busy box the oldest records are the ones waiting longest for a
        human. CRITICAL goes last within its class; a dismissed critical
        still outranks a pending low.
        """
        return sorted(records, key=_eviction_key)


def _eviction_key(evidence: Evidence) -> tuple[int, int, datetime]:
    by_review = {
        IncidentStatus.DISMISSED: 0,
        IncidentStatus.CONFIRMED: 1,
        IncidentStatus.PENDING_REVIEW: 2,
    }
    return (
        by_review[evidence.incident_status],
        1 if evidence.incident_severity is Severity.CRITICAL else 0,
        evidence.created_at,
    )
