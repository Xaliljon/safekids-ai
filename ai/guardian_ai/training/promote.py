"""Promotion to the Guardian Model Zoo — manual, gated, audited.

Sprint 17 rule: "Never allow automatic promotion." This module refuses
to move an artifact unless (1) a human is named as approver, (2) the
compatibility check passed moments before the copy, and (3) both the
model and its auto-generated manifest exist. The approval is recorded in
experiment.json — a promoted model can always be traced to who approved
it and which run produced it.

The zoo layout written here is exactly what the Edge Box expects
(models/<name>/<version>/{model.onnx, manifest.json}); activation on a
box stays a deliberate `guardianctl` step — promotion never flips
state.json.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guardian_ai.export.compat import check_compatibility
from guardian_ai.export.manifest import MANIFEST_FILE, load_manifest
from guardian_ai.export.onnx_export import MODEL_FILE
from guardian_ai.training.errors import PromotionError
from guardian_ai.training.experiment import Experiment


def promote(
    experiment: Experiment,
    zoo_root: Path,
    approved_by: str,
    now_utc: str | None = None,
) -> Path:
    """Copy the run's validated export into the zoo. Returns the version dir."""
    import shutil

    if not approved_by or not approved_by.strip():
        raise PromotionError(
            "promotion requires --approved-by <name>: promotion is never automatic"
        )
    export_dir = experiment.export_dir
    model_path = export_dir / MODEL_FILE
    manifest_path = export_dir / MANIFEST_FILE
    if not model_path.is_file():
        raise PromotionError(f"no exported model at {model_path} — run export first")
    if not manifest_path.is_file():
        raise PromotionError(
            f"no manifest at {manifest_path} — manifests are auto-generated at "
            "export time and must not be created by hand"
        )
    manifest = load_manifest(export_dir)

    # Re-check compatibility at promotion time: the artifact on disk is
    # what ships, not whatever passed earlier in the run.
    check_compatibility(model_path, manifest)

    destination = zoo_root / str(manifest["name"]) / str(manifest["version"])
    if destination.exists():
        raise PromotionError(
            f"zoo already has {manifest['name']}/{manifest['version']} — versions "
            "are immutable; bump the version instead of overwriting"
        )
    destination.mkdir(parents=True)
    shutil.copy2(model_path, destination / MODEL_FILE)
    shutil.copy2(manifest_path, destination / MANIFEST_FILE)

    record: dict[str, Any] = {
        "approved_by": approved_by.strip(),
        "approved_utc": now_utc or datetime.now(tz=timezone.utc).isoformat(),
        "zoo_path": str(destination),
        "model": manifest["name"],
        "version": manifest["version"],
        "sha256": manifest["sha256"],
    }
    experiment.update(promotion=record)
    return destination
