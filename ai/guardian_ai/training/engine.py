"""The training engine: reproducible, resumable, family-agnostic.

One Trainer drives any registered DetectorFamily through the same loop:
seeded setup → epochs of train/validate → checkpoints (last + best) →
early stopping → metrics into the experiment record. Interrupting at any
point loses at most one epoch: ``resume`` restores model, optimizer,
scheduler, epoch counter and the best checkpoint bookkeeping.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.evaluation.detection import evaluate_detections
from guardian_ai.training.config import TrainingConfig
from guardian_ai.training.data import RegistryDataModule
from guardian_ai.training.errors import ExperimentError, TrainingConfigurationError
from guardian_ai.training.experiment import Experiment
from guardian_ai.training.families import get_family

logger = logging.getLogger(__name__)

LAST_CHECKPOINT = "last.pt"
BEST_CHECKPOINT = "best.pt"
HISTORY_FILE = "history.json"


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 - global seeding is the point here
    torch.manual_seed(seed)


class Trainer:
    """Trains one experiment; every artifact lands in its run directory."""

    def __init__(self, config: TrainingConfig) -> None:
        self._config = config
        self._family = get_family(config.model.family)
        self._data = RegistryDataModule(config.dataset, config.model.input_size)

    @property
    def data(self) -> RegistryDataModule:
        return self._data

    @property
    def family(self) -> Any:
        return self._family

    # ------------------------------------------------------------ training

    def train(self, experiment: Experiment | None = None) -> Experiment:
        """Fresh run (or continuation when an experiment is passed)."""
        import torch

        config = self._config
        seed_everything(config.seed)
        if experiment is None:
            experiment = Experiment.create(
                config,
                dataset_name=self._data.dataset_name,
                dataset_version=self._data.dataset_version,
                taxonomy_name=self._data.taxonomy_name,
                taxonomy_version=self._data.taxonomy_version,
            )
        device = torch.device(config.device)
        model = self._family.build(len(self._data.class_names), config.model.input_size)
        model.to(device)
        optimizer = self._build_optimizer(model)
        scheduler = self._build_scheduler(optimizer)

        start_epoch = 0
        best_value: float | None = None
        epochs_without_improvement = 0
        history: list[dict[str, Any]] = []

        last_path = experiment.checkpoints_dir / LAST_CHECKPOINT
        if last_path.is_file():  # resume
            checkpoint = torch.load(last_path, weights_only=False)
            model.load_state_dict(checkpoint["model"])
            optimizer.load_state_dict(checkpoint["optimizer"])
            if scheduler is not None and checkpoint.get("scheduler") is not None:
                scheduler.load_state_dict(checkpoint["scheduler"])
            start_epoch = int(checkpoint["epoch"]) + 1
            best_value = checkpoint.get("best_value")
            epochs_without_improvement = int(checkpoint.get("stale_epochs", 0))
            history = self._load_history(experiment.run_dir)
            logger.info("resuming %s at epoch %d", experiment.experiment_id, start_epoch)

        experiment.start()
        metric_name = config.early_stopping.metric
        stopped_early = False

        for epoch in range(start_epoch, config.epochs):
            train_loss = self._train_epoch(model, optimizer, device, epoch)
            if scheduler is not None:
                scheduler.step()
            evaluation = self.evaluate(model, config.dataset.val_split)
            value = float(evaluation["overall"].get(metric_name, 0.0))
            improved = best_value is None or (
                value > best_value if config.early_stopping.mode == "max" else value < best_value
            )
            if improved:
                best_value = value
                epochs_without_improvement = 0
                self._save_checkpoint(
                    experiment.checkpoints_dir / BEST_CHECKPOINT,
                    model,
                    optimizer,
                    scheduler,
                    epoch,
                    best_value,
                    epochs_without_improvement,
                )
            else:
                epochs_without_improvement += 1

            history.append(
                {
                    "epoch": epoch,
                    "train_loss": round(train_loss, 6),
                    f"val_{metric_name}": round(value, 6),
                }
            )
            self._save_history(experiment.run_dir, history)
            self._save_checkpoint(
                experiment.checkpoints_dir / LAST_CHECKPOINT,
                model,
                optimizer,
                scheduler,
                epoch,
                best_value,
                epochs_without_improvement,
            )
            experiment.update(epochs_completed=epoch + 1)
            logger.info(
                "epoch %d/%d loss=%.4f val_%s=%.4f%s",
                epoch + 1,
                config.epochs,
                train_loss,
                metric_name,
                value,
                " (best)" if improved else "",
            )
            if (
                config.early_stopping.enabled
                and epochs_without_improvement >= config.early_stopping.patience
            ):
                stopped_early = True
                logger.info(
                    "early stopping: no %s improvement for %d epoch(s)",
                    metric_name,
                    config.early_stopping.patience,
                )
                break

        final = self.evaluate(self._best_model(experiment, model), config.dataset.val_split)
        experiment.set_metrics(
            {
                "val": final["overall"],
                "best_" + metric_name: best_value,
                "stopped_early": stopped_early,
            }
        )
        experiment.finish()
        return experiment

    def resume(self, run_dir: Path) -> Experiment:
        """Continue an interrupted run from its last checkpoint."""
        experiment = Experiment.load(run_dir)
        if not (experiment.checkpoints_dir / LAST_CHECKPOINT).is_file():
            raise ExperimentError(
                f"nothing to resume: {experiment.checkpoints_dir / LAST_CHECKPOINT} missing"
            )
        return self.train(experiment)

    # ---------------------------------------------------------- evaluation

    def evaluate(self, model: Any, split_name: str) -> dict[str, Any]:
        """Run the model over one split and compute the full metric set."""
        import torch

        model.eval()
        predictions = []
        ground_truths = []
        device = next(model.parameters()).device
        for images, boxes, labels in self._data.batches(split_name, self._config.batch_size):
            with torch.no_grad():
                outputs = model(torch.from_numpy(images).to(device))
            predictions.extend(self._family.decode(outputs))
            for index in range(len(labels)):
                ground_truths.append((boxes[index : index + 1], labels[index : index + 1]))
        model.train()
        return evaluate_detections(predictions, ground_truths, self._data.class_names)

    def load_best_model(self, experiment: Experiment) -> Any:
        import torch

        model = self._family.build(len(self._data.class_names), self._config.model.input_size)
        best = experiment.checkpoints_dir / BEST_CHECKPOINT
        if not best.is_file():
            raise ExperimentError(f"no best checkpoint at {best}")
        checkpoint = torch.load(best, weights_only=False)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        return model

    # ------------------------------------------------------------ internals

    def _best_model(self, experiment: Experiment, fallback: Any) -> Any:
        try:
            return self.load_best_model(experiment)
        except ExperimentError:
            return fallback

    def _train_epoch(self, model: Any, optimizer: Any, device: Any, epoch: int) -> float:
        import torch

        config = self._config
        batches = self._data.batches(
            config.dataset.train_split,
            config.batch_size,
            shuffle=True,
            augment=True,
            flip_probability=config.augmentation.horizontal_flip,
            seed=config.seed + epoch,
        )
        if not batches:
            raise TrainingConfigurationError(
                f"split '{config.dataset.train_split}' produced no batches"
            )
        model.train()
        total = 0.0
        for images, boxes, labels in batches:
            optimizer.zero_grad()
            outputs = model(torch.from_numpy(images).to(device))
            loss = self._family.loss(
                outputs,
                torch.from_numpy(boxes).to(device),
                torch.from_numpy(labels).to(device),
            )
            loss.backward()  # type: ignore[no-untyped-call]  # torch stubs gap
            optimizer.step()
            total += float(loss.detach())
        return total / len(batches)

    def _build_optimizer(self, model: Any) -> Any:
        import torch

        config = self._config.optimizer
        parameters = model.parameters()
        if config.name == "sgd":
            return torch.optim.SGD(
                parameters,
                lr=config.learning_rate,
                momentum=config.momentum,
                weight_decay=config.weight_decay,
            )
        if config.name == "adam":
            return torch.optim.Adam(
                parameters, lr=config.learning_rate, weight_decay=config.weight_decay
            )
        return torch.optim.AdamW(
            parameters, lr=config.learning_rate, weight_decay=config.weight_decay
        )

    def _build_scheduler(self, optimizer: Any) -> Any:
        import torch

        config = self._config
        if config.scheduler.name == "cosine":
            return torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer, T_max=max(config.epochs, 1)
            )
        if config.scheduler.name == "step":
            return torch.optim.lr_scheduler.StepLR(
                optimizer,
                step_size=config.scheduler.step_size,
                gamma=config.scheduler.gamma,
            )
        return None

    @staticmethod
    def _save_checkpoint(
        path: Path,
        model: Any,
        optimizer: Any,
        scheduler: Any,
        epoch: int,
        best_value: float | None,
        stale_epochs: int,
    ) -> None:
        import torch

        torch.save(
            {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict() if scheduler is not None else None,
                "epoch": epoch,
                "best_value": best_value,
                "stale_epochs": stale_epochs,
            },
            path,
        )

    @staticmethod
    def _save_history(run_dir: Path, history: list[dict[str, Any]]) -> None:
        (run_dir / HISTORY_FILE).write_text(json.dumps(history, indent=2), encoding="utf-8")

    @staticmethod
    def _load_history(run_dir: Path) -> list[dict[str, Any]]:
        path = run_dir / HISTORY_FILE
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8")))
