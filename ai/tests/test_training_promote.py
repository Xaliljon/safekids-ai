"""Promotion: manual, gated, audited — never automatic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
            promote(experiment, tmp_path / "zoo", approved_by=approver)


def test_promotion_refuses_without_export(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    with pytest.raises(PromotionError, match="run export first"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer")


def test_promotion_refuses_without_manifest(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    (experiment.export_dir / MANIFEST_FILE).unlink()
    with pytest.raises(PromotionError, match="auto-generated"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer")


def test_promotion_recheck_catches_tampered_artifact(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    model_path = experiment.export_dir / MODEL_FILE
    model_path.write_bytes(model_path.read_bytes() + b"tampered")
    with pytest.raises(CompatibilityError, match="sha256"):
        promote(experiment, tmp_path / "zoo", approved_by="Reviewer")


def test_promotion_installs_zoo_layout_and_audits(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    make_valid_export(experiment)
    destination = promote(experiment, tmp_path / "zoo", approved_by="  Reviewer ")

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
    promote(experiment, tmp_path / "zoo", approved_by="Reviewer")
    second = make_experiment(tmp_path)
    make_valid_export(second)
    with pytest.raises(PromotionError, match="immutable"):
        promote(second, tmp_path / "zoo", approved_by="Reviewer")
