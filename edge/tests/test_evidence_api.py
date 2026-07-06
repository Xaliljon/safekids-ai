"""Device API evidence endpoints: trusted-only, audited, media served."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from test_evidence_domain import make_evidence

from guardian_edge.api.pairing import PairingManager
from guardian_edge.api.server import DeviceApiServer
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.domain.evidence import EvidenceMetadata, EvidenceStatus
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel

METADATA = EvidenceMetadata(30.0, 10.0, 64, 48, 300, 15.0, 15.0)


class EvidenceApiHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.store = FileSystemEvidenceStore(
            tmp_path / "evidence", EvidenceVault(tmp_path / "keys" / "evidence.key")
        )
        channel = LocalPushChannel(tmp_path / "outbox")
        self.engine = NotificationEngine(channel)
        self.pairing = PairingManager(tmp_path)
        self.server = DeviceApiServer(
            risk_engine=RiskEngine(self.engine),
            push_channel=channel,
            outbox_dir=tmp_path / "outbox",
            pairing=self.pairing,
            host="127.0.0.1",
            api_port=0,
            ws_port=0,
            evidence_store=self.store,
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.api_port}"
        self.token = self.pairing.pair(self.pairing._code, "director-phone")  # noqa: SLF001
        assert self.token

    def close(self) -> None:
        self.server.stop()

    def get(self, path: str, token: str | None = None) -> tuple[int, bytes, str]:
        request = urllib.request.Request(  # noqa: S310 - test harness URL
            self.base + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                return (
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", ""),
                )
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "")

    def get_json(self, path: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
        status, body, _ = self.get(path, token)
        return status, json.loads(body)


@pytest.fixture()
def harness(tmp_path: Path):  # noqa: ANN201
    instance = EvidenceApiHarness(tmp_path)
    yield instance
    instance.close()


def stored(harness: EvidenceApiHarness):  # noqa: ANN201 - helper
    record = make_evidence(status=EvidenceStatus.PENDING)
    harness.store.save_record(record)
    return harness.store.save_media(record, b"original-mp4", b"overlay-mp4", b"jpeg", METADATA)


class TestAuthorization:
    def test_every_evidence_endpoint_rejects_unpaired_devices(self, harness) -> None:
        record = stored(harness)
        for path in (
            "/api/v1/evidence",
            f"/api/v1/evidence/{record.evidence_id}",
            f"/api/v1/evidence/{record.evidence_id}/video",
            f"/api/v1/evidence/{record.evidence_id}/thumbnail",
        ):
            status, _, _ = harness.get(path)
            assert status == 401, path
            status, _, _ = harness.get(path, token="forged-token")  # noqa: S106 - deliberately invalid credential
            assert status == 401, path

    def test_unauthorized_access_leaves_no_media_bytes(self, harness) -> None:
        record = stored(harness)
        _, body, _ = harness.get(f"/api/v1/evidence/{record.evidence_id}/video")
        assert b"original-mp4" not in body


class TestEvidenceEndpoints:
    def test_list_and_get(self, harness) -> None:
        record = stored(harness)
        status, body = harness.get_json("/api/v1/evidence", token=harness.token)
        assert status == 200
        assert [item["evidence_id"] for item in body["evidence"]] == [str(record.evidence_id)]
        status, one = harness.get_json(
            f"/api/v1/evidence/{record.evidence_id}", token=harness.token
        )
        assert status == 200
        assert one["incident_id"] == str(record.incident_id)
        assert one["metadata"]["duration_seconds"] == 30.0

    def test_video_variants_and_thumbnail(self, harness) -> None:
        record = stored(harness)
        status, body, content_type = harness.get(
            f"/api/v1/evidence/{record.evidence_id}/video", token=harness.token
        )
        assert (status, body, content_type) == (200, b"original-mp4", "video/mp4")
        status, body, _ = harness.get(
            f"/api/v1/evidence/{record.evidence_id}/video?variant=overlay",
            token=harness.token,
        )
        assert (status, body) == (200, b"overlay-mp4")
        status, body, content_type = harness.get(
            f"/api/v1/evidence/{record.evidence_id}/thumbnail", token=harness.token
        )
        assert (status, body, content_type) == (200, b"jpeg", "image/jpeg")

    def test_bad_variant_and_unknown_id(self, harness) -> None:
        record = stored(harness)
        status, _, _ = harness.get(
            f"/api/v1/evidence/{record.evidence_id}/video?variant=director-cut",
            token=harness.token,
        )
        assert status == 400
        status, _ = harness.get_json(
            "/api/v1/evidence/00000000-0000-0000-0000-000000000000", token=harness.token
        )
        assert status == 404
        status, _, _ = harness.get("/api/v1/evidence/not-a-uuid/video", token=harness.token)
        assert status == 404

    def test_all_access_is_audited_with_device_name(self, harness) -> None:
        record = stored(harness)
        harness.get(f"/api/v1/evidence/{record.evidence_id}", token=harness.token)
        harness.get(
            f"/api/v1/evidence/{record.evidence_id}/video?variant=overlay",
            token=harness.token,
        )
        harness.get(f"/api/v1/evidence/{record.evidence_id}/thumbnail", token=harness.token)
        actions = [entry["action"] for entry in harness.store.audit_entries()]
        assert actions == ["read", "download", "thumbnail"]
        assert all(entry["actor"] == "director-phone" for entry in harness.store.audit_entries())

    def test_evidence_disabled_returns_not_found(self, tmp_path: Path) -> None:
        channel = LocalPushChannel(tmp_path / "outbox")
        engine = NotificationEngine(channel)
        pairing = PairingManager(tmp_path)
        server = DeviceApiServer(
            risk_engine=RiskEngine(engine),
            push_channel=channel,
            outbox_dir=tmp_path / "outbox",
            pairing=pairing,
            host="127.0.0.1",
            api_port=0,
            ws_port=0,
        )
        server.start()
        try:
            token = pairing.pair(pairing._code, "tester")  # noqa: SLF001
            request = urllib.request.Request(  # noqa: S310
                f"http://127.0.0.1:{server.api_port}/api/v1/evidence",
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
            assert status == 404
        finally:
            server.stop()
