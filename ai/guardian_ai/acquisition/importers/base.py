"""Importer port + the one shared import flow.

An importer only knows two things about its raw dataset: how to discover
clips and how to express their annotations in Guardian terms. Everything
else — normalization, validation, metadata, split assignment, workflow
state — is the same flow for every source, so no importer can skip a gate.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from guardian_ai.acquisition.annotations import ClipAnnotation, EventSpan, FrameAnnotation
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.video import (
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    VideoInfo,
    frames_from_images,
    normalize_video,
)
from guardian_ai.acquisition.workspace import DatasetWorkspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceClip:
    """One clip as the raw dataset describes it, before normalization.

    Frame numbers in ``events``/``frames`` are on the SOURCE timeline at
    ``source_fps``; the flow maps them onto the normalized timeline.
    Exactly one of ``video`` or ``image_sequence`` is set.
    """

    clip_id: str
    video: Path | None = None
    image_sequence: tuple[Path, ...] = ()
    source_fps: float | None = None  # None -> probe the source video
    events: tuple[EventSpan, ...] = ()  # source-timeline frames
    frames: tuple[FrameAnnotation, ...] = ()  # source-timeline, pixel boxes already normalized
    attributes: dict[str, str] = field(default_factory=dict)
    split_group: str | None = None
    """What must not straddle train/val/test.

    Splitting by clip is not enough, and the candidate provenance review is
    the proof: every validation scene was also a training scene, so
    ``val_f1`` hit 1.0 at epoch 3 and measured same-room recognition rather
    than generalization. The group is whatever recurs across clips and lets
    a model memorize instead — the room and fixed camera for Le2i, the
    subject for UR Fall and GMDCSA24. ``None`` falls back to the clip id,
    which is only correct when every clip is genuinely independent."""


class DatasetImporter(Protocol):
    """What a source must provide; the flow provides everything else."""

    source: str
    license_note: str

    def discover(self, raw_dir: Path) -> list[SourceClip]: ...


@dataclass(frozen=True, slots=True)
class ImportResult:
    source: str
    imported: list[str]
    splits: dict[str, str]  # clip_id -> split


def run_import(
    importer: DatasetImporter, raw_dir: Path, workspace: DatasetWorkspace
) -> ImportResult:
    """The shared flow: discover -> normalize -> convert -> register."""
    if not raw_dir.is_dir():
        raise ImporterError(f"raw dataset directory missing: {raw_dir}")
    clips = importer.discover(raw_dir)
    if not clips:
        raise ImporterError(f"'{importer.source}' found no clips under {raw_dir} — wrong layout?")
    imported: list[str] = []
    splits: dict[str, str] = {}
    for clip in clips:
        with tempfile.TemporaryDirectory(prefix="guardian-import-") as staging:
            normalized = Path(staging) / f"{clip.clip_id}.mp4"
            source_fps, info = _normalize(clip, normalized)
            annotation = _to_guardian(clip, info, source_fps, importer.source)
            metadata: dict[str, Any] = {
                "source_dataset": importer.source,
                "license_note": importer.license_note,
                "original": str(
                    clip.video.name if clip.video else f"{len(clip.image_sequence)} images"
                ),
                "source_fps": source_fps,
                "normalized": {
                    "width": info.width,
                    "height": info.height,
                    "fps": TARGET_FPS,
                    "frame_count": info.frame_count,
                },
                **{f"attr_{key}": value for key, value in clip.attributes.items()},
            }
            split = workspace.add_clip(
                clip.clip_id, normalized, annotation, metadata, split_group=clip.split_group
            )
        imported.append(clip.clip_id)
        splits[clip.clip_id] = split
        logger.info("imported %s -> %s split", clip.clip_id, split)
    workflow = ReviewWorkflow(workspace.root)
    if workflow.state() is None:
        workflow.record(
            ReviewState.IMPORTED,
            by=f"importer:{importer.source}",
            notes=f"{len(imported)} clip(s) from {raw_dir.name}",
        )
    return ImportResult(source=importer.source, imported=imported, splits=splits)


def _normalize(clip: SourceClip, destination: Path) -> tuple[float, VideoInfo]:
    if clip.video is not None:
        from guardian_ai.acquisition.video import probe

        source_fps = clip.source_fps or probe(clip.video).fps or float(TARGET_FPS)
        info = normalize_video(clip.video, destination)
    elif clip.image_sequence:
        source_fps = clip.source_fps or float(TARGET_FPS)
        info = frames_from_images(list(clip.image_sequence), destination)
    else:
        raise ImporterError(f"clip '{clip.clip_id}' has neither video nor image sequence")
    return source_fps, info


def _to_guardian(
    clip: SourceClip, info: VideoInfo, source_fps: float, source: str
) -> ClipAnnotation:
    """Map source-timeline annotations onto the normalized clip."""
    from guardian_ai.acquisition.video import map_frame

    last = info.frame_count - 1

    def mapped(frame: int) -> int:
        return min(max(map_frame(frame, source_fps), 0), last)

    events = tuple(
        EventSpan(
            label=event.label,
            start_frame=mapped(event.start_frame),
            end_frame=mapped(event.end_frame),
            confidence=event.confidence,
        )
        for event in clip.events
    )
    frames: dict[int, FrameAnnotation] = {}
    for frame in clip.frames:
        index = mapped(frame.index)
        if index in frames:  # fps downsampling collapsed two source frames
            continue
        frames[index] = FrameAnnotation(index=index, boxes=frame.boxes)
    return ClipAnnotation(
        clip_id=clip.clip_id,
        fps=float(TARGET_FPS),
        width=TARGET_WIDTH,
        height=TARGET_HEIGHT,
        frame_count=info.frame_count,
        frames=tuple(sorted(frames.values(), key=lambda item: item.index)),
        events=events,
        attributes={"source_dataset": source, **clip.attributes},
    )
