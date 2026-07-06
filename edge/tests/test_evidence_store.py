"""Encrypted evidence store: layout, audit trail, secure deletion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_evidence_domain import make_evidence

from guardian_edge.domain.evidence import ClipVariant, EvidenceMetadata, EvidenceStatus
from guardian_edge.domain.incident import IncidentStatus
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.store import (
    FileSystemEvidenceStore,
    UnknownEvidenceError,
)

METADATA = EvidenceMetadata(30.0, 10.0, 64, 48, 300, 15.0, 15.0)


@pytest.fixture()
def store(tmp_path: Path) -> FileSystemEvidenceStore:
    return FileSystemEvidenceStore(
        tmp_path / "evidence", EvidenceVault(tmp_path / "data" / "keys" / "evidence.key")
    )


def saved(store: FileSystemEvidenceStore):  # noqa: ANN201 - test helper
    record = make_evidence(status=EvidenceStatus.PENDING)
    store.save_record(record)
    return store.save_media(record, b"original-mp4", b"overlay-mp4", b"jpeg", METADATA)


class TestStoreLayout:
    def test_media_lands_in_the_incident_folder_encrypted(
        self, store: FileSystemEvidenceStore, tmp_path: Path
    ) -> None:
        record = saved(store)
        folder = tmp_path / "evidence" / str(record.incident_id)
        names = {file.name for file in folder.iterdir()}
        assert names == {
            "metadata.json",
            "clip.mp4.enc",
            "clip-overlay.mp4.enc",
            "thumbnail.jpg.enc",
        }
        assert b"original-mp4" not in (folder / "clip.mp4.enc").read_bytes()
        # metadata is plaintext facts, never pixels
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["status"] == "ready"

    def test_round_trips_clips_and_thumbnail(self, store: FileSystemEvidenceStore) -> None:
        record = saved(store)
        assert store.open_clip(record, ClipVariant.ORIGINAL) == b"original-mp4"
        assert store.open_clip(record, ClipVariant.OVERLAY) == b"overlay-mp4"
        assert store.open_thumbnail(record) == b"jpeg"

    def test_list_and_get(self, store: FileSystemEvidenceStore) -> None:
        record = saved(store)
        assert [item.evidence_id for item in store.list_evidence()] == [record.evidence_id]
        assert store.get(record.evidence_id).status is EvidenceStatus.READY
        with pytest.raises(UnknownEvidenceError):
            store.get(make_evidence().evidence_id)

    def test_for_incident(self, store: FileSystemEvidenceStore) -> None:
        record = saved(store)
        assert store.for_incident(record.incident_id) is not None
        assert store.for_incident(make_evidence().incident_id) is None


class TestStoreMutations:
    def test_update_incident_status(self, store: FileSystemEvidenceStore) -> None:
        record = saved(store)
        store.update_incident_status(record.incident_id, IncidentStatus.CONFIRMED)
        assert store.get(record.evidence_id).incident_status is IncidentStatus.CONFIRMED

    def test_delete_removes_media_keeps_tombstone(
        self, store: FileSystemEvidenceStore, tmp_path: Path
    ) -> None:
        record = saved(store)
        store.delete(record, EvidenceStatus.DELETED, actor="director-phone")
        folder = tmp_path / "evidence" / str(record.incident_id)
        assert {file.name for file in folder.iterdir()} == {"metadata.json"}
        tombstone = store.get(record.evidence_id)
        assert tombstone.status is EvidenceStatus.DELETED
        assert tombstone.clips == ()
        with pytest.raises(Exception):  # noqa: B017 - any failure is correct: media is gone
            store.open_clip(tombstone, ClipVariant.ORIGINAL)


class TestAudit:
    def test_every_access_is_recorded(self, store: FileSystemEvidenceStore) -> None:
        record = saved(store)
        store.audit("read", record.evidence_id, "director-phone")
        store.audit("download", record.evidence_id, "director-phone", {"variant": "overlay"})
        entries = store.audit_entries()
        assert [entry["action"] for entry in entries] == ["read", "download"]
        assert entries[0]["actor"] == "director-phone"
        assert entries[1]["detail"] == {"variant": "overlay"}
        assert all("at" in entry for entry in entries)

    def test_unreadable_metadata_is_skipped_not_fatal(
        self, store: FileSystemEvidenceStore, tmp_path: Path
    ) -> None:
        saved(store)
        broken = tmp_path / "evidence" / "broken-incident"
        broken.mkdir()
        (broken / "metadata.json").write_text("{not json", encoding="utf-8")
        assert len(store.list_evidence()) == 1
