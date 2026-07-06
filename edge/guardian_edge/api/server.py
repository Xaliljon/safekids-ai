"""Guardian Device API: the box's LAN surface for director devices (ADR-0015).

Pure composition — no engine is modified. The server:

- pairs devices (code → token) via PairingManager,
- pushes live notification payloads over WebSocket by *subscribing* to the
  existing LocalPushChannel,
- serves missed notifications from the existing durable outbox by line
  cursor (offline catch-up),
- forwards confirm/dismiss to the existing RiskEngine review API.

Transport is plain HTTP/WS on the trusted kindergarten LAN for V1; TLS
with box-local certificates is tracked in ADR-0015's consequences. The
server binds a LAN interface by design — phones must reach it.

Protocol v1 (JSON):
  POST /api/v1/pair                      {code, device_name} -> {token, box_name, ws_port, cursor}
  GET  /api/v1/notifications?after=N     Bearer token -> {cursor, notifications: [...]}
  GET  /api/v1/incidents/<id>            Bearer token -> incident + event timeline
  POST /api/v1/incidents/<id>/resolve    Bearer token, {decision, note} -> resolved incident
  GET  /api/v1/evidence                  Bearer token -> {evidence: [...]}
  GET  /api/v1/evidence/<id>             Bearer token -> evidence record
  GET  /api/v1/evidence/<id>/video?variant=original|overlay  Bearer token -> video/mp4
  GET  /api/v1/evidence/<id>/thumbnail   Bearer token -> image/jpeg
  WS   ws://host:<ws_port>/ws?token=...  frames: {kind: notification, payload: {...}}

Evidence (ADR-0017) is served ONLY to paired trusted devices, decrypted in
memory per request, and every access is written to the evidence audit
trail. There is no sharing/export surface — the LAN device API is the only
door, by design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import websockets
from websockets.asyncio.server import ServerConnection

from guardian_edge.api.pairing import PairingManager
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.domain.errors import UnknownIncidentError, VisionConfigurationError
from guardian_edge.domain.evidence import ClipVariant, Evidence
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.infrastructure.evidence.crypto import EvidenceCryptoError
from guardian_edge.infrastructure.evidence.store import (
    FileSystemEvidenceStore,
    UnknownEvidenceError,
)
from guardian_edge.infrastructure.notifications.local_push import (
    OUTBOX_FILE_NAME,
    LocalPushChannel,
)

logger = logging.getLogger(__name__)

DEFAULT_API_PORT = 8787
DEFAULT_WS_PORT = 8788
_WS_CLOSE_UNAUTHORIZED = 4401


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Parsed HTTP request handed to route methods."""

    path: str
    token: str
    body: dict[str, Any]


_Route = Callable[[RequestContext], tuple[HTTPStatus, dict[str, Any]]]
_MediaRoute = Callable[[RequestContext], tuple[HTTPStatus, str, bytes]]


def _media_error(status: HTTPStatus, message: str) -> tuple[HTTPStatus, str, bytes]:
    return status, "application/json", json.dumps({"error": message}).encode("utf-8")


def serialize_incident(incident: SafetyIncident) -> dict[str, Any]:
    """Incident details for the review screen: metadata + event timeline."""
    return {
        "incident_id": str(incident.incident_id),
        "type": incident.incident_type.value,
        "camera_id": incident.camera_id,
        "track_id": str(incident.track_id),
        "track_display_id": incident.track_display_id,
        "severity": incident.severity.value,
        "risk_confidence": incident.risk_confidence,
        "status": incident.status.value,
        "opened_at": incident.opened_at.isoformat(),
        "last_event_at": incident.last_event_at.isoformat(),
        "correlation_id": str(incident.correlation_id),
        "summary": incident.summary,
        "events": [
            {
                "observed_at": event.observed_at.isoformat(),
                "confidence": event.confidence,
                "signals": [
                    {"name": signal.name, "score": signal.score, "detail": signal.detail}
                    for signal in event.signals
                ],
            }
            for event in incident.events
        ],
        "review": (
            {
                "reviewer": incident.review.reviewer,
                "decided_at": incident.review.decided_at.isoformat(),
                "note": incident.review.note,
            }
            if incident.review is not None
            else None
        ),
    }


def serialize_evidence(evidence: Evidence) -> dict[str, Any]:
    """Evidence record for the wire (identifiers + clip facts, no media)."""
    return evidence.to_dict()


class DeviceApiServer:
    """LAN HTTP + WebSocket server for director devices."""

    def __init__(
        self,
        risk_engine: RiskEngine,
        push_channel: LocalPushChannel,
        outbox_dir: Path,
        pairing: PairingManager,
        box_name: str = "guardian-edge-box",
        host: str = "0.0.0.0",  # noqa: S104 - the device API must be reachable on the LAN (ADR-0015)
        api_port: int = DEFAULT_API_PORT,
        ws_port: int = DEFAULT_WS_PORT,
        evidence_store: FileSystemEvidenceStore | None = None,
    ) -> None:
        self._risk_engine = risk_engine
        self._outbox_path = outbox_dir / OUTBOX_FILE_NAME
        self._pairing = pairing
        self._evidence = evidence_store
        self._box_name = box_name
        self._host = host
        self._api_port = api_port
        self._ws_port = ws_port

        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._clients: set[ServerConnection] = set()
        self._started = threading.Event()
        push_channel.subscribe(self._on_notification)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start HTTP and WebSocket listeners. Idempotent."""
        if self._started.is_set():
            return
        self._http_server = ThreadingHTTPServer((self._host, self._api_port), self._make_handler())
        self._api_port = self._http_server.server_address[1]
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever, name="device-api-http", daemon=True
        )
        self._http_thread.start()

        ready = threading.Event()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)

            async def serve() -> None:
                server = await websockets.serve(self._ws_handler, self._host, self._ws_port)
                port = server.sockets[0].getsockname()[1] if server.sockets else self._ws_port
                self._ws_port = port
                ready.set()

            loop.run_until_complete(serve())
            loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, name="device-api-ws", daemon=True)
        self._loop_thread.start()
        ready.wait(timeout=10.0)
        self._started.set()
        logger.info(
            "device API up: http://%s:%d (ws :%d), pairing code in logs above",
            self._host,
            self._api_port,
            self._ws_port,
        )

    def stop(self) -> None:
        """Stop listeners. Idempotent."""
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=5.0)
            self._loop = None
        self._started.clear()

    @property
    def api_port(self) -> int:
        return self._api_port

    @property
    def ws_port(self) -> int:
        return self._ws_port

    # ---------------------------------------------------------- notifications

    def _on_notification(self, payload: dict[str, Any]) -> None:
        """LocalPushChannel subscriber: fan out to connected devices."""
        loop = self._loop
        if loop is None:
            return
        frame = json.dumps({"kind": "notification", "payload": payload})
        loop.call_soon_threadsafe(self._broadcast_on_loop, frame)

    def _broadcast_on_loop(self, frame: str) -> None:
        for connection in tuple(self._clients):
            asyncio.ensure_future(self._send_quietly(connection, frame))  # noqa: RUF006

    async def _send_quietly(self, connection: ServerConnection, frame: str) -> None:
        try:
            await connection.send(frame)
        except Exception:
            self._clients.discard(connection)

    async def _ws_handler(self, connection: ServerConnection) -> None:
        path = connection.request.path if connection.request is not None else ""
        query = parse_qs(urlparse(path).query)
        token = (query.get("token") or [""])[0]
        if not self._pairing.is_trusted(token):
            await connection.close(code=_WS_CLOSE_UNAUTHORIZED, reason="unpaired device")
            return
        self._clients.add(connection)
        try:
            await connection.send(
                json.dumps({"kind": "hello", "box_name": self._box_name, "cursor": self._cursor()})
            )
            async for _ in connection:  # devices only listen; drain pings/messages
                pass
        finally:
            self._clients.discard(connection)

    def _cursor(self) -> int:
        if not self._outbox_path.is_file():
            return 0
        return len(self._outbox_path.read_text(encoding="utf-8").splitlines())

    def _notifications_after(self, after: int) -> tuple[int, list[dict[str, Any]]]:
        if not self._outbox_path.is_file():
            return 0, []
        lines = self._outbox_path.read_text(encoding="utf-8").splitlines()
        payloads = [json.loads(line) for line in lines[max(after, 0) :] if line.strip()]
        return len(lines), payloads

    # ------------------------------------------------------------- HTTP side

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                if self.path == "/api/v1/pair":
                    self._handle(server._pair, authenticated=False)
                elif self.path.startswith("/api/v1/incidents/") and self.path.endswith("/resolve"):
                    self._handle(server._resolve)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                clean = urlparse(self.path).path
                if self.path.startswith("/api/v1/notifications"):
                    self._handle(server._sync)
                elif self.path.startswith("/api/v1/incidents/"):
                    self._handle(server._incident)
                elif clean.startswith("/api/v1/evidence/") and clean.endswith("/video"):
                    self._handle_media(server._evidence_video)
                elif clean.startswith("/api/v1/evidence/") and clean.endswith("/thumbnail"):
                    self._handle_media(server._evidence_thumbnail)
                elif clean.startswith("/api/v1/evidence/"):
                    self._handle(server._evidence_one)
                elif clean == "/api/v1/evidence":
                    self._handle(server._evidence_list)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

            # -- plumbing

            def _handle(self, route: _Route, authenticated: bool = True) -> None:
                try:
                    token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                    if authenticated and not server._pairing.is_trusted(token):
                        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unpaired device"})
                        return
                    context = RequestContext(path=self.path, token=token, body=self._body())
                    status, body = route(context)
                    self._json(status, body)
                except Exception:
                    logger.exception("device API request failed: %s", self.path)
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

            def _handle_media(self, route: _MediaRoute) -> None:
                """Like _handle, but the route answers with raw media bytes."""
                try:
                    token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                    if not server._pairing.is_trusted(token):
                        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unpaired device"})
                        return
                    context = RequestContext(path=self.path, token=token, body={})
                    status, content_type, payload = route(context)
                    self.send_response(int(status))
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    # Evidence never leaves the app: no caching proxies.
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    logger.exception("device API media request failed: %s", self.path)
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    return {}
                parsed = json.loads(self.rfile.read(length).decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {}

            def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                return  # our logging, not http.server's

        return Handler

    # -------------------------------------------------------------- routes

    def _pair(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        body = request.body
        token = self._pairing.pair(str(body.get("code", "")), str(body.get("device_name", "")))
        if token is None:
            return HTTPStatus.FORBIDDEN, {"error": "invalid pairing code"}
        return HTTPStatus.OK, {
            "token": token,
            "box_name": self._box_name,
            "ws_port": self._ws_port,
            "cursor": self._cursor(),
        }

    def _sync(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        query = parse_qs(urlparse(request.path).query)
        after = int((query.get("after") or ["0"])[0])
        cursor, payloads = self._notifications_after(after)
        return HTTPStatus.OK, {"cursor": cursor, "notifications": payloads}

    def _incident(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        incident_id = urlparse(request.path).path.rsplit("/", 1)[-1]
        for incident in self._risk_engine.open_incidents():
            if str(incident.incident_id) == incident_id:
                return HTTPStatus.OK, serialize_incident(incident)
        return HTTPStatus.NOT_FOUND, {"error": "incident is not open on this box"}

    def _resolve(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        path = urlparse(request.path).path
        incident_id = path.removesuffix("/resolve").rsplit("/", 1)[-1]
        decision = str(request.body.get("decision", ""))
        device = self._pairing.device_for(request.token)
        reviewer = device.device_name if device is not None else "unknown-device"
        note = str(request.body.get("note", ""))
        try:
            identifier = UUID(incident_id)
            if decision == "confirm":
                resolved = self._risk_engine.confirm(identifier, reviewer=reviewer, note=note)
            elif decision == "dismiss":
                resolved = self._risk_engine.dismiss(identifier, reviewer=reviewer, note=note)
            else:
                return HTTPStatus.BAD_REQUEST, {"error": "decision must be confirm or dismiss"}
        except (ValueError, VisionConfigurationError) as exc:
            return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
        except UnknownIncidentError as exc:
            return HTTPStatus.NOT_FOUND, {"error": str(exc)}
        if self._evidence is not None:
            # Retention applies the right lifetime once the human decides.
            self._evidence.update_incident_status(resolved.incident_id, resolved.status)
        return HTTPStatus.OK, serialize_incident(resolved)

    # ---------------------------------------------------- evidence routes

    def _device_name(self, token: str) -> str:
        device = self._pairing.device_for(token)
        return device.device_name if device is not None else "unknown-device"

    def _evidence_list(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        if self._evidence is None:
            return HTTPStatus.NOT_FOUND, {"error": "evidence is not enabled on this box"}
        records = [serialize_evidence(record) for record in self._evidence.list_evidence()]
        return HTTPStatus.OK, {"evidence": records}

    def _find_evidence(
        self, request: RequestContext, suffix: str = ""
    ) -> Evidence | tuple[HTTPStatus, dict[str, Any]]:
        if self._evidence is None:
            return HTTPStatus.NOT_FOUND, {"error": "evidence is not enabled on this box"}
        path = urlparse(request.path).path.removesuffix(suffix).rstrip("/")
        raw_id = path.rsplit("/", 1)[-1]
        try:
            return self._evidence.get(UUID(raw_id))
        except (ValueError, UnknownEvidenceError):
            return HTTPStatus.NOT_FOUND, {"error": "unknown evidence"}

    def _evidence_one(self, request: RequestContext) -> tuple[HTTPStatus, dict[str, Any]]:
        store = self._evidence
        found = self._find_evidence(request)
        if not isinstance(found, Evidence) or store is None:
            return (
                found
                if not isinstance(found, Evidence)
                else (
                    HTTPStatus.NOT_FOUND,
                    {"error": "evidence is not enabled on this box"},
                )
            )
        store.audit("read", found.evidence_id, self._device_name(request.token))
        return HTTPStatus.OK, serialize_evidence(found)

    def _evidence_video(self, request: RequestContext) -> tuple[HTTPStatus, str, bytes]:
        store = self._evidence
        found = self._find_evidence(request, suffix="/video")
        if store is None or not isinstance(found, Evidence):
            status, body = (
                found
                if not isinstance(found, Evidence)
                else (
                    HTTPStatus.NOT_FOUND,
                    {"error": "evidence is not enabled on this box"},
                )
            )
            return _media_error(status, str(body.get("error", "not found")))
        query = parse_qs(urlparse(request.path).query)
        raw_variant = (query.get("variant") or ["original"])[0]
        try:
            variant = ClipVariant(raw_variant)
        except ValueError:
            return _media_error(HTTPStatus.BAD_REQUEST, "variant must be original or overlay")
        try:
            payload = store.open_clip(found, variant)
        except (UnknownEvidenceError, EvidenceCryptoError, OSError) as exc:
            return _media_error(HTTPStatus.NOT_FOUND, str(exc))
        store.audit(
            "download",
            found.evidence_id,
            self._device_name(request.token),
            {"variant": variant.value},
        )
        return HTTPStatus.OK, "video/mp4", payload

    def _evidence_thumbnail(self, request: RequestContext) -> tuple[HTTPStatus, str, bytes]:
        store = self._evidence
        found = self._find_evidence(request, suffix="/thumbnail")
        if store is None or not isinstance(found, Evidence):
            status, body = (
                found
                if not isinstance(found, Evidence)
                else (
                    HTTPStatus.NOT_FOUND,
                    {"error": "evidence is not enabled on this box"},
                )
            )
            return _media_error(status, str(body.get("error", "not found")))
        try:
            payload = store.open_thumbnail(found)
        except (UnknownEvidenceError, EvidenceCryptoError, OSError) as exc:
            return _media_error(HTTPStatus.NOT_FOUND, str(exc))
        store.audit("thumbnail", found.evidence_id, self._device_name(request.token))
        return HTTPStatus.OK, "image/jpeg", payload
