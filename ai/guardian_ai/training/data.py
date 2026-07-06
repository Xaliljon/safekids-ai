"""Dataset access for training: the registry is the ONLY door.

Training never reads random folders (Sprint 17 rule). A DataModule
resolves its dataset through the Sprint-7 FileSystemDatasetRegistry —
which verifies checksums, privacy declarations and taxonomy binding —
and serves train/val/test splits as tensors.

Samples are single-object detection targets for V1: the first annotation
of each record is the target box+class (the smoke family's contract);
multi-object families consume the full annotation tuple.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from guardian_ai.datasets.annotations import SampleRecord
from guardian_ai.datasets.registry import FileSystemDatasetRegistry, RegisteredDataset
from guardian_ai.datasets.taxonomy import GUARDIAN_TAXONOMY_V1, LabelTaxonomy
from guardian_ai.training.config import DatasetConfig
from guardian_ai.training.errors import TrainingConfigurationError

_KNOWN_TAXONOMIES: dict[tuple[str, str], LabelTaxonomy] = {
    (GUARDIAN_TAXONOMY_V1.name, GUARDIAN_TAXONOMY_V1.version): GUARDIAN_TAXONOMY_V1,
}


@dataclass(frozen=True, slots=True)
class Sample:
    """One training sample: image tensor data + target box/class."""

    image: np.ndarray  # CHW float32 in [0, 1]
    box: np.ndarray  # (4,) normalized cx, cy, w, h
    label: int
    path: str


class RegistryDataModule:
    """Train/val/test splits, loaded exclusively through the registry."""

    def __init__(self, config: DatasetConfig, input_size: int) -> None:
        registry = FileSystemDatasetRegistry(config.registry_root)
        self._dataset: RegisteredDataset = registry.get(config.name, config.version)
        self._config = config
        self._input_size = input_size
        manifest = self._dataset.manifest
        taxonomy = _KNOWN_TAXONOMIES.get((manifest.taxonomy_name, manifest.taxonomy_version))
        if taxonomy is None:
            raise TrainingConfigurationError(
                f"dataset '{manifest.name}' binds unknown taxonomy "
                f"{manifest.taxonomy_name}@{manifest.taxonomy_version}"
            )
        self._taxonomy = taxonomy
        self._class_names = sorted(taxonomy.label_names())

    # ------------------------------------------------------------- facts

    @property
    def dataset_name(self) -> str:
        return self._dataset.manifest.name

    @property
    def dataset_version(self) -> str:
        return self._dataset.manifest.version

    @property
    def taxonomy_name(self) -> str:
        return self._dataset.manifest.taxonomy_name

    @property
    def taxonomy_version(self) -> str:
        return self._dataset.manifest.taxonomy_version

    @property
    def license(self) -> str:
        return self._dataset.manifest.license

    @property
    def class_names(self) -> list[str]:
        return list(self._class_names)

    def class_index(self, label: str) -> int:
        try:
            return self._class_names.index(label)
        except ValueError as exc:
            raise TrainingConfigurationError(
                f"label '{label}' is not in taxonomy {self.taxonomy_name}@{self.taxonomy_version}"
            ) from exc

    # ------------------------------------------------------------ loading

    def split(self, name: str) -> list[SampleRecord]:
        return self._dataset.load_split(name)

    def samples(
        self,
        split_name: str,
        augment: bool = False,
        flip_probability: float = 0.0,
        rng: random.Random | None = None,
    ) -> list[Sample]:
        """Materialize one split as training samples (images loaded)."""
        rng = rng or random.Random(0)  # noqa: S311 - reproducible augmentation, not crypto
        samples: list[Sample] = []
        for record in self.split(split_name):
            image = self._load_image(record)
            if not record.annotations:
                continue  # background-only samples are future work
            annotation = record.annotations[0]
            box = annotation.box
            center = np.array(
                [box.x + box.width / 2, box.y + box.height / 2, box.width, box.height],
                dtype=np.float32,
            )
            label = self.class_index(annotation.label)
            if augment and flip_probability > 0 and rng.random() < flip_probability:
                image = image[:, :, ::-1].copy()  # CHW horizontal flip
                center[0] = 1.0 - center[0]
            samples.append(Sample(image=image, box=center, label=label, path=record.path))
        return samples

    def batches(
        self,
        split_name: str,
        batch_size: int,
        shuffle: bool = False,
        augment: bool = False,
        flip_probability: float = 0.0,
        seed: int = 0,
    ) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """(images, boxes, labels) mini-batches as numpy arrays."""
        rng = random.Random(seed)  # noqa: S311 - reproducible shuffling, not crypto
        samples = self.samples(
            split_name, augment=augment, flip_probability=flip_probability, rng=rng
        )
        if shuffle:
            rng.shuffle(samples)
        result = []
        for start in range(0, len(samples), batch_size):
            chunk = samples[start : start + batch_size]
            result.append(
                (
                    np.stack([sample.image for sample in chunk]),
                    np.stack([sample.box for sample in chunk]),
                    np.array([sample.label for sample in chunk], dtype=np.int64),
                )
            )
        return result

    def _load_image(self, record: SampleRecord) -> np.ndarray:
        path = self._media_path(record)
        try:
            with Image.open(path) as handle:
                resized = handle.convert("RGB").resize((self._input_size, self._input_size))
                array = np.asarray(resized, dtype=np.float32) / 255.0
        except OSError as exc:
            raise TrainingConfigurationError(
                f"sample media unreadable: {path} ({exc}) — datasets must be "
                "complete before training"
            ) from exc
        return np.transpose(array, (2, 0, 1))  # HWC -> CHW

    def _media_path(self, record: SampleRecord) -> Path:
        return self._dataset.root / "media" / record.path
