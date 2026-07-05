"""Device API: pairing, sync, realtime push, review actions."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import websockets
from camera_fakes import wait_until
from event_fixtures import make_safety_incident

from guardian_edge.api.pairing import PairingManager
from guardian_edge.api.server import DeviceApiServer
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.domain.incident import SafetyIncident, Severity
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel


class ApiHarness:
    """A running device API over the real notification/risk stack."""

    def __init__(self, tmp_path: Path) -> None:
        self.channel = LocalPushChannel(tmp_path / "outbox")
        self.notification_engine = NotificationEngine(self.channel)
        self.risk_engine = RiskEngine(self.notification_engine)
        self.pairing = PairingManager(tmp_path)
        self.server = DeviceApiServer(
            risk_engine=self.risk_engine,
            push_channel=self.channel,
            outbox_dir=tmp_path / "outbox",
            pairing=self.pairing,
            host="127.0.0.1",
            api_port=0,
            ws_port=0,
        )
        self.notification_engine.start()
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.api_port}"

    def close(self) -> None:
        self.server.stop()
        self.notification_engine.stop()

    # -- tiny JSON HTTP client (stdlib) --

    def post(self, path: str, body: dict[str, Any], token: str | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(  # noqa: S310 - http URL built from test harness
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {token}"} if token else {}),
            method="POST",
        )
        return self._send(request)

    def get(self, path: str, token: str | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(  # noqa: S310 - http URL built from test harness
            self.base + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def pair_device(self, name: str = "director-phone") -> str:
        status, body = self.post(
            "/api/v1/pair", {"code": self.pairing.current_code, "device_name": name}
        )
        assert status == 200
        return body["token"]


@pytest.fixture
def api(tmp_path: Path):  # noqa: ANN201
    harness = ApiHarness(tmp_path)
    yield harness
    harness.close()


class TestPairing:
    def test_wrong_code_is_rejected(self, api: ApiHarness) -> None:
        status, body = api.post("/api/v1/pair", {"code": "000000", "device_name": "x"})
        assert status == 403
        assert "invalid" in body["error"]

    def test_valid_code_yields_token_and_is_single_use(self, api: ApiHarness) -> None:
        code = api.pairing.current_code
        token = api.pair_device()
        assert api.pairing.is_trusted(token)
        status, _ = api.post("/api/v1/pair", {"code": code, "device_name": "second"})
        assert status == 403, "a consumed code never pairs a second device"

    def test_trust_survives_restart(self, api: ApiHarness, tmp_path: Path) -> None:
        token = api.pair_device()
        reloaded = PairingManager(tmp_path)
        assert reloaded.is_trusted(token)

    def test_endpoints_require_pairing(self, api: ApiHarness) -> None:
        assert api.get("/api/v1/notifications?after=0")[0] == 401
        forged = "not-a-real-token"  # noqa: S105 - deliberately invalid credential
        assert api.get("/api/v1/notifications?after=0", token=forged)[0] == 401


class TestSyncAndActions:
    def incident(self, api: ApiHarness, confidence: float = 0.9) -> SafetyIncident:
        incident = make_safety_incident(severity=Severity.CRITICAL, confidence=confidence)
        api.risk_engine._open[  # noqa: SLF001 - seed the open set directly
            (incident.camera_id, incident.track_id, incident.incident_type)
        ] = incident
        self_notify = api.notification_engine
        self_notify(incident)
        assert wait_until(lambda: api.notification_engine.metrics().delivered >= 1)
        return incident

    def test_missed_notifications_sync_by_cursor(self, api: ApiHarness) -> None:
        token = api.pair_device()
        self.incident(api)
        status, body = api.get("/api/v1/notifications?after=0", token=token)
        assert status == 200
        assert body["cursor"] == 1
        assert body["notifications"][0]["severity"] == "critical"
        status, body = api.get(f"/api/v1/notifications?after={body['cursor']}", token=token)
        assert body["notifications"] == [], "nothing new after the cursor"

    def test_incident_details_include_timeline(self, api: ApiHarness) -> None:
        token = api.pair_device()
        incident = self.incident(api)
        status, body = api.get(f"/api/v1/incidents/{incident.incident_id}", token=token)
        assert status == 200
        assert body["severity"] == "critical"
        assert body["events"][0]["signals"], "timeline carries explainable signals"

    def test_confirm_records_the_device_as_reviewer(self, api: ApiHarness) -> None:
        token = api.pair_device(name="director-anna-phone")
        incident = self.incident(api)
        status, body = api.post(
            f"/api/v1/incidents/{incident.incident_id}/resolve",
            {"decision": "confirm", "note": "checked"},
            token=token,
        )
        assert status == 200
        assert body["status"] == "confirmed"
        assert body["review"]["reviewer"] == "director-anna-phone"
        assert api.risk_engine.open_incidents() == ()

    def test_dismiss_and_bad_requests(self, api: ApiHarness) -> None:
        token = api.pair_device()
        incident = self.incident(api)
        identifier = incident.incident_id
        assert (
            api.post(f"/api/v1/incidents/{identifier}/resolve", {"decision": "maybe"}, token=token)[
                0
            ]
            == 400
        )
        status, body = api.post(
            f"/api/v1/incidents/{identifier}/resolve", {"decision": "dismiss"}, token=token
        )
        assert status == 200 and body["status"] == "dismissed"
        assert (
            api.post(
                f"/api/v1/incidents/{identifier}/resolve", {"decision": "confirm"}, token=token
            )[0]
            == 404
        ), "already resolved incidents are no longer open"


class TestRealtime:
    def test_websocket_pushes_live_notifications(self, api: ApiHarness) -> None:
        token = api.pair_device()

        async def listen() -> list[dict]:
            uri = f"ws://127.0.0.1:{api.server.ws_port}/ws?token={token}"
            async with websockets.connect(uri) as connection:
                hello = json.loads(await asyncio.wait_for(connection.recv(), timeout=5))
                assert hello["kind"] == "hello"
                incident = make_safety_incident(severity=Severity.CRITICAL, confidence=0.9)
                api.notification_engine(incident)
                frame = json.loads(await asyncio.wait_for(connection.recv(), timeout=5))
                return [hello, frame]

        hello, frame = asyncio.run(listen())
        assert frame["kind"] == "notification"
        assert frame["payload"]["severity"] == "critical"
        assert hello["box_name"] == "guardian-edge-box"

    def test_websocket_rejects_unpaired_devices(self, api: ApiHarness) -> None:
        async def attempt() -> int:
            uri = f"ws://127.0.0.1:{api.server.ws_port}/ws?token=forged"
            async with websockets.connect(uri) as connection:
                try:
                    await asyncio.wait_for(connection.recv(), timeout=5)
                except websockets.ConnectionClosed as closed:
                    return closed.rcvd.code if closed.rcvd else 0
            return 0

        assert asyncio.run(attempt()) == 4401
