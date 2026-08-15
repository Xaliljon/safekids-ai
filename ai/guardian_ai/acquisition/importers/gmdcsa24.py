"""GMDCSA24 importer (Fall Detection Dataset, 2024).

Expected raw layout (as distributed on GitHub/Zenodo; four subjects,
home settings):

    <raw>/
      Fall/Subject1/*.mp4          # clips containing a fall
      ADL/Subject1/*.mp4           # activities of daily living
      annotations.json             # optional temporal segments:
                                   # {"Fall/Subject1/F1.mp4":
                                   #    [{"label": "fall", "start_s": 2.0, "end_s": 3.4}]}

Fall clips *require* a segment entry — a fall dataset where nobody knows
when the fall happens is not annotated data. ADL clips need none (their
value is being negatives) and may optionally carry posture segments.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.annotations import EventSpan
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers.base import SourceClip
from guardian_ai.acquisition.taxonomy import is_event_label
from guardian_ai.acquisition.video import probe

_ANNOTATIONS_FILE = "annotations.json"


class Gmdcsa24Importer:
    source = "gmdcsa24"
    license_note = (
        "GMDCSA24 — CC-BY 4.0; cite Alanazi et al. 2024. Adult subjects "
        "in home settings, no minors."
    )

    def discover(self, raw_dir: Path) -> list[SourceClip]:
        segments = self._read_segments(raw_dir)
        clips: list[SourceClip] = []
        for category in ("Fall", "ADL"):
            for video in sorted((raw_dir / category).glob("**/*.mp4")):
                relative = video.relative_to(raw_dir).as_posix()
                info = probe(video)
                events = self._events_for(relative, category, segments, info.fps)
                subject = video.parent.name
                clips.append(
                    SourceClip(
                        clip_id=f"gmdcsa24-{_slug(category)}-{_slug(subject)}-{_slug(video.stem)}",
                        video=video,
                        source_fps=info.fps or 30.0,
                        events=events,
                        attributes={
                            "camera_angle": "room",
                            "category": category.lower(),
                            "subjects": "adult",
                        },
                        # Four subjects, each filmed in their own home: the
                        # person and their room vary together, so the
                        # subject is the group.
                        split_group=subject,
                    )
                )
        if not clips:
            raise ImporterError(f"gmdcsa24: no Fall/ or ADL/ clips under {raw_dir}")
        return clips

    # ------------------------------------------------------------ internals

    def _read_segments(self, raw_dir: Path) -> dict[str, list[dict[str, Any]]]:
        path = raw_dir / _ANNOTATIONS_FILE
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ImporterError(f"gmdcsa24: {_ANNOTATIONS_FILE} is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ImporterError(f"gmdcsa24: {_ANNOTATIONS_FILE} must map video -> segments")
        return {str(key): list(value) for key, value in raw.items()}

    def _events_for(
        self, relative: str, category: str, segments: dict[str, list[dict[str, Any]]], fps: float
    ) -> tuple[EventSpan, ...]:
        entries = segments.get(relative, [])
        if category == "Fall" and not entries:
            raise ImporterError(
                f"gmdcsa24: fall clip '{relative}' has no segment in "
                f"{_ANNOTATIONS_FILE} — unannotated falls are rejected"
            )
        fps = fps or 30.0
        events: list[EventSpan] = []
        for entry in entries:
            try:
                label = str(entry["label"])
                start_s = float(entry["start_s"])
                end_s = float(entry["end_s"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ImporterError(
                    f"gmdcsa24: malformed segment for '{relative}': {entry}"
                ) from exc
            if not is_event_label(label):
                raise ImporterError(
                    f"gmdcsa24: '{label}' is not a Guardian event label ('{relative}')"
                )
            if end_s < start_s or start_s < 0:
                raise ImporterError(
                    f"gmdcsa24: segment times [{start_s}, {end_s}] invalid ('{relative}')"
                )
            events.append(
                EventSpan(
                    label=label,
                    start_frame=int(start_s * fps),
                    end_frame=int(end_s * fps),
                    confidence=float(entry.get("confidence", 1.0)),
                )
            )
        return tuple(events)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
