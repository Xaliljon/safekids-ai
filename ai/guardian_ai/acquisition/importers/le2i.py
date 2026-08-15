"""Le2i Fall Detection Dataset importer (Université de Bourgogne).

Expected raw layout (as distributed; Coffee_room / Home / Lecture_room /
Office scenes):

    <raw>/
      Videos/video (1).avi ...       # or <scene>/Videos/*.avi
      Annotation_files/video (1).txt

Each annotation txt: line 1 = fall start frame, line 2 = fall end frame
(0/0 when the clip contains no fall), then one line per frame:
``frame,x1,y1,x2,y2`` — a pixel bounding box of the person on the
320x240 source. Boxes become normalized Guardian ``person`` boxes; the
start/end pair becomes a ``fall`` event span.
"""

from __future__ import annotations

import re
from pathlib import Path

from guardian_ai.acquisition.annotations import EventSpan, FrameAnnotation, FrameBox
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers.base import SourceClip
from guardian_ai.acquisition.video import probe

_SOURCE_WIDTH = 320.0
_SOURCE_HEIGHT = 240.0


class Le2iImporter:
    source = "le2i"
    license_note = (
        "Le2i Fall Detection Dataset — research use; cite Charfi et al. "
        "2013. Adult actors in staged indoor scenes, no minors."
    )

    def discover(self, raw_dir: Path) -> list[SourceClip]:
        videos = sorted(raw_dir.glob("**/Videos/*.avi")) + sorted(raw_dir.glob("**/Videos/*.mp4"))
        if not videos:
            raise ImporterError(f"le2i: no Videos/*.avi under {raw_dir}")
        clips: list[SourceClip] = []
        for video in videos:
            annotation = self._annotation_for(video)
            scene = video.parents[1].name if video.parents[1] != raw_dir else "scene"
            info = probe(video)
            events, frames = self._parse(
                annotation, info.width or _SOURCE_WIDTH, info.height or _SOURCE_HEIGHT
            )
            clips.append(
                SourceClip(
                    clip_id=f"le2i-{_slug(scene)}-{_slug(video.stem)}",
                    video=video,
                    source_fps=info.fps or 25.0,
                    events=events,
                    frames=frames,
                    attributes={"camera_angle": "corner", "scene": scene, "subjects": "adult"},
                    # The room and its fixed camera. Le2i has four, and
                    # letting them straddle splits is what made val_f1
                    # reach 1.0 by epoch 3 on same-room recognition.
                    split_group=scene,
                )
            )
        return clips

    # ------------------------------------------------------------ internals

    def _annotation_for(self, video: Path) -> Path:
        for base in (video.parents[1], video.parents[0].parent, video.parent):
            candidate = base / "Annotation_files" / f"{video.stem}.txt"
            if candidate.is_file():
                return candidate
        raise ImporterError(f"le2i: no Annotation_files/{video.stem}.txt for {video.name}")

    def _parse(
        self, path: Path, width: float, height: float
    ) -> tuple[tuple[EventSpan, ...], tuple[FrameAnnotation, ...]]:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        lines = [line for line in lines if line]
        if len(lines) < 2:
            raise ImporterError(f"le2i: {path.name} is missing the fall start/end lines")
        try:
            fall_start, fall_end = int(lines[0]), int(lines[1])
        except ValueError as exc:
            raise ImporterError(f"le2i: {path.name} has non-numeric fall frames") from exc
        events: tuple[EventSpan, ...] = ()
        if fall_end > 0 and fall_end >= fall_start:
            events = (EventSpan("fall", max(0, fall_start), fall_end, 1.0),)

        frames: list[FrameAnnotation] = []
        for number, line in enumerate(lines[2:], start=3):
            parts = [part for part in re.split(r"[,\s]+", line) if part]
            if len(parts) != 5:
                raise ImporterError(f"le2i: malformed box line {path.name}:{number}: '{line}'")
            try:
                frame, x1, y1, x2, y2 = (int(float(part)) for part in parts)
            except ValueError as exc:
                raise ImporterError(f"le2i: non-numeric box line {path.name}:{number}") from exc
            if x2 <= x1 or y2 <= y1:
                continue  # Le2i marks frames without a person as zero boxes
            box = FrameBox(
                label="person",
                box=(
                    max(0.0, x1 / width),
                    max(0.0, y1 / height),
                    min(1.0, (x2 - x1) / width),
                    min(1.0, (y2 - y1) / height),
                ),
                confidence=1.0,
            )
            frames.append(FrameAnnotation(index=max(0, frame), boxes=(box,)))
        return events, tuple(frames)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
