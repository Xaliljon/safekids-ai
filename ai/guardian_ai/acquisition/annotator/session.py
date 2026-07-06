"""The annotation session: every edit validated, undoable, autosaved.

The session is the tool's whole brain: box and event editing, an
undo/redo history, autosave after every mutation, and export in Guardian
format (which is simply its native format — there is no other). The web
UI is a thin renderer over this class.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from guardian_ai.acquisition.annotations import (
    ClipAnnotation,
    EventSpan,
    FrameAnnotation,
    FrameBox,
    load_annotation,
    save_annotation,
    validate_annotation,
)
from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.workspace import DatasetWorkspace

_HISTORY_LIMIT = 200


class AnnotationSession:
    """Edit one clip's annotation with undo/redo and autosave."""

    def __init__(self, workspace: DatasetWorkspace, clip_id: str, autosave: bool = True) -> None:
        self._workspace = workspace
        self._clip_id = clip_id
        self._path = workspace.annotation_path(clip_id)
        self._annotation = load_annotation(self._path)
        self._undo: list[ClipAnnotation] = []
        self._redo: list[ClipAnnotation] = []
        self._autosave = autosave

    # --------------------------------------------------------------- facts

    @property
    def clip_id(self) -> str:
        return self._clip_id

    @property
    def annotation(self) -> ClipAnnotation:
        return self._annotation

    @property
    def video_path(self) -> Path:
        return self._workspace.video_path(self._clip_id)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    # --------------------------------------------------------------- boxes

    def add_box(
        self,
        frame_index: int,
        label: str,
        box: tuple[float, float, float, float],
        confidence: float = 1.0,
    ) -> None:
        frames = {frame.index: frame for frame in self._annotation.frames}
        existing = frames.get(frame_index, FrameAnnotation(index=frame_index))
        frames[frame_index] = replace(
            existing,
            boxes=(*existing.boxes, FrameBox(label=label, box=box, confidence=confidence)),
        )
        self._apply(replace(self._annotation, frames=_sorted_frames(frames)))

    def update_box(
        self,
        frame_index: int,
        box_index: int,
        label: str | None = None,
        box: tuple[float, float, float, float] | None = None,
    ) -> None:
        frames = {frame.index: frame for frame in self._annotation.frames}
        frame = self._require_frame(frames, frame_index)
        boxes = list(frame.boxes)
        current = self._require_box(boxes, frame_index, box_index)
        boxes[box_index] = replace(
            current,
            label=label if label is not None else current.label,
            box=box if box is not None else current.box,
        )
        frames[frame_index] = replace(frame, boxes=tuple(boxes))
        self._apply(replace(self._annotation, frames=_sorted_frames(frames)))

    def delete_box(self, frame_index: int, box_index: int) -> None:
        frames = {frame.index: frame for frame in self._annotation.frames}
        frame = self._require_frame(frames, frame_index)
        boxes = list(frame.boxes)
        self._require_box(boxes, frame_index, box_index)
        del boxes[box_index]
        if boxes:
            frames[frame_index] = replace(frame, boxes=tuple(boxes))
        else:
            del frames[frame_index]
        self._apply(replace(self._annotation, frames=_sorted_frames(frames)))

    # -------------------------------------------------------------- events

    def add_event(
        self, label: str, start_frame: int, end_frame: int, confidence: float = 1.0
    ) -> None:
        event = EventSpan(label, start_frame, end_frame, confidence)
        events = tuple(sorted((*self._annotation.events, event), key=lambda item: item.start_frame))
        self._apply(replace(self._annotation, events=events))

    def update_event(
        self,
        event_index: int,
        label: str | None = None,
        start_frame: int | None = None,
        end_frame: int | None = None,
    ) -> None:
        events = list(self._annotation.events)
        current = self._require_event(events, event_index)
        events[event_index] = replace(
            current,
            label=label if label is not None else current.label,
            start_frame=start_frame if start_frame is not None else current.start_frame,
            end_frame=end_frame if end_frame is not None else current.end_frame,
        )
        self._apply(replace(self._annotation, events=tuple(events)))

    def delete_event(self, event_index: int) -> None:
        events = list(self._annotation.events)
        self._require_event(events, event_index)
        del events[event_index]
        self._apply(replace(self._annotation, events=tuple(events)))

    # ------------------------------------------------------------- history

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._annotation)
        self._annotation = self._undo.pop()
        self._save()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._annotation)
        self._annotation = self._redo.pop()
        self._save()
        return True

    def save(self) -> Path:
        """Explicit save — also the Guardian-format export (same thing)."""
        self._save()
        return self._path

    def mark_annotated(self, by: str, notes: str = "") -> None:
        """Advance the workspace to ANNOTATED once a human finished a pass."""
        ReviewWorkflow(self._workspace.root).record(ReviewState.ANNOTATED, by=by, notes=notes)

    # ----------------------------------------------------------- internals

    def _apply(self, candidate: ClipAnnotation) -> None:
        validate_annotation(candidate)  # invalid edits never enter history
        self._undo.append(self._annotation)
        if len(self._undo) > _HISTORY_LIMIT:
            del self._undo[0]
        self._redo.clear()
        self._annotation = candidate
        if self._autosave:
            self._save()

    def _save(self) -> None:
        save_annotation(self._annotation, self._path)

    @staticmethod
    def _require_frame(frames: dict[int, FrameAnnotation], index: int) -> FrameAnnotation:
        if index not in frames:
            raise AcquisitionError(f"frame {index} has no annotations")
        return frames[index]

    @staticmethod
    def _require_box(boxes: list[FrameBox], frame_index: int, box_index: int) -> FrameBox:
        if not 0 <= box_index < len(boxes):
            raise AcquisitionError(f"frame {frame_index} has no box #{box_index}")
        return boxes[box_index]

    @staticmethod
    def _require_event(events: list[EventSpan], index: int) -> EventSpan:
        if not 0 <= index < len(events):
            raise AcquisitionError(f"no event #{index}")
        return events[index]


def _sorted_frames(frames: dict[int, FrameAnnotation]) -> tuple[FrameAnnotation, ...]:
    return tuple(sorted(frames.values(), key=lambda frame: frame.index))
