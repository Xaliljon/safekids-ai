"""Engine: smoke training, resume, early stopping — on a real registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from training_fixtures import make_training_config, publish_tiny_dataset

from guardian_ai.training.config import EarlyStoppingConfig
from guardian_ai.training.engine import (
    BEST_CHECKPOINT,
    HISTORY_FILE,
    LAST_CHECKPOINT,
    Trainer,
)
from guardian_ai.training.errors import ExperimentError, TrainingConfigurationError
from guardian_ai.training.experiment import Experiment


@pytest.fixture(scope="module")
def registry_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("registry")
    publish_tiny_dataset(root)
    return root


def test_smoke_training_produces_full_run(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs", epochs=2)
    experiment = Trainer(config).train()

    assert experiment.record["status"] == "completed"
    assert experiment.record["epochs_completed"] == 2
    assert (experiment.checkpoints_dir / LAST_CHECKPOINT).is_file()
    assert (experiment.checkpoints_dir / BEST_CHECKPOINT).is_file()

    history = json.loads((experiment.run_dir / HISTORY_FILE).read_text())
    assert len(history) == 2
    assert history[0]["epoch"] == 0
    assert "train_loss" in history[0]
    assert "val_f1" in history[0]

    metrics = experiment.record["metrics"]
    assert set(metrics["val"]) >= {
        "precision",
        "recall",
        "f1",
        "map50",
        "map50_95",
        "false_positives",
        "false_negatives",
        "images",
    }
    assert metrics["stopped_early"] is False


def test_training_is_reproducible(registry_root: Path, tmp_path: Path) -> None:
    first = Trainer(make_training_config(registry_root, tmp_path / "a", name="repro")).train()
    second = Trainer(make_training_config(registry_root, tmp_path / "b", name="repro")).train()
    first_history = json.loads((first.run_dir / HISTORY_FILE).read_text())
    second_history = json.loads((second.run_dir / HISTORY_FILE).read_text())
    assert first_history == second_history  # same seed -> same numbers


def test_resume_restores_and_continues(registry_root: Path, tmp_path: Path) -> None:
    short = make_training_config(registry_root, tmp_path / "runs", epochs=2)
    experiment = Trainer(short).train()

    longer = make_training_config(registry_root, tmp_path / "runs", epochs=4)
    resumed = Trainer(longer).resume(experiment.run_dir)
    assert resumed.experiment_id == experiment.experiment_id
    assert resumed.record["epochs_completed"] == 4
    history = json.loads((resumed.run_dir / HISTORY_FILE).read_text())
    assert [entry["epoch"] for entry in history] == [0, 1, 2, 3]


def test_resume_without_checkpoint_is_refused(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs")
    experiment = Experiment.create(
        config,
        dataset_name="tiny-synthetic",
        dataset_version="1.0.0",
        taxonomy_name="guardian-safety",
        taxonomy_version="1.0.0",
    )
    with pytest.raises(ExperimentError, match="nothing to resume"):
        Trainer(config).resume(experiment.run_dir)


def test_early_stopping_stops_a_flat_run(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(
        registry_root,
        tmp_path / "runs",
        epochs=10,
        early_stopping=EarlyStoppingConfig(enabled=True, patience=2),
    )
    experiment = Trainer(config).train()
    # tiny run cannot improve f1 for 10 epochs; patience must cut it short
    assert experiment.record["epochs_completed"] < 10
    assert experiment.record["metrics"]["stopped_early"] is True


def test_evaluate_full_metric_structure(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs")
    trainer = Trainer(config)
    experiment = trainer.train()
    model = trainer.load_best_model(experiment)
    evaluation = trainer.evaluate(model, "test")
    assert evaluation["overall"]["images"] == 3
    assert set(evaluation["per_class"]) == {"adult", "child", "person"}
    assert evaluation["confusion_matrix"]["labels"][-1] == "background"


def test_reserved_family_cannot_reach_the_engine(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs")
    reserved = config.to_dict()
    reserved["model"]["family"] = "yolov8"  # AGPL-blocked (ADR-0003), still reserved
    from guardian_ai.training.config import config_from_dict

    with pytest.raises(TrainingConfigurationError, match="reserved"):
        Trainer(config_from_dict(reserved))
