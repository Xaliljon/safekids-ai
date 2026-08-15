"""Engine: smoke training, resume, early stopping — on a real registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from training_fixtures import make_training_config, publish_tiny_dataset

from guardian_ai.training.config import EarlyStoppingConfig, config_from_dict
from guardian_ai.training.engine import (
    BEST_CHECKPOINT,
    HISTORY_FILE,
    LAST_CHECKPOINT,
    METRICS_FILE,
    TRAINING_LOG,
    Trainer,
    _improved,
    _is_saturated,
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
    assert "val_map50_95" in history[0]

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


def test_last_checkpoint_carries_rng_and_scaler_slots(registry_root: Path, tmp_path: Path) -> None:
    import torch

    config = make_training_config(registry_root, tmp_path / "runs", epochs=1)
    experiment = Trainer(config).train()
    checkpoint = torch.load(experiment.checkpoints_dir / LAST_CHECKPOINT, weights_only=False)
    # Sprint 20.1: resume must restore the full training state, not just weights.
    assert "rng" in checkpoint
    assert {"python", "numpy", "torch"} <= set(checkpoint["rng"])
    assert "scaler" in checkpoint  # None on CPU (no AMP), but the slot is present
    assert "optimizer" in checkpoint
    assert "scheduler" in checkpoint
    assert checkpoint["epoch"] == 0


def test_every_epoch_flushes_metrics_and_training_log(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs", epochs=2)
    experiment = Trainer(config).train()

    metrics = json.loads((experiment.run_dir / METRICS_FILE).read_text())
    assert metrics["epochs_completed"] == 2
    assert metrics["epochs_planned"] == 2
    assert len(metrics["history"]) == 2
    assert metrics["metric"] == config.early_stopping.metric
    assert "final_val" in metrics  # written after the final evaluation

    log_text = (experiment.run_dir / TRAINING_LOG).read_text()
    assert "epoch 1/2" in log_text and "epoch 2/2" in log_text


def test_no_temp_files_left_behind(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs", epochs=1)
    experiment = Trainer(config).train()
    # atomic writes rename a .tmp into place — none should survive a clean run
    stray = list(experiment.run_dir.rglob("*.tmp"))
    assert stray == []


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


def test_warmup_scheduler_ramps_up_then_anneals(registry_root: Path, tmp_path: Path) -> None:
    import torch

    base = make_training_config(registry_root, tmp_path / "runs", epochs=6)
    config = config_from_dict(
        {**base.to_dict(), "scheduler": {"name": "cosine", "warmup_epochs": 2}}
    )
    trainer = Trainer(config)
    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scheduler = trainer._build_scheduler(optimizer)

    lrs = [optimizer.param_groups[0]["lr"]]
    for _ in range(5):
        scheduler.step()
        lrs.append(optimizer.param_groups[0]["lr"])

    assert lrs[0] < lrs[1] < lrs[2]  # linear warmup ramps up for 2 epochs
    peak = lrs[2]
    assert all(later <= peak + 1e-9 for later in lrs[3:])  # cosine never exceeds the peak
    assert lrs[-1] < peak  # and anneals down from it


def test_resume_restores_warmup_scheduler_state(registry_root: Path, tmp_path: Path) -> None:
    base = make_training_config(registry_root, tmp_path / "runs", epochs=3)
    config = config_from_dict(
        {**base.to_dict(), "scheduler": {"name": "cosine", "warmup_epochs": 2}}
    )
    experiment = Trainer(config).train()

    longer = config_from_dict({**config.to_dict(), "epochs": 5})
    resumed = Trainer(longer).resume(experiment.run_dir)
    assert resumed.record["epochs_completed"] == 5
    history = json.loads((resumed.run_dir / HISTORY_FILE).read_text())
    assert [entry["epoch"] for entry in history] == [0, 1, 2, 3, 4]


def test_checkpoint_checksum_is_recorded_when_family_reports_one(
    registry_root: Path, tmp_path: Path
) -> None:
    config = make_training_config(registry_root, tmp_path / "runs", epochs=1)
    trainer = Trainer(config)
    original_build = trainer.family.build

    def build_with_checkpoint(*args: object, **kwargs: object) -> object:
        model = original_build(*args, **kwargs)  # type: ignore[misc]
        model.checkpoint_sha256 = "deadbeef" * 8  # type: ignore[attr-defined]
        return model

    trainer._family.build = build_with_checkpoint  # type: ignore[method-assign]
    experiment = trainer.train()
    assert experiment.record["checksums"]["checkpoint"] == "deadbeef" * 8


def test_no_checkpoint_checksum_when_family_reports_none(
    registry_root: Path, tmp_path: Path
) -> None:
    config = make_training_config(registry_root, tmp_path / "runs", epochs=1)
    experiment = Trainer(config).train()
    assert "checkpoint" not in experiment.record["checksums"]


def test_reserved_family_cannot_reach_the_engine(registry_root: Path, tmp_path: Path) -> None:
    config = make_training_config(registry_root, tmp_path / "runs")
    reserved = config.to_dict()
    reserved["model"]["family"] = "yolov8"  # AGPL-blocked (ADR-0003), still reserved
    from guardian_ai.training.config import config_from_dict

    with pytest.raises(TrainingConfigurationError, match="reserved"):
        Trainer(config_from_dict(reserved))


# ------------------------------------- early stopping: ceiling vs. plateau


def test_min_delta_ignores_noise_level_improvement() -> None:
    """Without it, a metric wobbling at the fifth decimal resets patience
    forever — the failure opposite to saturation and just as invisible."""
    config = EarlyStoppingConfig(metric="map50_95", mode="max", min_delta=0.001)
    assert _improved(0.5011, 0.5000, config) is True
    assert _improved(0.50005, 0.5000, config) is False


def test_min_delta_zero_keeps_the_historical_behaviour() -> None:
    config = EarlyStoppingConfig(metric="map50_95", mode="max", min_delta=0.0)
    assert _improved(0.50001, 0.5000, config) is True
    assert _improved(0.5000, 0.5000, config) is False


def test_first_epoch_always_improves() -> None:
    assert _improved(0.0, None, EarlyStoppingConfig(min_delta=0.5)) is True


def test_min_mode_improves_downwards() -> None:
    config = EarlyStoppingConfig(metric="loss", mode="min", min_delta=0.01)
    assert _improved(0.90, 1.0, config) is True
    assert _improved(0.999, 1.0, config) is False


@pytest.mark.parametrize("metric", ["f1", "precision", "recall", "map50", "map50_95"])
def test_bounded_metric_at_one_is_saturated(metric: str) -> None:
    """Sprint 20's run, exactly: F1 pinned at 1.0 while the loss still fell.
    "No improvement" there is arithmetic, not evidence."""
    assert _is_saturated(metric, 1.0, "max") is True


def test_bounded_metric_below_one_is_a_real_plateau() -> None:
    assert _is_saturated("map50_95", 0.9999, "max") is False


def test_unbounded_metric_is_never_called_saturated() -> None:
    """Loss has no ceiling, so patience expiring on it means what it says."""
    assert _is_saturated("loss", 1.0, "min") is False


def test_min_mode_saturates_at_zero() -> None:
    assert _is_saturated("f1", 0.0, "min") is True
    assert _is_saturated("f1", 0.0001, "min") is False
