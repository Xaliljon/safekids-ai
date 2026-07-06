"""Evidence domain objects: identity, transitions, retention policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from guardian_edge.domain.evidence import (
    ClipReference,
    ClipVariant,
    Evidence,
    EvidenceMetadata,
    EvidenceRetentionPolicy,
    EvidenceStatus,
    EvidenceType,
)
from guardian_edge.domain.incident import IncidentStatus, Severity

NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_evidence(
    status: EvidenceStatus = EvidenceStatus.READY,
    incident_status: IncidentStatus = IncidentStatus.PENDING_REVIEW,
    severity: Severity = Severity.HIGH,
    created_at: datetime = NOW,
) -> Evidence:
    return Evidence(
        evidence_id=Evidence.new_id(),
        evidence_type=EvidenceType.VIDEO_CLIP,
        status=status,
        incident_id=uuid4(),
        camera_id="cam-1",
        track_id=uuid4(),
        detection_id=uuid4(),
        frame_id=uuid4(),
        correlation_id=uuid4(),
        incident_severity=severity,
        incident_status=incident_status,
        incident_opened_at=created_at,
        created_at=created_at,
    )


class TestEvidence:
    def test_roundtrips_through_dict(self) -> None:
        original = make_evidence().with_result(
            metadata=EvidenceMetadata(30.0, 10.0, 640, 480, 300, 15.0, 15.0),
            clips=(
                ClipReference(ClipVariant.ORIGINAL, "clip.mp4.enc", 1000, "aa"),
                ClipReference(ClipVariant.OVERLAY, "clip-overlay.mp4.enc", 1200, "bb"),
            ),
            thumbnail_file="thumbnail.jpg.enc",
        )
        restored = Evidence.from_dict(original.to_dict())
        assert restored == original
        assert restored.clip(ClipVariant.OVERLAY).file_name == "clip-overlay.mp4.enc"

    def test_carries_the_full_identity_chain(self) -> None:
        evidence = make_evidence()
        wire = evidence.to_dict()
        # ADR-0007: incident, track, detection, frame, correlation — all present.
        for key in ("incident_id", "track_id", "detection_id", "frame_id", "correlation_id"):
            assert wire[key]

    def test_status_transitions_are_copies(self) -> None:
        pending = make_evidence(status=EvidenceStatus.PENDING)
        failed = pending.with_status(EvidenceStatus.FAILED, error="ring empty")
        assert pending.status is EvidenceStatus.PENDING
        assert failed.status is EvidenceStatus.FAILED
        assert failed.error == "ring empty"

    def test_without_media_tombstones(self) -> None:
        ready = make_evidence().with_result(
            metadata=EvidenceMetadata(30.0, 10.0, 640, 480, 300, 15.0, 15.0),
            clips=(ClipReference(ClipVariant.ORIGINAL, "clip.mp4.enc", 1, "aa"),),
            thumbnail_file="thumbnail.jpg.enc",
        )
        tombstone = ready.with_status(EvidenceStatus.EXPIRED).without_media()
        assert tombstone.clips == ()
        assert tombstone.thumbnail_file is None
        assert tombstone.status is EvidenceStatus.EXPIRED

    def test_future_evidence_types_exist(self) -> None:
        # The platform grows by adding types, not architecture (ADR-0017).
        names = {member.value for member in EvidenceType}
        assert {
            "video_clip",
            "snapshot",
            "pose_skeleton",
            "heatmap",
            "risk_timeline",
            "track_replay",
            "ai_explainability",
        } <= names


class TestRetentionPolicy:
    policy = EvidenceRetentionPolicy()

    def test_defaults_by_outcome(self) -> None:
        assert self.policy.lifetime_for(IncidentStatus.DISMISSED, Severity.MEDIUM) == timedelta(
            hours=24
        )
        assert self.policy.lifetime_for(IncidentStatus.CONFIRMED, Severity.MEDIUM) == timedelta(
            days=30
        )
        assert self.policy.lifetime_for(
            IncidentStatus.PENDING_REVIEW, Severity.MEDIUM
        ) == timedelta(days=30)

    def test_critical_overrides_everything(self) -> None:
        for status in IncidentStatus:
            assert self.policy.lifetime_for(status, Severity.CRITICAL) == timedelta(days=90)

    def test_expires_at_uses_creation_time(self) -> None:
        evidence = make_evidence(incident_status=IncidentStatus.DISMISSED)
        assert self.policy.expires_at(evidence) == NOW + timedelta(hours=24)
