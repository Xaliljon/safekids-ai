"""UR Fall Dataset importer (University of Rzeszów).

Expected raw layout (as distributed at fenix.ur.edu.pl/~mkepski/ds/uf.html):

    <raw>/
      urfall-cam0-falls.csv          # rows: sequence,frame,label
                                     # label: -1 not lying, 0 falling, 1 lying
      videos/fall-01-cam0.mp4        # or image sequences:
      fall-01-cam0-rgb/*.png

Sequences named ``fall-XX-cam0`` are fall recordings, ``adl-XX-cam0`` are
activities of daily living. The CSV's per-frame labels become Guardian
event spans: contiguous 0-labels -> a ``fall`` event, contiguous
1-labels -> ``lying``. UR Fall has no bounding boxes in this CSV — boxes
are added later in the annotation tool.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from guardian_ai.acquisition.annotations import EventSpan
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers.base import SourceClip

_SOURCE_FPS = 30.0  # UR Fall cameras record at 30 fps


class UrFallImporter:
    source = "urfall"
    license_note = (
        "UR Fall Detection Dataset — free for research use; cite Kwolek & "
        "Kepski 2014. Adult volunteers, staged falls, no minors."
    )

    def discover(self, raw_dir: Path) -> list[SourceClip]:
        labels = self._read_labels(raw_dir)
        clips: list[SourceClip] = []
        for sequence in sorted(labels):
            media = self._find_media(raw_dir, sequence)
            if media is None:
                raise ImporterError(
                    f"urfall: sequence '{sequence}' is in the CSV but has no "
                    f"video/image-sequence under {raw_dir}"
                )
            video, images = media
            clips.append(
                SourceClip(
                    clip_id=f"urfall-{sequence}",
                    video=video,
                    image_sequence=images,
                    source_fps=_SOURCE_FPS,
                    events=self._events_from_labels(labels[sequence]),
                    attributes={"camera_angle": "side", "subjects": "adult"},
                )
            )
        return clips

    # ------------------------------------------------------------ internals

    def _read_labels(self, raw_dir: Path) -> dict[str, list[tuple[int, int]]]:
        candidates = sorted(raw_dir.glob("urfall-cam0-*.csv"))
        if not candidates:
            raise ImporterError(f"urfall: no urfall-cam0-*.csv under {raw_dir}")
        labels: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for csv_path in candidates:
            with csv_path.open(encoding="utf-8", newline="") as handle:
                for row_number, row in enumerate(csv.reader(handle), start=1):
                    if not row or not row[0].strip():
                        continue
                    try:
                        sequence = row[0].strip()
                        frame = int(row[1])
                        label = int(row[2])
                    except (IndexError, ValueError) as exc:
                        raise ImporterError(
                            f"urfall: malformed CSV row {csv_path.name}:{row_number}: {row}"
                        ) from exc
                    if label not in (-1, 0, 1):
                        raise ImporterError(
                            f"urfall: unknown label {label} at {csv_path.name}:{row_number}"
                        )
                    labels[sequence].append((frame, label))
        for sequence in labels:
            labels[sequence].sort()
        return dict(labels)

    def _find_media(
        self, raw_dir: Path, sequence: str
    ) -> tuple[Path | None, tuple[Path, ...]] | None:
        for pattern in (
            f"videos/{sequence}.mp4",
            f"videos/{sequence}.avi",
            f"{sequence}.mp4",
            f"{sequence}.avi",
        ):
            candidate = raw_dir / pattern
            if candidate.is_file():
                return candidate, ()
        for directory in (raw_dir / f"{sequence}-rgb", raw_dir / sequence):
            if directory.is_dir():
                images = tuple(sorted(directory.glob("*.png"))) or tuple(
                    sorted(directory.glob("*.jpg"))
                )
                if images:
                    return None, images
        return None

    def _events_from_labels(self, rows: list[tuple[int, int]]) -> tuple[EventSpan, ...]:
        """Contiguous runs of 0 -> fall, of 1 -> lying (source frames)."""
        events: list[EventSpan] = []
        run_label: int | None = None
        run_start = 0
        previous_frame = 0
        for frame, label in rows:
            if label != run_label:
                if run_label in (0, 1):
                    events.append(_span(run_label, run_start, previous_frame))
                run_label, run_start = label, frame
            previous_frame = frame
        if run_label in (0, 1):
            events.append(_span(run_label, run_start, previous_frame))
        return tuple(events)


def _span(label: int, start: int, end: int) -> EventSpan:
    return EventSpan(
        label="fall" if label == 0 else "lying",
        start_frame=start,
        end_frame=max(start, end),
        confidence=1.0,
    )
