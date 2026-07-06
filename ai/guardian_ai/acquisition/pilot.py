"""Guardian pilot import: real incidents become dataset candidates.

Input is a *decrypted evidence export* directory — the operator produces
it on the box (guardianctl exports the AES-encrypted clip in the clear;
ai/ never sees keys and never imports edge code):

    <export>/
      <incident-id>/
        metadata.json    # the Evidence record (ADR-0017 shape, plaintext)
        clip.mp4         # decrypted ORIGINAL clip (never the AI overlay)

Every imported clip preserves the full identity chain (ADR-0007):
incident_id, track_id, detection_id, frame_id, correlation_id — so the
lineage Incident → Evidence → Dataset → Model is complete, in both
directions.

The imported clip is a *candidate*: review state starts at IMPORTED,
events must be annotated by a human, and nothing is published
automatically.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.annotations import ClipAnnotation
from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.review import ReviewState, ReviewWorkflow
from guardian_ai.acquisition.video import TARGET_FPS, TARGET_HEIGHT, TARGET_WIDTH, normalize_video
from guardian_ai.acquisition.workspace import DatasetWorkspace

logger = logging.getLogger(__name__)

METADATA_FILE = "metadata.json"
CLIP_FILE = "clip.mp4"
LINEAGE_KEYS = ("incident_id", "track_id", "detection_id", "frame_id", "correlation_id")


def import_pilot_evidence(export_dir: Path, workspace: DatasetWorkspace) -> list[str]:
    """Import every incident under an evidence export. Returns clip ids."""
    if not export_dir.is_dir():
        raise ImporterError(f"evidence export directory missing: {export_dir}")
    incident_dirs = sorted(
        path for path in export_dir.iterdir() if path.is_dir() and (path / METADATA_FILE).is_file()
    )
    if not incident_dirs:
        raise ImporterError(
            f"no evidence exports under {export_dir} "
            f"(expected <incident-id>/{METADATA_FILE} + {CLIP_FILE})"
        )
    imported = []
    for incident_dir in incident_dirs:
        imported.append(_import_one(incident_dir, workspace))
    workflow = ReviewWorkflow(workspace.root)
    if workflow.state() is None:
        workflow.record(
            ReviewState.IMPORTED,
            by="importer:pilot",
            notes=f"{len(imported)} incident clip(s) from {export_dir.name}",
        )
    return imported


def _import_one(incident_dir: Path, workspace: DatasetWorkspace) -> str:
    record = _read_evidence_record(incident_dir / METADATA_FILE)
    clip_path = incident_dir / CLIP_FILE
    if not clip_path.is_file():
        raise ImporterError(
            f"pilot: {incident_dir.name} has {METADATA_FILE} but no {CLIP_FILE} — "
            "export the decrypted ORIGINAL clip from the box first"
        )
    clip_id = f"pilot-{record['incident_id'][:8]}"
    with tempfile.TemporaryDirectory(prefix="guardian-pilot-") as staging:
        normalized = Path(staging) / f"{clip_id}.mp4"
        info = normalize_video(clip_path, normalized)
        annotation = ClipAnnotation(
            clip_id=clip_id,
            fps=float(TARGET_FPS),
            width=TARGET_WIDTH,
            height=TARGET_HEIGHT,
            frame_count=info.frame_count,
            # events arrive from human annotation — a pilot incident is a
            # candidate, not ground truth (docs/04: AI never labels itself)
            attributes={"source_dataset": "pilot", "needs_annotation": "true"},
        )
        metadata: dict[str, Any] = {
            "source_dataset": "pilot",
            "license_note": "Guardian pilot evidence — customer data, consent per pilot agreement",
            "original": incident_dir.name,
            "camera_id": record.get("camera_id", ""),
            "incident_severity": record.get("incident_severity", ""),
            "incident_opened_at": record.get("incident_opened_at", ""),
            "lineage": {key: record[key] for key in LINEAGE_KEYS},
            "normalized": {
                "width": info.width,
                "height": info.height,
                "fps": TARGET_FPS,
                "frame_count": info.frame_count,
            },
        }
        split = workspace.add_clip(clip_id, normalized, annotation, metadata)
    logger.info(
        "pilot: imported incident %s as %s (%s split) — lineage preserved",
        record["incident_id"],
        clip_id,
        split,
    )
    return clip_id


def _read_evidence_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImporterError(f"pilot: unreadable evidence record {path}: {exc}") from exc
    missing = [key for key in LINEAGE_KEYS if not record.get(key)]
    if missing:
        raise ImporterError(
            f"pilot: evidence record {path.parent.name} is missing lineage ids "
            f"{missing} — clips without full lineage are rejected (ADR-0007)"
        )
    return dict(record)


def lineage_of(workspace: DatasetWorkspace, clip_id: str) -> dict[str, str]:
    """The identity chain of an imported pilot clip."""
    metadata = workspace.metadata(clip_id)
    lineage = metadata.get("lineage")
    if not lineage:
        raise ImporterError(f"clip '{clip_id}' carries no pilot lineage")
    return {key: str(lineage[key]) for key in LINEAGE_KEYS}
