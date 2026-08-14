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

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guardian_ai.datasets.errors import DatasetError
from guardian_ai.datasets.licensing import DatasetUsage
from guardian_ai.datasets.registry import FileSystemDatasetRegistry
from guardian_ai.export.compat import check_compatibility
from guardian_ai.export.manifest import MANIFEST_FILE, load_manifest
from guardian_ai.export.onnx_export import MODEL_FILE
from guardian_ai.training.errors import PromotionError
from guardian_ai.training.experiment import Experiment

logger = logging.getLogger(__name__)


def promote(
    experiment: Experiment,
    zoo_root: Path,
    approved_by: str,
    now_utc: str | None = None,
    datasets: FileSystemDatasetRegistry | None = None,
) -> Path:
    """Copy the run's validated export into the zoo. Returns the version dir."""
    import shutil

    if not approved_by or not approved_by.strip():
        raise PromotionError(
            "promotion requires --approved-by <name>: promotion is never automatic"
        )
    registry = _require_dataset_registry(datasets)
    _check_training_data(experiment, registry)
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
        "dataset_verified": _dataset_is_registered(experiment, registry),
        "approved_by": approved_by.strip(),
        "approved_utc": now_utc or datetime.now(tz=timezone.utc).isoformat(),
        "zoo_path": str(destination),
        "model": manifest["name"],
        "version": manifest["version"],
        "sha256": manifest["sha256"],
    }
    experiment.update(promotion=record)
    return destination


def _training_dataset(experiment: Experiment) -> tuple[str, str]:
    dataset = experiment.record.get("dataset", {})
    return str(dataset.get("name", "")), str(dataset.get("version", ""))


def _require_dataset_registry(
    datasets: FileSystemDatasetRegistry | None,
) -> FileSystemDatasetRegistry:
    """The registry is required rather than optional.

    A gate that quietly skips when its dependency is absent is the exact
    failure ADR-0005 was written to prevent — it would report success on the
    day it mattered.
    """
    if datasets is None:
        raise PromotionError(
            "promotion requires a dataset registry: ADR-0005 blocks promoting a "
            "model trained on withdrawn or evaluation-only data, and that cannot "
            "be checked without one"
        )
    return datasets


def _check_training_data(experiment: Experiment, datasets: FileSystemDatasetRegistry) -> None:
    """Refuse to ship a model its training data no longer permits.

    Two refusals, both from ADR-0005. A **withdrawn** dataset means a
    guardian revoked consent after this model learned from their child; the
    weights are not deleted, but they stop here (§4). An **evaluation-only**
    dataset means research-licensed material that may be measured against
    and never shipped (§5).
    """
    name, version = _training_dataset(experiment)
    if not name:
        raise PromotionError(
            "experiment names no training dataset — a model whose training data "
            "cannot be named cannot be shipped"
        )
    try:
        registered = datasets.get_for_audit(name, version)
    except DatasetError:
        # Not every run trains from the registry (the COCO baseline does
        # not). Unresolvable is not refused, but it is never silent: the
        # promotion record carries dataset_verified=false forever.
        logger.warning(
            "promotion: training dataset %s v%s is not in the registry — "
            "recording the promotion as unverified",
            name,
            version,
        )
        return
    if registered.tombstone is not None:
        raise PromotionError(
            f"training dataset {name} v{version} is tombstoned as "
            f"{registered.tombstone.lifecycle.value} — this model may not be "
            f"promoted (ADR-0005 §4): {registered.tombstone.reason}"
        )
    if registered.manifest.usage is DatasetUsage.EVALUATION_ONLY:
        raise PromotionError(
            f"training dataset {name} v{version} is published as "
            f"'{DatasetUsage.EVALUATION_ONLY.value}': its licence permits "
            f"measuring against it, not shipping a model trained on it "
            f"(ADR-0005 §5)"
        )


def _dataset_is_registered(experiment: Experiment, datasets: FileSystemDatasetRegistry) -> bool:
    name, version = _training_dataset(experiment)
    try:
        datasets.get_for_audit(name, version)
    except DatasetError:
        return False
    return True
