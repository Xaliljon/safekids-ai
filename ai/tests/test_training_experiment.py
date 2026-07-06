"""Experiment records: no anonymous models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from guardian_ai.training.config import config_from_dict
from guardian_ai.training.errors import ExperimentError
from guardian_ai.training.experiment import EXPERIMENT_FILE, Experiment, git_commit

CONFIG = {
    "name": "record-test",
    "model": {"family": "tiny-ssd"},
    "dataset": {"registry_root": "registry", "name": "dummy-detection"},
    "epochs": 2,
    "batch_size": 4,
}


def make_experiment(tmp_path: Path) -> Experiment:
    config = config_from_dict({**CONFIG, "output_dir": str(tmp_path / "runs")})
    return Experiment.create(
        config,
        dataset_name="dummy-detection",
        dataset_version="1.0.0",
        taxonomy_name="guardian-safety",
        taxonomy_version="1.0.0",
    )


def test_create_writes_full_provenance(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    record = json.loads((experiment.run_dir / EXPERIMENT_FILE).read_text())
    assert record["dataset"] == {"name": "dummy-detection", "version": "1.0.0"}
    assert record["taxonomy"] == {"name": "guardian-safety", "version": "1.0.0"}
    assert record["config"]["name"] == "record-test"
    assert record["git_commit"]  # commit hash or explicit "unknown", never empty
    assert record["status"] == "created"
    assert record["promotion"] is None
    assert experiment.checkpoints_dir.is_dir()
    assert experiment.reports_dir.is_dir()
    assert experiment.export_dir.is_dir()


def test_lifecycle_and_metrics(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    experiment.start()
    assert experiment.record["started_utc"] is not None
    experiment.set_metrics({"val": {"f1": 0.5}})
    experiment.set_checksum("model.onnx", "abc123")
    experiment.finish()

    reloaded = Experiment.load(experiment.run_dir)
    assert reloaded.record["status"] == "completed"
    assert reloaded.record["metrics"]["val"]["f1"] == 0.5
    assert reloaded.record["checksums"]["model.onnx"] == "abc123"
    assert reloaded.record["finished_utc"] is not None


def test_start_is_idempotent_for_resume(tmp_path: Path) -> None:
    experiment = make_experiment(tmp_path)
    experiment.start()
    first = experiment.record["started_utc"]
    experiment.start()  # resume path calls start() again
    assert experiment.record["started_utc"] == first


def test_load_refuses_anonymous_and_corrupt(tmp_path: Path) -> None:
    with pytest.raises(ExperimentError, match="no experiment record"):
        Experiment.load(tmp_path)
    (tmp_path / EXPERIMENT_FILE).write_text("{broken", encoding="utf-8")
    with pytest.raises(ExperimentError, match="corrupt"):
        Experiment.load(tmp_path)


def test_git_commit_never_empty(tmp_path: Path) -> None:
    assert git_commit(tmp_path)  # outside a checkout -> "unknown", not ""
