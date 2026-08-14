"""Promotion: manual, gated, audited — never automatic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from guardian_ai.datasets.manifest import DATASET_MANIFEST_NAME
from guardian_ai.datasets.registry import FileSystemDatasetRegistry
from guardian_ai.datasets.taxonomy import LabelDefinition, LabelTaxonomy
from guardian_ai.export.manifest import (
    MANIFEST_FILE,
    build_manifest,
    save_manifest,
)
from guardian_ai.export.onnx_export import MODEL_FILE, export_onnx, sha256_of
from guardian_ai.training.config import config_from_dict
from guardian_ai.training.errors import CompatibilityError, PromotionError
from guardian_ai.training.experiment import Experiment
from guardian_ai.training.families import TinySsdFamily
from guardian_ai.training.promote import promote


def empty_registry(tmp_path: Path) -> FileSystemDatasetRegistry:
    """A registry that does not know 'tiny-synthetic'.

    Unresolvable training data is not refused — the COCO baseline trains
    outside the registry too — but it is recorded as unverified rather than
    passed silently (ADR-0005 §4).
    """
    return FileSystemDatasetRegistry(tmp_path / "registry")


def make_experiment(tmp_path: Path) -> Experiment:
    config = config_from_dict(
        {
            "name": "promo-test",
            "model": {"family": "tiny-ssd", "input_size": 64},
            "dataset": {"registry_root": "registry", "name": "tiny-synthetic"},
            "epochs": 1,
            "batch_size": 4,
            "output_dir": str(tmp_path / "runs"),
        }
    )
    return Experiment.create(
        config,
        dataset_name="tiny-synthetic",
        dataset_version="1.0.0",
        taxonomy_name="guardian-safety",
        taxonomy_version="1.0.0",
    )


def make_valid_export(experiment: Experiment, version: str = "0.0.1") -> None:
    family = TinySsdFamily()
    model = family.build(num_classes=3, input_size=64)
    destination = experiment.export_dir / MODEL_FILE
    sha256 = export_onnx(model, family, 64, destination)
    manifest = build_manifest(
        model_name="tiny-ssd",
        model_version=version,
        sha256=sha256,
        labels=["adult", "child", "person"],
        license_id=family.license,
        input_name="images",
        output_name="output",
        input_shape=[1, 3, 64, 64],
        output_shape=[1, 8],
        dataset_name="tiny-synthetic",
        dataset_version="1.0.0",
        taxonomy_name="guardian-safety",
        taxonomy_version="1.0.0",
        experiment_id=experiment.experiment_id,
        git_commit="deadbeef",
    )
    save_manifest(manifest, experiment.export_dir)


def test_promotion_requires_a_named_approver(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    for approver in ("", "   "):
        with pytest.raises(PromotionError, match="never automatic"):
            promote(
                experiment,
                tmp_path / "zoo",
                approved_by=approver,
                datasets=empty_registry(tmp_path),
            )


def test_promotion_refuses_without_export(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    with pytest.raises(PromotionError, match="run export first"):
        promote(
            experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path)
        )


def test_promotion_refuses_without_manifest(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    (experiment.export_dir / MANIFEST_FILE).unlink()
    with pytest.raises(PromotionError, match="auto-generated"):
        promote(
            experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path)
        )


def test_promotion_recheck_catches_tampered_artifact(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    model_path = experiment.export_dir / MODEL_FILE
    model_path.write_bytes(model_path.read_bytes() + b"tampered")
    with pytest.raises(CompatibilityError, match="sha256"):
        promote(
            experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path)
        )


def test_promotion_installs_zoo_layout_and_audits(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    destination = promote(
        experiment, tmp_path / "zoo", approved_by="  Reviewer ", datasets=empty_registry(tmp_path)
    )

    assert destination == tmp_path / "zoo" / "tiny-ssd" / "0.0.1"
    assert (destination / MODEL_FILE).is_file()
    manifest = json.loads((destination / MANIFEST_FILE).read_text())
    assert manifest["sha256"] == sha256_of(destination / MODEL_FILE)

    promotion = Experiment.load(experiment.run_dir).record["promotion"]
    assert promotion["approved_by"] == "Reviewer"
    assert promotion["model"] == "tiny-ssd"
    assert promotion["version"] == "0.0.1"
    assert promotion["approved_utc"]
    assert promotion["zoo_path"] == str(destination)


def test_zoo_versions_are_immutable(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    promote(experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path))
    second = make_experiment(tmp_path)
    make_valid_export(second)
    with pytest.raises(PromotionError, match="immutable"):
        promote(second, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path))


# ------------------------------------------------- ADR-0005 promotion gate


def _publish(registry: FileSystemDatasetRegistry, tmp_path: Path, usage: str) -> None:
    """Put 'tiny-synthetic' 1.0.0 in the registry so the gate can see it."""
    bundle = tmp_path / f"bundle-{usage}"
    (bundle / "annotations").mkdir(parents=True)
    (bundle / "annotations" / "train.jsonl").write_text(
        json.dumps(
            {
                "path": "clips/a/000001.jpg",
                "width": 64,
                "height": 64,
                "annotations": [
                    {"label": "person", "box": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle / DATASET_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "name": "tiny-synthetic",
                "version": "1.0.0",
                "taxonomy": {"name": "guardian-safety", "version": "1.0.0"},
                "created_utc": "2026-08-15T10:00:00+00:00",
                "provenance": {"collected_by": "tests", "consent_reference": "agreement-1"},
                "privacy": {"contains_minors": False, "anonymized": False},
                "splits": {"train": {"file": "train.jsonl"}},
                "license": "Research-Only" if usage == "evaluation-only" else "Apache-2.0",
                "usage": usage,
            }
        ),
        encoding="utf-8",
    )
    registry.publish(
        bundle,
        LabelTaxonomy(
            name="guardian-safety", version="1.0.0", labels=(LabelDefinition(name="person"),)
        ),
    )


def test_promotion_refuses_without_a_dataset_registry(tmp_path: Path) -> None:
    """The gate is not optional. A promotion path that skips the check when
    its dependency is missing reports success on the day it matters."""
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    with pytest.raises(PromotionError, match="requires a dataset registry"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer")


def test_promotion_refused_when_training_data_was_withdrawn(tmp_path: Path) -> None:
    registry = empty_registry(tmp_path)
    _publish(registry, tmp_path, usage="training")
    registry.withdraw(
        "tiny-synthetic",
        "1.0.0",
        reason="guardian of subject 3 withdrew consent",
        recorded_by="Data Protection Lead",
        recorded_utc="2026-08-15T10:00:00+00:00",
    )
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    with pytest.raises(PromotionError, match="tombstoned as withdrawn"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=registry)
    assert not (tmp_path / "zoo").exists()


def test_promotion_refused_for_evaluation_only_training_data(tmp_path: Path) -> None:
    """Research-licensed data may be measured against, never shipped."""
    registry = empty_registry(tmp_path)
    _publish(registry, tmp_path, usage="evaluation-only")
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    with pytest.raises(PromotionError, match="evaluation-only"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=registry)


def test_promotion_records_whether_the_dataset_was_verified(tmp_path: Path) -> None:
    registry = empty_registry(tmp_path)
    _publish(registry, tmp_path, usage="training")
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    promote(experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=registry)
    assert Experiment.load(experiment.run_dir).record["promotion"]["dataset_verified"] is True


def test_unverified_dataset_is_recorded_not_hidden(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    promote(experiment, tmp_path / "zoo", approved_by="Reviewer", datasets=empty_registry(tmp_path))
    assert Experiment.load(experiment.run_dir).record["promotion"]["dataset_verified"] is False
