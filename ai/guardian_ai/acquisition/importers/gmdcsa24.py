"""GMDCSA24 importer (Fall Detection Dataset, 2024).

Raw layout, **as the dataset is actually distributed** (four subjects, each
filmed at home; github.com/ekramalam/GMDCSA24-…):

    <raw>/
      Subject 1/
        Fall/01.mp4 …           clips containing a fall
        Fall.csv                per-clip description + labelled time spans
        ADL/01.mp4 …            activities of daily living
        ADL.csv
      Subject 2/ … Subject 4/

The CSV's last column carries the annotation, semicolon-separated:

    Falling (SW)[3.4 to 6]; Sitting[0 to 3.4]

Times are seconds on the clip's own timeline. Labels are the paper's, not
Guardian's, and are mapped through ``_LABEL_MAP``; anything unmapped is
dropped rather than guessed at, because inventing an event label is worse
than having none.

Fall clips *require* a falling span — a fall dataset where nobody knows
when the fall happens is not annotated data. ADL clips need none (their
value is being negatives) and keep whatever posture spans they carry.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from guardian_ai.acquisition.annotations import EventSpan
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers.base import SourceClip
from guardian_ai.acquisition.video import probe

_CATEGORIES = ("Fall", "ADL")
_CLASSES_COLUMN = "Classes"
_FILE_COLUMN = "File Name"

_LABEL_MAP = {
    "falling": "fall",
    "walking": "walking",
    "standing": "standing",
    "sitting": "sitting",
    "sleeping": "lying",
    "lying": "lying",
}
"""GMDCSA24's vocabulary onto Guardian's (acquisition taxonomy).

"Sleeping" becomes ``lying``: Guardian describes body state, never
intent — the detector cannot know whether someone on a bed is asleep, and
a label it cannot verify is a label it should not carry. Everything else
this dataset uses (reading, bending, …) has no Guardian equivalent and is
dropped."""

_SPAN_PATTERN = re.compile(r"^\s*(?P<label>[^[]+?)\s*\[\s*(?P<start>[\d.]+)\s+to\s+(?P<end>[\d.]+)")


class Gmdcsa24Importer:
    source = "gmdcsa24"
    license_note = (
        "GMDCSA24 — CC-BY 4.0; cite Alanazi et al. 2024. Adult subjects "
        "in home settings, no minors."
    )

    def discover(self, raw_dir: Path) -> list[SourceClip]:
        clips: list[SourceClip] = []
        for subject_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
            for category in _CATEGORIES:
                clips.extend(self._clips_for(subject_dir, category))
        if not clips:
            raise ImporterError(
                f"gmdcsa24: no 'Subject */Fall' or 'Subject */ADL' clips under {raw_dir} — "
                f"expected the layout as distributed on GitHub"
            )
        return clips

    # ------------------------------------------------------------ internals

    def _clips_for(self, subject_dir: Path, category: str) -> list[SourceClip]:
        category_dir = subject_dir / category
        if not category_dir.is_dir():
            return []
        spans = self._read_spans(subject_dir / f"{category}.csv", category)
        subject = subject_dir.name
        clips: list[SourceClip] = []
        for video in sorted(category_dir.glob("*.mp4")):
            info = probe(video)
            fps = info.fps or 30.0
            events = self._events_for(video, category, spans.get(video.name, ()), fps, subject)
            clips.append(
                SourceClip(
                    clip_id=f"gmdcsa24-{_slug(category)}-{_slug(subject)}-{_slug(video.stem)}",
                    video=video,
                    source_fps=fps,
                    events=events,
                    attributes={
                        "camera_angle": "room",
                        "category": category.lower(),
                        "subjects": "adult",
                    },
                    # Four subjects, each filmed in their own home: the
                    # person and their room vary together, so the subject
                    # is the group that must not straddle splits.
                    split_group=subject,
                )
            )
        return clips

    def _read_spans(
        self, csv_path: Path, category: str
    ) -> dict[str, tuple[tuple[str, float, float], ...]]:
        """Parse one <category>.csv into file name -> (label, start_s, end_s)."""
        if not csv_path.is_file():
            raise ImporterError(
                f"gmdcsa24: '{csv_path.name}' missing beside {csv_path.parent.name}/{category} — "
                f"every category directory ships its annotation CSV"
            )
        rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
        if not rows:
            raise ImporterError(f"gmdcsa24: '{csv_path}' has no rows")
        header = rows[0].keys()
        if _FILE_COLUMN not in header or not any(
            column and column.strip() == _CLASSES_COLUMN for column in header
        ):
            raise ImporterError(
                f"gmdcsa24: '{csv_path}' needs '{_FILE_COLUMN}' and '{_CLASSES_COLUMN}' "
                f"columns, found {sorted(name for name in header if name)}"
            )
        # The shipped CSVs spell the last column " Classes" (leading space).
        classes_key = next(c for c in header if c and c.strip() == _CLASSES_COLUMN)
        spans: dict[str, tuple[tuple[str, float, float], ...]] = {}
        for row in rows:
            file_name = (row.get(_FILE_COLUMN) or "").strip()
            if not file_name:
                continue
            spans[file_name] = self._parse_classes(row.get(classes_key) or "", csv_path, file_name)
        return spans

    def _parse_classes(
        self, classes: str, csv_path: Path, file_name: str
    ) -> tuple[tuple[str, float, float], ...]:
        parsed: list[tuple[str, float, float]] = []
        for chunk in classes.split(";"):
            if not chunk.strip():
                continue
            match = _SPAN_PATTERN.match(chunk)
            if match is None:
                raise ImporterError(
                    f"gmdcsa24: cannot parse span '{chunk.strip()}' for '{file_name}' "
                    f"in {csv_path.name} — expected 'Label[start to end]'"
                )
            # "Falling (SW)" -> "falling": the parenthetical is the paper's
            # fall subtype (sideways, forward…), which Guardian does not model.
            raw_label = re.sub(r"\(.*?\)", "", match.group("label")).strip().lower()
            label = _LABEL_MAP.get(raw_label)
            if label is None:
                continue
            start_s, end_s = float(match.group("start")), float(match.group("end"))
            if end_s < start_s or start_s < 0:
                raise ImporterError(
                    f"gmdcsa24: span times [{start_s}, {end_s}] invalid for '{file_name}' "
                    f"in {csv_path.name}"
                )
            parsed.append((label, start_s, end_s))
        return tuple(parsed)

    def _events_for(
        self,
        video: Path,
        category: str,
        spans: tuple[tuple[str, float, float], ...],
        fps: float,
        subject: str,
    ) -> tuple[EventSpan, ...]:
        events = tuple(
            EventSpan(
                label=label,
                start_frame=int(start_s * fps),
                end_frame=int(end_s * fps),
                confidence=1.0,
            )
            for label, start_s, end_s in spans
        )
        if category == "Fall" and not any(event.label == "fall" for event in events):
            raise ImporterError(
                f"gmdcsa24: fall clip '{subject}/{category}/{video.name}' has no falling "
                f"span in {category}.csv — unannotated falls are rejected"
            )
        return events


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
