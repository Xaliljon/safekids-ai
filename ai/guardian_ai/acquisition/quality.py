"""Quality validation: structural integrity before anything ships.

Checks (spec, Sprint 18 §6): missing annotations, empty/unreadable
videos, duplicate frames, duplicate videos, invalid timestamps, label
mismatch, broken bounding boxes. ERRORs block publication; WARNINGs
surface for human judgment. The result is written as
``quality-report.json`` — a validation that leaves no report did not
happen.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.annotations import load_annotation
from guardian_ai.acquisition.errors import AnnotationFormatError
from guardian_ai.acquisition.taxonomy import GUARDIAN_VIDEO_TAXONOMY_V1
from guardian_ai.acquisition.workspace import DatasetWorkspace

QUALITY_REPORT_FILE = "quality-report.json"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    severity: str  # "error" | "warning"
    message: str
    clip_id: str = ""


@dataclass(frozen=True, slots=True)
class QualityReport:
    issues: tuple[QualityIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_utc": datetime.now(tz=timezone.utc).isoformat(),
            "errors": [
                {"message": issue.message, "clip_id": issue.clip_id} for issue in self.errors
            ],
            "warnings": [
                {"message": issue.message, "clip_id": issue.clip_id} for issue in self.warnings
            ],
        }


def validate_quality(workspace: DatasetWorkspace) -> QualityReport:
    """Every structural check over one workspace."""
    issues: list[QualityIssue] = []
    clip_ids = workspace.clip_ids()
    if not clip_ids:
        issues.append(QualityIssue("error", "workspace contains no clips"))
        return QualityReport(tuple(issues))
    if len(clip_ids) != len(set(clip_ids)):
        issues.append(QualityIssue("error", "duplicate clip ids across splits"))

    video_hashes: dict[str, str] = {}
    for clip_id in clip_ids:
        issues.extend(_check_clip(workspace, clip_id, video_hashes))
    return QualityReport(tuple(issues))


def write_quality_report(report: QualityReport, workspace: DatasetWorkspace) -> Path:
    path = workspace.root / "metadata" / QUALITY_REPORT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------ checks


def _check_clip(
    workspace: DatasetWorkspace, clip_id: str, video_hashes: dict[str, str]
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    video_path = workspace.video_path(clip_id)
    annotation_path = workspace.annotation_path(clip_id)

    # missing annotations / missing videos
    if not annotation_path.is_file():
        issues.append(QualityIssue("error", "missing annotation", clip_id))
        return issues
    if not video_path.is_file():
        issues.append(QualityIssue("error", "missing video file", clip_id))
        return issues

    # duplicate videos (byte-identical content across clip ids)
    digest = _sha256(video_path)
    if digest in video_hashes:
        issues.append(
            QualityIssue(
                "error",
                f"duplicate video content (same as '{video_hashes[digest]}')",
                clip_id,
            )
        )
    else:
        video_hashes[digest] = clip_id

    # the annotation must parse AND self-validate (boxes, timestamps, labels)
    try:
        annotation = load_annotation(annotation_path)
    except AnnotationFormatError as exc:
        issues.append(QualityIssue("error", f"malformed annotation: {exc}", clip_id))
        return issues

    # taxonomy binding mismatch
    if (annotation.taxonomy_name, annotation.taxonomy_version) != (
        GUARDIAN_VIDEO_TAXONOMY_V1.name,
        GUARDIAN_VIDEO_TAXONOMY_V1.version,
    ):
        issues.append(
            QualityIssue(
                "error",
                f"label taxonomy mismatch: annotation binds "
                f"{annotation.taxonomy_name}@{annotation.taxonomy_version}",
                clip_id,
            )
        )

    # empty video / annotation-vs-video timestamp disagreement
    issues.extend(_check_video(workspace, clip_id, annotation))

    # a fall dataset clip with neither events nor boxes is unannotated
    if not annotation.events and not annotation.frames:
        issues.append(QualityIssue("warning", "clip has no events and no boxes yet", clip_id))
    return issues


def _check_video(workspace: DatasetWorkspace, clip_id: str, annotation: Any) -> list[QualityIssue]:
    import cv2
    import numpy as np

    issues: list[QualityIssue] = []
    capture = cv2.VideoCapture(str(workspace.video_path(clip_id)))
    try:
        if not capture.isOpened():
            return [QualityIssue("error", "unreadable video", clip_id)]
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count <= 0:
            return [QualityIssue("error", "empty video (no frames)", clip_id)]
        if annotation.frame_count > frame_count:
            issues.append(
                QualityIssue(
                    "error",
                    f"invalid timestamps: annotation declares {annotation.frame_count} "
                    f"frames, video has {frame_count}",
                    clip_id,
                )
            )
        # duplicate frames: sample up to 30 frames; a clip whose sampled
        # frames are all identical is a frozen/still recording
        sample_count = min(30, frame_count)
        indices = np.linspace(0, frame_count - 1, sample_count).astype(int)
        hashes = set()
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = capture.read()
            if not ok:
                continue
            hashes.add(hashlib.sha256(frame.tobytes()).hexdigest())
        if len(hashes) == 1 and sample_count > 1:
            issues.append(
                QualityIssue("error", "duplicate frames: video is a frozen still", clip_id)
            )
        elif sample_count > 4 and len(hashes) < sample_count // 2:
            issues.append(
                QualityIssue(
                    "warning",
                    f"many duplicate frames ({sample_count - len(hashes)} of "
                    f"{sample_count} sampled)",
                    clip_id,
                )
            )
    finally:
        capture.release()
    return issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
