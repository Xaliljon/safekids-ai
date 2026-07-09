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
import os
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
from guardian_ai.training.video_data import VideoRegistryDataModule

logger = logging.getLogger(__name__)

LAST_CHECKPOINT = "last.pt"
BEST_CHECKPOINT = "best.pt"
HISTORY_FILE = "history.json"
METRICS_FILE = "metrics.json"
TRAINING_LOG = "training.log"


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 - global seeding is the point here
    torch.manual_seed(seed)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a sibling temp file then rename, so a reader (or a crash)
    never sees a half-written file — matters when the run dir is a Drive
    mount being flushed every epoch."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Trainer:
    """Trains one experiment; every artifact lands in its run directory."""

    def __init__(self, config: TrainingConfig) -> None:
        self._config = config
        self._family = get_family(config.model.family)
        if config.dataset.format == "video":
            self._data: Any = VideoRegistryDataModule(
                config.dataset, config.model.input_size, workers=config.workers
            )
        else:
            self._data = RegistryDataModule(config.dataset, config.model.input_size)

    @property
    def data(self) -> Any:
        return self._data

    @property
    def family(self) -> Any:
        return self._family

    # ------------------------------------------------------------ training

    def train(self, experiment: Experiment | None = None) -> Experiment:
        """Fresh run (or continuation when an experiment is passed).

        Every epoch atomically flushes ``last.pt`` (model, optimizer,
        scheduler, AMP scaler, RNG state and epoch), ``history.json``,
        ``metrics.json`` and ``experiment.json``, and appends to
        ``training.log`` — so an interrupted run (e.g. a Colab disconnect)
        loses at most the epoch in progress and resumes from the next one.
        """
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
        log_handler = self._attach_log_file(experiment.run_dir)
        try:
            device = torch.device(config.device)
            checkpoint_path = Path(config.model.checkpoint) if config.model.checkpoint else None
            model = self._family.build(
                len(self._data.class_names),
                config.model.input_size,
                pretrained=config.model.pretrained,
                checkpoint=checkpoint_path,
            )
            model.to(device)
            # Set by a DetectorFamily.build() that loaded a checkpoint (custom
            # or auto-downloaded pretrained) — a duck-typed, optional attribute
            # so the engine records provenance without knowing any detector's
            # internals (the isolation principle from Sprint 19.1).
            checkpoint_sha256 = getattr(model, "checkpoint_sha256", None)
            if checkpoint_sha256:
                experiment.set_checksum("checkpoint", checkpoint_sha256)
            optimizer = self._build_optimizer(model)
            scheduler = self._build_scheduler(optimizer)

            # The AMP scaler is created ONCE here (not per-epoch) so its loss
            # scale and growth tracker persist into the checkpoint and survive
            # a resume — otherwise every reconnect would reset the scale.
            autocast_type = device.type if device.type in ("cpu", "cuda") else None
            use_amp = config.mixed_precision and autocast_type is not None
            scaler = (
                torch.amp.GradScaler(device.type)  # type: ignore[attr-defined]
                if use_amp and device.type == "cuda"
                else None
            )

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
                if scaler is not None and checkpoint.get("scaler") is not None:
                    scaler.load_state_dict(checkpoint["scaler"])
                self._restore_rng_state(checkpoint.get("rng"))
                start_epoch = int(checkpoint["epoch"]) + 1
                best_value = checkpoint.get("best_value")
                epochs_without_improvement = int(checkpoint.get("stale_epochs", 0))
                history = self._load_history(experiment.run_dir)
                logger.info("resuming %s at epoch %d", experiment.experiment_id, start_epoch)

            experiment.start()
            metric_name = config.early_stopping.metric
            stopped_early = False

            for epoch in range(start_epoch, config.epochs):
                train_loss = self._train_epoch(
                    model, optimizer, device, epoch, scaler, use_amp, autocast_type
                )
                if scheduler is not None:
                    scheduler.step()
                evaluation = self.evaluate(model, config.dataset.val_split)
                value = float(evaluation["overall"].get(metric_name, 0.0))
                improved = best_value is None or (
                    value > best_value
                    if config.early_stopping.mode == "max"
                    else value < best_value
                )
                if improved:
                    best_value = value
                    epochs_without_improvement = 0
                    self._save_checkpoint(
                        experiment.checkpoints_dir / BEST_CHECKPOINT,
                        model,
                        optimizer,
                        scheduler,
                        scaler,
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
                # last.pt after history so a crash between the two never leaves
                # a checkpoint that is ahead of its own recorded history.
                self._save_checkpoint(
                    experiment.checkpoints_dir / LAST_CHECKPOINT,
                    model,
                    optimizer,
                    scheduler,
                    scaler,
                    epoch,
                    best_value,
                    epochs_without_improvement,
                )
                self._save_metrics(
                    experiment.run_dir,
                    metric_name,
                    best_value,
                    epoch + 1,
                    config.epochs,
                    stopped_early,
                    history,
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
            self._save_metrics(
                experiment.run_dir,
                metric_name,
                best_value,
                experiment.record["epochs_completed"],
                config.epochs,
                stopped_early,
                history,
                final["overall"],
            )
            experiment.finish()
            return experiment
        finally:
            self._detach_log_file(log_handler)

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
        predictions, ground_truths, _paths = self.predict_split(model, split_name)
        return evaluate_detections(predictions, ground_truths, self._data.class_names)

    def predict_split(
        self, model: Any, split_name: str
    ) -> tuple[list[Any], list[tuple[np.ndarray, np.ndarray]], list[str]]:
        """Predictions + ground truths + image paths, one triple per image —
        the shared basis for metrics, error analysis and qualitative export."""
        import torch

        model.eval()
        predictions = []
        ground_truths: list[tuple[np.ndarray, np.ndarray]] = []
        paths: list[str] = []
        device = next(model.parameters()).device
        for images, targets, batch_paths in self._data.batches(split_name, self._config.batch_size):
            with torch.no_grad():
                outputs = model(torch.from_numpy(images).to(device))
            predictions.extend(self._family.decode(outputs))
            ground_truths.extend(targets)  # already (boxes_i, labels_i) per image
            paths.extend(batch_paths)
        model.train()
        return predictions, ground_truths, paths

    def load_best_model(self, experiment: Experiment) -> Any:
        import torch

        # pretrained=False: best.pt is about to overwrite every weight anyway
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

    def _train_epoch(
        self,
        model: Any,
        optimizer: Any,
        device: Any,
        epoch: int,
        scaler: Any,
        use_amp: bool,
        autocast_type: str | None,
    ) -> float:
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
        for images, raw_targets, _paths in batches:
            optimizer.zero_grad()
            targets = [
                (torch.from_numpy(boxes).to(device), torch.from_numpy(labels).to(device))
                for boxes, labels in raw_targets
            ]
            with torch.autocast(device_type=autocast_type or "cpu", enabled=use_amp):
                outputs = model(torch.from_numpy(images).to(device))
                loss = self._family.loss(outputs, targets)
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
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
        warmup_epochs = config.scheduler.warmup_epochs
        main = self._build_main_scheduler(optimizer, warmup_epochs)
        if main is None or warmup_epochs <= 0:
            return main
        # Linear warmup then the main schedule — epoch-granular (the engine
        # steps once per epoch, matching the rest of this scheduler API).
        # Without this, SGD at the paper's learning rate can numerically
        # diverge on anchor-free heads (disclosed in Sprint 19.1's
        # comparison report; upstream YOLOX budgets 5 warmup epochs itself).
        warmup = torch.optim.lr_scheduler.LinearLR(
            optimizer, start_factor=1e-3, total_iters=warmup_epochs
        )
        return torch.optim.lr_scheduler.SequentialLR(
            optimizer, schedulers=[warmup, main], milestones=[warmup_epochs]
        )

    def _build_main_scheduler(self, optimizer: Any, warmup_epochs: int) -> Any:
        import torch

        config = self._config
        remaining_epochs = max(config.epochs - warmup_epochs, 1)
        if config.scheduler.name == "cosine":
            return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=remaining_epochs)
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
        scaler: Any,
        epoch: int,
        best_value: float | None,
        stale_epochs: int,
    ) -> None:
        import torch

        payload = {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict() if scheduler is not None else None,
            "scaler": scaler.state_dict() if scaler is not None else None,
            "epoch": epoch,
            "best_value": best_value,
            "stale_epochs": stale_epochs,
            "rng": Trainer._rng_state(),
        }
        # Write to a sibling temp file then atomically rename: a crash (or a
        # Colab disconnect) mid-save can never leave a truncated checkpoint.
        tmp = path.with_name(path.name + ".tmp")
        torch.save(payload, tmp)
        os.replace(tmp, path)

    @staticmethod
    def _rng_state() -> dict[str, Any]:
        """Capture every RNG the training loop draws from, so a resumed run
        continues the exact same random stream (augmentation, dropout, …)."""
        import torch

        state: dict[str, Any] = {
            "python": random.getstate(),
            "numpy": np.random.get_state(),
            "torch": torch.get_rng_state(),
        }
        if torch.cuda.is_available():
            state["torch_cuda"] = torch.cuda.get_rng_state_all()
        return state

    @staticmethod
    def _restore_rng_state(state: dict[str, Any] | None) -> None:
        if not state:
            return
        import torch

        random.setstate(state["python"])
        np.random.set_state(state["numpy"])
        torch.set_rng_state(state["torch"])
        cuda_state = state.get("torch_cuda")
        if cuda_state is not None and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(cuda_state)

    @staticmethod
    def _save_history(run_dir: Path, history: list[dict[str, Any]]) -> None:
        _atomic_write_text(run_dir / HISTORY_FILE, json.dumps(history, indent=2))

    @staticmethod
    def _load_history(run_dir: Path) -> list[dict[str, Any]]:
        path = run_dir / HISTORY_FILE
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _save_metrics(
        run_dir: Path,
        metric: str,
        best_value: float | None,
        epochs_completed: int,
        epochs_planned: int,
        stopped_early: bool,
        history: list[dict[str, Any]],
        final_val: dict[str, Any] | None = None,
    ) -> None:
        """Per-epoch metrics snapshot, flushed every epoch so a disconnect
        never loses the record of what has trained so far."""
        payload: dict[str, Any] = {
            "metric": metric,
            f"best_{metric}": best_value,
            "epochs_completed": epochs_completed,
            "epochs_planned": epochs_planned,
            "stopped_early": stopped_early,
            "history": history,
        }
        if final_val is not None:
            payload["final_val"] = final_val
        _atomic_write_text(run_dir / METRICS_FILE, json.dumps(payload, indent=2))

    @staticmethod
    def _attach_log_file(run_dir: Path) -> logging.Handler | None:
        """Tee guardian_ai's logs to run_dir/training.log for this run. The
        FileHandler flushes per record, so the log on disk (Drive, on Colab)
        stays current epoch by epoch. Returns None if already attached."""
        log_path = (run_dir / TRAINING_LOG).resolve()
        pkg_logger = logging.getLogger("guardian_ai")
        for existing in pkg_logger.handlers:
            if isinstance(existing, logging.FileHandler) and getattr(
                existing, "baseFilename", None
            ) == str(log_path):
                return None
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        pkg_logger.addHandler(handler)
        if pkg_logger.level == logging.NOTSET or pkg_logger.level > logging.INFO:
            pkg_logger.setLevel(logging.INFO)
        return handler

    @staticmethod
    def _detach_log_file(handler: logging.Handler | None) -> None:
        if handler is None:
            return
        logging.getLogger("guardian_ai").removeHandler(handler)
        handler.close()
