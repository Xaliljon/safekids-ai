"""Annotation tool: the session brain and the local HTTP server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from acquisition_fixtures import build_workspace

from guardian_ai.acquisition.annotations import load_annotation
from guardian_ai.acquisition.annotator.server import AnnotatorServer
from guardian_ai.acquisition.annotator.session import AnnotationSession
from guardian_ai.acquisition.errors import AcquisitionError, AnnotationFormatError
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.workspace import DatasetWorkspace


@pytest.fixture()
def workspace(tmp_path: Path) -> DatasetWorkspace:
    return build_workspace(tmp_path / "ws", clip_count=1)


@pytest.fixture()
def session(workspace: DatasetWorkspace) -> AnnotationSession:
    return AnnotationSession(workspace, workspace.clip_ids()[0])


class TestSession:
    def test_box_editing_add_update_delete(self, session: AnnotationSession) -> None:
        session.add_box(7, "child", (0.4, 0.4, 0.2, 0.3))
        frame = next(f for f in session.annotation.frames if f.index == 7)
        assert frame.boxes[0].label == "child"

        session.update_box(7, 0, label="adult", box=(0.5, 0.5, 0.1, 0.2))
        frame = next(f for f in session.annotation.frames if f.index == 7)
        assert frame.boxes[0].label == "adult"
        assert frame.boxes[0].box == (0.5, 0.5, 0.1, 0.2)

        session.delete_box(7, 0)
        assert all(f.index != 7 for f in session.annotation.frames)

    def test_event_timeline_editing(self, session: AnnotationSession) -> None:
        before = len(session.annotation.events)
        session.add_event("walking", 0, 8)
        assert len(session.annotation.events) == before + 1
        session.update_event(0, end_frame=9)
        assert session.annotation.events[0].end_frame == 9
        session.delete_event(0)
        assert len(session.annotation.events) == before

    def test_invalid_edits_are_rejected_and_leave_no_trace(
        self, session: AnnotationSession
    ) -> None:
        snapshot = session.annotation
        with pytest.raises(AnnotationFormatError):
            session.add_box(7, "fall", (0.1, 0.1, 0.2, 0.2))  # event label as box
        with pytest.raises(AnnotationFormatError):
            session.add_event("fall", 50, 10)  # starts after end
        with pytest.raises(AcquisitionError):
            session.delete_box(7, 0)  # nothing there
        assert session.annotation == snapshot
        assert not session.can_redo()

    def test_undo_redo(self, session: AnnotationSession) -> None:
        base_events = len(session.annotation.events)
        session.add_event("walking", 0, 5)
        session.add_box(3, "person", (0.1, 0.1, 0.2, 0.2))
        assert session.undo()  # drop the box
        assert session.undo()  # drop the event
        assert len(session.annotation.events) == base_events
        assert session.redo()
        assert len(session.annotation.events) == base_events + 1
        assert session.redo() and not session.can_redo()
        assert not session.redo()

    def test_new_edit_clears_redo(self, session: AnnotationSession) -> None:
        session.add_event("walking", 0, 5)
        session.undo()
        session.add_event("sitting", 1, 4)
        assert not session.can_redo()

    def test_autosave_persists_every_edit(
        self, workspace: DatasetWorkspace, session: AnnotationSession
    ) -> None:
        session.add_event("walking", 2, 6)
        on_disk = load_annotation(workspace.annotation_path(session.clip_id))
        assert any(event.label == "walking" for event in on_disk.events)
        session.undo()
        on_disk = load_annotation(workspace.annotation_path(session.clip_id))
        assert not any(event.label == "walking" for event in on_disk.events)

    def test_explicit_save_is_the_guardian_export(self, session: AnnotationSession) -> None:
        path = session.save()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["schema"] == "guardian-video-annotation/1"

    def test_mark_annotated_advances_workflow(
        self, workspace: DatasetWorkspace, session: AnnotationSession
    ) -> None:
        session.mark_annotated(by="Annotator A", notes="one pass")
        assert ReviewWorkflow(workspace.root).state() is ReviewState.ANNOTATED

    def test_history_limit_is_bounded(self, session: AnnotationSession) -> None:
        for _ in range(210):
            session.add_event("walking", 0, 1)
        undone = 0
        while session.undo():
            undone += 1
        assert undone <= 200


class TestServer:
    @pytest.fixture()
    def server(self, session: AnnotationSession) -> Any:
        server = AnnotatorServer(session, port=0)
        server.start_background()
        yield server
        server.shutdown()

    @staticmethod
    def _get(server: AnnotatorServer, path: str) -> bytes:
        return urllib.request.urlopen(server.url.rstrip("/") + path, timeout=5).read()

    @staticmethod
    def _post(server: AnnotatorServer, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            server.url.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        return json.loads(urllib.request.urlopen(request, timeout=5).read())

    def test_page_and_state(self, server: AnnotatorServer) -> None:
        page = self._get(server, "/").decode("utf-8")
        assert "GUARDIAN ANNOTATOR" in page
        state = json.loads(self._get(server, "/api/state"))
        assert state["annotation"]["schema"] == "guardian-video-annotation/1"
        assert state["can_undo"] is False

    def test_frame_stepping_serves_jpegs(self, server: AnnotatorServer) -> None:
        for index in (0, 5, 29):
            jpeg = self._get(server, f"/frame/{index}.jpg")
            assert jpeg[:2] == b"\xff\xd8"

    def test_apply_undo_redo_save_over_http(self, server: AnnotatorServer) -> None:
        state = self._post(
            server,
            "/api/apply",
            {"op": "add_box", "frame": 4, "label": "person", "box": [0.2, 0.2, 0.3, 0.4]},
        )
        assert state["can_undo"] is True
        state = self._post(server, "/api/undo", {})
        assert state["can_redo"] is True
        state = self._post(server, "/api/redo", {})
        assert any(frame["index"] == 4 for frame in state["annotation"]["frames"])
        self._post(server, "/api/save", {})

    def test_rejected_edits_return_400(self, server: AnnotatorServer) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            self._post(
                server,
                "/api/apply",
                {"op": "add_box", "frame": 4, "label": "face", "box": [0.1, 0.1, 0.2, 0.2]},
            )
        assert excinfo.value.code == 400
        assert "error" in json.loads(excinfo.value.read())

    def test_unknown_routes_and_ops(self, server: AnnotatorServer) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            self._get(server, "/api/nope")
        assert excinfo.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            self._post(server, "/api/apply", {"op": "teleport"})
        assert excinfo.value.code == 400


class TestServerEdges:
    def test_unknown_command_is_400(self, session: AnnotationSession) -> None:
        server = AnnotatorServer(session, port=0)
        server.start_background()
        try:
            request = urllib.request.Request(
                server.url.rstrip("/") + "/api/teleport", data=b"{}", method="POST"
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)
            assert excinfo.value.code == 400
        finally:
            server.shutdown()

    def test_mark_annotated_over_http(
        self, workspace: DatasetWorkspace, session: AnnotationSession
    ) -> None:
        server = AnnotatorServer(session, port=0)
        server.start_background()
        try:
            request = urllib.request.Request(
                server.url.rstrip("/") + "/api/mark-annotated",
                data=json.dumps({"by": "Annotator A", "notes": "done"}).encode(),
                method="POST",
            )
            urllib.request.urlopen(request, timeout=5)
        finally:
            server.shutdown()
        assert ReviewWorkflow(workspace.root).state() is ReviewState.ANNOTATED

    def test_frame_out_of_range_is_400(self, session: AnnotationSession) -> None:
        server = AnnotatorServer(session, port=0)
        server.start_background()
        try:
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(server.url + "frame/9999.jpg", timeout=5)
            assert excinfo.value.code == 400
        finally:
            server.shutdown()
