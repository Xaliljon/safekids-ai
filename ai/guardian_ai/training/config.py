"""Training configuration: one YAML, everything reproducible.

The config is the experiment's full recipe — model family, dataset
coordinates (registry-only), optimization, augmentation, early stopping,
seed and output directory. Loading validates loudly; a silently defaulted
knob is a lie in the experiment record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from guardian_ai.training.errors import TrainingConfigurationError

_OPTIMIZERS = ("sgd", "adam", "adamw")
_SCHEDULERS = ("none", "cosine", "step")
_ES_MODES = ("max", "min")
_DATASET_FORMATS = ("images", "video")


@dataclass(frozen=True, slots=True)
class ModelConfig:
    family: str
    input_size: int = 96
    """Square input edge in pixels (family may override constraints)."""
    pretrained: bool = False
    """Load the family's documented pretrained checkpoint (auto-downloaded,
    checksum-verified — Sprint 19.1). Ignored by families with no pretrained
    path (tiny-ssd). Off by default so tests/CI never trigger a network call."""
    checkpoint: str | None = None
    """Path to a custom checkpoint file — overrides `pretrained` when set."""


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    registry_root: Path
    name: str
    version: str | None = None  # None = latest registered version
    train_split: str = "train"
    val_split: str = "val"
    test_split: str = "test"
    format: str = "images"
    """"images" = Sprint 7 FileSystemDatasetRegistry (SampleRecord/JSONL).
    "video" = Sprint 18 VideoDatasetRegistry's pre-extracted training/
    export (guardian_dataset_v1 -> images/+labels/+data.yaml)."""
    max_samples: int | None = None
    """Cap each split to its first N images (sorted, so deterministic) —
    for bounded smoke/validation runs against a real, full-size published
    dataset. None (default) trains on the complete split, every sample."""


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
    name: str = "adamw"
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    momentum: float = 0.9  # sgd only


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    name: str = "cosine"
    step_size: int = 10  # step only
    gamma: float = 0.1  # step only
    warmup_epochs: int = 0
    """Linear LR warmup epochs before the main scheduler takes over (0 =
    none). Anchor-free detection heads (YOLOX) can numerically diverge at
    the paper's SGD learning rate without this — Sprint 19.1 disclosed the
    failure; Sprint 20 turns it on."""


@dataclass(frozen=True, slots=True)
class AugmentationConfig:
    horizontal_flip: float = 0.5
    """Probability of a horizontal flip (boxes flipped with the image)."""


@dataclass(frozen=True, slots=True)
class EarlyStoppingConfig:
    enabled: bool = True
    metric: str = "f1"
    mode: str = "max"
    patience: int = 5


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """The whole experiment recipe. Immutable once loaded."""

    name: str
    model: ModelConfig
    dataset: DatasetConfig
    epochs: int
    batch_size: int
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    augmentation: AugmentationConfig = field(default_factory=AugmentationConfig)
    early_stopping: EarlyStoppingConfig = field(default_factory=EarlyStoppingConfig)
    seed: int = 2026
    output_dir: Path = Path("ai/training/runs")
    device: str = "cpu"
    """cpu by default: deterministic and universal; cuda/mps opt-in."""
    workers: int = 0
    """Parallel data-loading threads (video dataset format only); 0 = main thread."""
    mixed_precision: bool = False
    """torch.autocast during training; GradScaler is added automatically on cuda."""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise TrainingConfigurationError("experiment name must not be empty")
        if self.epochs < 1:
            raise TrainingConfigurationError(f"epochs must be >= 1, got {self.epochs}")
        if self.batch_size < 1:
            raise TrainingConfigurationError(f"batch_size must be >= 1, got {self.batch_size}")
        if self.optimizer.name not in _OPTIMIZERS:
            raise TrainingConfigurationError(
                f"unknown optimizer '{self.optimizer.name}' (one of {_OPTIMIZERS})"
            )
        if self.optimizer.learning_rate <= 0:
            raise TrainingConfigurationError("learning_rate must be positive")
        if self.scheduler.name not in _SCHEDULERS:
            raise TrainingConfigurationError(
                f"unknown scheduler '{self.scheduler.name}' (one of {_SCHEDULERS})"
            )
        if self.scheduler.warmup_epochs < 0:
            raise TrainingConfigurationError("scheduler.warmup_epochs must be >= 0")
        if self.scheduler.warmup_epochs >= self.epochs:
            raise TrainingConfigurationError(
                f"scheduler.warmup_epochs ({self.scheduler.warmup_epochs}) must be < "
                f"epochs ({self.epochs})"
            )
        if self.early_stopping.mode not in _ES_MODES:
            raise TrainingConfigurationError(f"early_stopping.mode must be one of {_ES_MODES}")
        if self.early_stopping.patience < 1:
            raise TrainingConfigurationError("early_stopping.patience must be >= 1")
        if not (0.0 <= self.augmentation.horizontal_flip <= 1.0):
            raise TrainingConfigurationError("horizontal_flip must be a probability")
        if self.model.input_size < 32:
            raise TrainingConfigurationError("model.input_size must be >= 32")
        if self.dataset.format not in _DATASET_FORMATS:
            raise TrainingConfigurationError(
                f"unknown dataset.format '{self.dataset.format}' (one of {_DATASET_FORMATS})"
            )
        if self.dataset.max_samples is not None and self.dataset.max_samples < 1:
            raise TrainingConfigurationError("dataset.max_samples must be >= 1 when set")
        if self.workers < 0:
            raise TrainingConfigurationError("workers must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": {
                "family": self.model.family,
                "input_size": self.model.input_size,
                "pretrained": self.model.pretrained,
                "checkpoint": self.model.checkpoint,
            },
            "dataset": {
                "registry_root": str(self.dataset.registry_root),
                "name": self.dataset.name,
                "version": self.dataset.version,
                "train_split": self.dataset.train_split,
                "val_split": self.dataset.val_split,
                "test_split": self.dataset.test_split,
                "format": self.dataset.format,
                "max_samples": self.dataset.max_samples,
            },
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "optimizer": {
                "name": self.optimizer.name,
                "learning_rate": self.optimizer.learning_rate,
                "weight_decay": self.optimizer.weight_decay,
                "momentum": self.optimizer.momentum,
            },
            "scheduler": {
                "name": self.scheduler.name,
                "step_size": self.scheduler.step_size,
                "gamma": self.scheduler.gamma,
                "warmup_epochs": self.scheduler.warmup_epochs,
            },
            "augmentation": {"horizontal_flip": self.augmentation.horizontal_flip},
            "early_stopping": {
                "enabled": self.early_stopping.enabled,
                "metric": self.early_stopping.metric,
                "mode": self.early_stopping.mode,
                "patience": self.early_stopping.patience,
            },
            "seed": self.seed,
            "output_dir": str(self.output_dir),
            "device": self.device,
            "workers": self.workers,
            "mixed_precision": self.mixed_precision,
        }


def load_config(path: Path) -> TrainingConfig:
    """Load and validate a training YAML; unknown keys are errors."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TrainingConfigurationError(f"cannot read config '{path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise TrainingConfigurationError(f"'{path}' is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TrainingConfigurationError(f"'{path}' must be a mapping at the top level")
    return config_from_dict(raw, source=str(path))


def config_from_dict(raw: dict[str, Any], source: str = "<dict>") -> TrainingConfig:
    known = {
        "name",
        "model",
        "dataset",
        "epochs",
        "batch_size",
        "optimizer",
        "scheduler",
        "augmentation",
        "early_stopping",
        "seed",
        "output_dir",
        "device",
        "workers",
        "mixed_precision",
    }
    unknown = set(raw) - known
    if unknown:
        raise TrainingConfigurationError(
            f"{source}: unknown config keys {sorted(unknown)} — "
            "misspelled knobs must fail, not silently default"
        )
    try:
        model_raw = dict(raw["model"])
        dataset_raw = dict(raw["dataset"])
        return TrainingConfig(
            name=str(raw["name"]),
            model=ModelConfig(
                family=str(model_raw["family"]),
                input_size=int(model_raw.get("input_size", 96)),
                pretrained=bool(model_raw.get("pretrained", False)),
                checkpoint=(str(model_raw["checkpoint"]) if model_raw.get("checkpoint") else None),
            ),
            dataset=DatasetConfig(
                registry_root=Path(str(dataset_raw["registry_root"])),
                name=str(dataset_raw["name"]),
                version=(str(dataset_raw["version"]) if dataset_raw.get("version") else None),
                train_split=str(dataset_raw.get("train_split", "train")),
                val_split=str(dataset_raw.get("val_split", "val")),
                test_split=str(dataset_raw.get("test_split", "test")),
                format=str(dataset_raw.get("format", "images")),
                max_samples=(
                    int(dataset_raw["max_samples"]) if dataset_raw.get("max_samples") else None
                ),
            ),
            epochs=int(raw["epochs"]),
            batch_size=int(raw["batch_size"]),
            optimizer=OptimizerConfig(**dict(raw.get("optimizer", {}))),
            scheduler=SchedulerConfig(**dict(raw.get("scheduler", {}))),
            augmentation=AugmentationConfig(**dict(raw.get("augmentation", {}))),
            early_stopping=EarlyStoppingConfig(**dict(raw.get("early_stopping", {}))),
            seed=int(raw.get("seed", 2026)),
            output_dir=Path(str(raw.get("output_dir", "ai/training/runs"))),
            device=str(raw.get("device", "cpu")),
            workers=int(raw.get("workers", 0)),
            mixed_precision=bool(raw.get("mixed_precision", False)),
        )
    except KeyError as exc:
        raise TrainingConfigurationError(f"{source}: missing required key {exc}") from exc
    except TypeError as exc:
        raise TrainingConfigurationError(f"{source}: {exc}") from exc
