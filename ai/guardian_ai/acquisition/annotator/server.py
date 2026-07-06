"""Local annotation server: stdlib HTTP on localhost, no cloud, ever.

    GET  /                         the editor page (embedded HTML/JS)
    GET  /api/state                annotation + facts + undo/redo flags
    GET  /frame/<index>.jpg        one decoded frame as JPEG
    POST /api/apply {op, ...}      one edit operation on the session
    POST /api/undo | /api/redo | /api/save | /api/mark-annotated

Binds 127.0.0.1 only. Frames are decoded on demand with OpenCV
(headless); the browser is just a renderer for the session.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from guardian_ai.acquisition.annotator.page import PAGE_HTML
from guardian_ai.acquisition.annotator.session import AnnotationSession
from guardian_ai.acquisition.errors import AcquisitionError

logger = logging.getLogger(__name__)

_FRAME_RE = re.compile(r"^/frame/(\d+)\.jpg$")


class AnnotatorServer:
    """One session, one clip, one local port."""

    def __init__(self, session: AnnotationSession, port: int = 0) -> None:
        self._session = session
        self._lock = threading.Lock()
        handler = _build_handler(self)
        self._http = ThreadingHTTPServer(("127.0.0.1", port), handler)

    @property
    def port(self) -> int:
        return int(self._http.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def serve_forever(self) -> None:
        logger.info("annotator: %s (clip %s)", self.url, self._session.clip_id)
        self._http.serve_forever()

    def start_background(self) -> None:
        thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        thread.start()

    def shutdown(self) -> None:
        self._http.shutdown()
        self._http.server_close()

    # ------------------------------------------------------------ handlers

    def state(self) -> dict[str, Any]:
        with self._lock:
            annotation = self._session.annotation
            return {
                "annotation": annotation.to_dict(),
                "can_undo": self._session.can_undo(),
                "can_redo": self._session.can_redo(),
            }

    def frame_jpeg(self, index: int) -> bytes:
        import cv2

        with self._lock:
            capture = cv2.VideoCapture(str(self._session.video_path))
            try:
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
            finally:
                capture.release()
        if not ok:
            raise AcquisitionError(f"cannot decode frame {index}")
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise AcquisitionError(f"cannot encode frame {index}")
        return bytes(encoded.tobytes())

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("op", ""))
        with self._lock:
            session = self._session
            if operation == "add_box":
                session.add_box(
                    int(payload["frame"]),
                    str(payload["label"]),
                    tuple(float(v) for v in payload["box"]),  # type: ignore[arg-type]
                )
            elif operation == "update_box":
                session.update_box(
                    int(payload["frame"]),
                    int(payload["box_index"]),
                    label=payload.get("label"),
                    box=(
                        tuple(float(v) for v in payload["box"])  # type: ignore[arg-type]
                        if payload.get("box")
                        else None
                    ),
                )
            elif operation == "delete_box":
                session.delete_box(int(payload["frame"]), int(payload["box_index"]))
            elif operation == "add_event":
                session.add_event(str(payload["label"]), int(payload["start"]), int(payload["end"]))
            elif operation == "update_event":
                session.update_event(
                    int(payload["event_index"]),
                    label=payload.get("label"),
                    start_frame=payload.get("start"),
                    end_frame=payload.get("end"),
                )
            elif operation == "delete_event":
                session.delete_event(int(payload["event_index"]))
            else:
                raise AcquisitionError(f"unknown operation '{operation}'")
        return self.state()

    def command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if name == "undo":
                self._session.undo()
            elif name == "redo":
                self._session.redo()
            elif name == "save":
                self._session.save()
            elif name == "mark-annotated":
                self._session.mark_annotated(
                    by=str(payload.get("by", "")), notes=str(payload.get("notes", ""))
                )
            else:
                raise AcquisitionError(f"unknown command '{name}'")
        return self.state()


def _build_handler(server: AnnotatorServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug("annotator http: " + format, *args)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            try:
                if self.path == "/" or self.path.startswith("/?"):
                    self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if self.path == "/api/state":
                    self._send_json(200, server.state())
                    return
                match = _FRAME_RE.match(self.path)
                if match:
                    self._send(200, server.frame_jpeg(int(match.group(1))), "image/jpeg")
                    return
                self._send_json(404, {"error": f"no route {self.path}"})
            except AcquisitionError as exc:
                self._send_json(400, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/apply":
                    self._send_json(200, server.apply(payload))
                    return
                if self.path.startswith("/api/"):
                    self._send_json(200, server.command(self.path[len("/api/") :], payload))
                    return
                self._send_json(404, {"error": f"no route {self.path}"})
            except (AcquisitionError, json.JSONDecodeError, KeyError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
