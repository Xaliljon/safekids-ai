"""Shared builders for dataset acquisition tests.

Synthetic videos (moving rectangle "person" who ends up lying), raw
dataset layouts in each importer's documented shape, and ready-made
guardian_dataset_v1 workspaces — everything tiny and deterministic.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np

from guardian_ai.acquisition.annotations import (
    ClipAnnotation,
    EventSpan,
    FrameAnnotation,
    FrameBox,
)
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.video import TARGET_FPS, TARGET_HEIGHT, TARGET_WIDTH
from guardian_ai.acquisition.workspace import DatasetWorkspace, WorkspaceManifest


def write_video(
    path: Path,
    frames: int = 30,
    size: tuple[int, int] = (320, 240),
    fps: float = 30.0,
    seed: int = 0,
    still: bool = False,
) -> Path:
    """A tiny synthetic clip: a moving rectangle that falls over."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    rng = np.random.default_rng(seed)
    for index in range(frames):
        frame = np.full((size[1], size[0], 3), 110, dtype=np.uint8)
        offset = 0 if still else index
        x = 20 + offset * 2
        if index < frames * 0.6 or still:
            cv2.rectangle(frame, (x, 40), (x + 30, size[1] - 40), (60, 60, 220), -1)
        else:
            cv2.rectangle(frame, (x, size[1] - 60), (x + 70, size[1] - 30), (60, 60, 220), -1)
        if not still:
            frame += rng.integers(0, 6, frame.shape, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def make_manifest(name: str = "test-dataset", consent: str = "research/terms") -> WorkspaceManifest:
    return WorkspaceManifest(
        name=name,
        description="acquisition test dataset",
        collected_by="tests",
        consent_reference=consent,
        contains_minors=False,
        anonymized=True,
    )


def normalized_clip_annotation(
    clip_id: str,
    frame_count: int = 30,
    events: tuple[EventSpan, ...] = (),
    frames: tuple[FrameAnnotation, ...] = (),
) -> ClipAnnotation:
    return ClipAnnotation(
        clip_id=clip_id,
        fps=float(TARGET_FPS),
        width=TARGET_WIDTH,
        height=TARGET_HEIGHT,
        frame_count=frame_count,
        frames=frames,
        events=events,
    )


def build_workspace(
    root: Path,
    clip_count: int = 3,
    manifest: WorkspaceManifest | None = None,
    review_to: ReviewState | None = ReviewState.IMPORTED,
) -> DatasetWorkspace:
    """A workspace with normalized-shaped clips, boxes and fall events."""
    workspace = DatasetWorkspace.create(root, manifest or make_manifest())
    staging = root.parent / f".clips-{root.name}"
    staging.mkdir(exist_ok=True)
    for index in range(clip_count):
        clip_id = f"clip-{index:03d}"
        video = write_video(
            staging / f"{clip_id}.mp4",
            frames=30,
            size=(TARGET_WIDTH, TARGET_HEIGHT),
            fps=float(TARGET_FPS),
            seed=index,
        )
        annotation = normalized_clip_annotation(
            clip_id,
            events=(EventSpan("fall", 10, 15), EventSpan("lying", 16, 25)),
            frames=(
                FrameAnnotation(
                    index=5,
                    boxes=(FrameBox("person", (0.1, 0.2, 0.2, 0.5)),),
                ),
                FrameAnnotation(
                    index=12,
                    boxes=(FrameBox("person", (0.3, 0.5, 0.3, 0.25)),),
                ),
            ),
        )
        workspace.add_clip(
            clip_id,
            video,
            annotation,
            metadata={"source_dataset": "tests", "attr_camera_angle": "side"},
        )
    if review_to is not None:
        workflow = ReviewWorkflow(root)
        for state in ReviewState:
            workflow.record(state, by="tests", notes="fixture")
            if state is review_to:
                break
    return workspace


def approve_workspace(workspace: DatasetWorkspace, by: str = "Reviewer") -> None:
    workflow = ReviewWorkflow(workspace.root)
    if workflow.state() is None:
        workflow.record(ReviewState.IMPORTED, by=by, notes="fixture")
    current_index = list(ReviewState).index(workflow.state())  # type: ignore[arg-type]
    for state in (ReviewState.ANNOTATED, ReviewState.REVIEWED, ReviewState.APPROVED):
        if list(ReviewState).index(state) <= current_index:
            continue
        workflow.record(state, by=by, notes=f"fixture -> {state.value}")


# ------------------------------------------------------- raw dataset layouts


def build_urfall_raw(root: Path) -> Path:
    write_video(root / "videos" / "fall-01-cam0.mp4", seed=1)
    write_video(root / "videos" / "adl-01-cam0.mp4", seed=2)
    rows = []
    for frame in range(30):
        label = -1 if frame < 15 else (0 if frame < 21 else 1)
        rows.append(f"fall-01-cam0,{frame},{label}")
    for frame in range(30):
        rows.append(f"adl-01-cam0,{frame},-1")
    (root / "urfall-cam0-falls.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def build_le2i_raw(root: Path) -> Path:
    scene = root / "Coffee_room"
    write_video(scene / "Videos" / "video (1).avi", seed=3)
    lines = ["16", "21"]
    for frame in range(30):
        x = 20 + frame * 2
        lines.append(f"{frame},{x},40,{x + 30},200")
    (scene / "Annotation_files").mkdir(parents=True, exist_ok=True)
    (scene / "Annotation_files" / "video (1).txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return root


def build_gmdcsa24_raw(root: Path) -> Path:
    """The layout GMDCSA24 actually ships, header spacing included.

    The previous fixture built `Fall/Subject1/*.mp4` + `annotations.json`,
    which is what the importer assumed and not what the dataset publishes.
    Tests passed against an invented archive; the real one could not be
    imported at all. The header below keeps the shipped CSV's leading space
    in " Classes" and its "Falling (SW)" subtype, because both are what the
    parser has to survive.
    """
    header = "File Name,Length (seconds),Time of Recording,Attire,Description, Classes\n"
    for subject in ("Subject 1", "Subject 2"):
        write_video(root / subject / "Fall" / "01.mp4", seed=4)
        (root / subject / "Fall.csv").write_text(
            header + "01.mp4,06, Day (Light On),Full T-shirt,Falling from a chair,"
            "Falling (SW)[0.5 to 0.8]; Sitting[0 to 0.5]\n",
            encoding="utf-8",
        )
        write_video(root / subject / "ADL" / "01.mp4", seed=5)
        (root / subject / "ADL.csv").write_text(
            header + "01.mp4,08, Day (Light On), Full T-shirt,Sitting then lying down,"
            "Sitting[0 to 0.3]; Sleeping[0.4 to 0.9]\n",
            encoding="utf-8",
        )
    return root


def build_evidence_export(root: Path, incident_id: str | None = None) -> tuple[Path, dict]:
    incident_id = incident_id or str(uuid.uuid4())
    record = {
        "incident_id": incident_id,
        "track_id": str(uuid.uuid4()),
        "detection_id": str(uuid.uuid4()),
        "frame_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "camera_id": "cam-entrance",
        "incident_severity": "critical",
        "incident_opened_at": "2026-07-06T09:00:00+00:00",
    }
    incident_dir = root / incident_id
    write_video(incident_dir / "clip.mp4", seed=6)
    (incident_dir / "metadata.json").write_text(json.dumps(record), encoding="utf-8")
    return root, record
