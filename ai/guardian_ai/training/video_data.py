"""Video-dataset access for training: reads the Sprint-18 training export.

``guardian_dataset_v1`` datasets (Sprint 18) publish through a *different*
registry than the Sprint-7 image dataset platform — checksummed video
clips plus a pre-extracted, deterministic ``training/`` export
(``data.yaml`` + ``images/{split}/*.png`` + ``labels/{split}/*.txt`` in
normalized YOLO format). This module is the ONLY door onto that export:
resolution goes through ``VideoDatasetRegistry.get()``, which verifies
every file's checksum before this module reads a single byte.

Images are letterboxed onto a square canvas (centered, zero-padded) so a
640x480 source and a 640x640 model input agree on geometry; box
coordinates are transformed through the exact same padding.

Real published datasets export one image per ANNOTATED FRAME, not per
clip — guardian-fall-detection-v1's train split alone is ~20,000 images.
Materializing that as decoded float32 tensors up front would need tens
of gigabytes of RAM, so ``batches()`` is lazy: it returns a sized,
iterable ``LazyBatches`` that decodes only the batch currently being
consumed, keeping peak memory at O(batch_size).
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from guardian_ai.acquisition.registry import VideoDatasetRegistry
from guardian_ai.training.config import DatasetConfig
from guardian_ai.training.data import Sample
from guardian_ai.training.errors import TrainingConfigurationError

TRAINING_SUBDIR = "training"
DATA_YAML = "data.yaml"


@dataclass(frozen=True, slots=True)
class LetterboxGeometry:
    """How a source image was placed onto a square canvas."""

    scale: float
    pad_x: float
    pad_y: float
    source_width: int
    source_height: int
    target_size: int


def letterbox_image(
    image_hwc: np.ndarray, target_size: int
) -> tuple[np.ndarray, LetterboxGeometry]:
    """Resize (aspect-preserving) + center-pad onto a ``target_size`` square."""
    height, width = image_hwc.shape[:2]
    scale = min(target_size / width, target_size / height)
    new_width, new_height = round(width * scale), round(height * scale)
    resized = np.asarray(
        Image.fromarray(image_hwc).resize((new_width, new_height), Image.Resampling.BILINEAR)
    )
    pad_x = (target_size - new_width) / 2.0
    pad_y = (target_size - new_height) / 2.0
    canvas = np.zeros((target_size, target_size, 3), dtype=image_hwc.dtype)
    left, top = int(round(pad_x)), int(round(pad_y))
    canvas[top : top + new_height, left : left + new_width] = resized
    return canvas, LetterboxGeometry(scale, pad_x, pad_y, width, height, target_size)


def letterbox_boxes(boxes_xywh_norm: np.ndarray, geometry: LetterboxGeometry) -> np.ndarray:
    """Transform normalized (cx, cy, w, h) boxes through the same letterbox."""
    if boxes_xywh_norm.size == 0:
        return boxes_xywh_norm.reshape(0, 4).astype(np.float32)
    absolute = boxes_xywh_norm.copy()
    absolute[:, 0] *= geometry.source_width
    absolute[:, 2] *= geometry.source_width
    absolute[:, 1] *= geometry.source_height
    absolute[:, 3] *= geometry.source_height
    absolute *= geometry.scale
    absolute[:, 0] += geometry.pad_x
    absolute[:, 1] += geometry.pad_y
    return (absolute / geometry.target_size).astype(np.float32)


class VideoRegistryDataModule:
    """Train/val/test splits from a Sprint-18 published video dataset."""

    def __init__(self, config: DatasetConfig, input_size: int, workers: int = 0) -> None:
        registry = VideoDatasetRegistry(config.registry_root)
        self._version_dir = registry.get(config.name, config.version)
        self._config = config
        self._input_size = input_size
        self._workers = max(1, workers)

        training_dir = self._version_dir / TRAINING_SUBDIR
        data_yaml_path = training_dir / DATA_YAML
        if not data_yaml_path.is_file():
            raise TrainingConfigurationError(
                f"dataset '{config.name}' has no {TRAINING_SUBDIR}/{DATA_YAML} — "
                "publish through guardian_ai.dataset first (Sprint 18)"
            )
        data_yaml = yaml.safe_load(data_yaml_path.read_text(encoding="utf-8"))
        self._class_names = list(data_yaml["names"])
        self._training_dir = training_dir
        self._dataset_manifest = json.loads(
            (self._version_dir / "dataset.json").read_text(encoding="utf-8")
        )

    # ------------------------------------------------------------- facts

    @property
    def dataset_name(self) -> str:
        return self._config.name

    @property
    def dataset_version(self) -> str:
        return self._version_dir.name

    @property
    def taxonomy_name(self) -> str:
        return str(self._dataset_manifest["taxonomy"]["name"])

    @property
    def taxonomy_version(self) -> str:
        return str(self._dataset_manifest["taxonomy"]["version"])

    @property
    def license(self) -> str:
        return str(self._dataset_manifest.get("license", "Proprietary-GuardianAI"))

    @property
    def class_names(self) -> list[str]:
        return list(self._class_names)

    def class_index(self, label: str) -> int:
        try:
            return self._class_names.index(label)
        except ValueError as exc:
            raise TrainingConfigurationError(
                f"label '{label}' is not in {self.dataset_name}'s class list {self._class_names}"
            ) from exc

    # ------------------------------------------------------------ loading

    def split(self, name: str) -> list[Path]:
        images_dir = self._training_dir / "images" / name
        if not images_dir.is_dir():
            raise TrainingConfigurationError(
                f"dataset '{self.dataset_name}' has no training/images/{name}"
            )
        paths = sorted(images_dir.glob("*.png"))
        if self._config.max_samples is not None:
            paths = paths[: self._config.max_samples]
        return paths

    def load_one(self, image_path: Path, split_name: str) -> Sample:
        """One image, off the hot batching path — for one-off inspection
        (qualitative export, debugging), never for a training/eval loop."""
        labels_dir = self._training_dir / "labels" / split_name
        return self._load_one((image_path, False), labels_dir)

    def load_canvas(self, image_path: Path) -> np.ndarray:
        """The letterboxed uint8 HWC canvas — for drawing, not for the model
        (which wants ``load_one``'s normalized float32 CHW tensor)."""
        with Image.open(image_path) as handle:
            source = np.asarray(handle.convert("RGB"))
        canvas, _ = letterbox_image(source, self._input_size)
        return canvas

    def batches(
        self,
        split_name: str,
        batch_size: int,
        shuffle: bool = False,
        augment: bool = False,
        flip_probability: float = 0.0,
        seed: int = 0,
    ) -> LazyBatches:
        """A sized, iterable batch sequence; images are decoded on demand."""
        rng = random.Random(seed)  # noqa: S311 - reproducible shuffling, not crypto
        image_paths = self.split(split_name)
        # flip decisions (and shuffle order) are drawn sequentially in this
        # thread, BEFORE any parallel I/O, so multi-threaded loading stays
        # bit-reproducible regardless of thread scheduling.
        flips = [
            bool(augment and flip_probability > 0 and rng.random() < flip_probability)
            for _ in image_paths
        ]
        if shuffle:
            order = list(range(len(image_paths)))
            rng.shuffle(order)
            image_paths = [image_paths[i] for i in order]
            flips = [flips[i] for i in order]
        labels_dir = self._training_dir / "labels" / split_name
        return LazyBatches(self, image_paths, flips, labels_dir, batch_size)

    # ------------------------------------------------------------ internals

    def _load_one(self, task: tuple[Path, bool], labels_dir: Path) -> Sample:
        image_path, flip = task
        boxes, labels = self._read_labels(labels_dir / f"{image_path.stem}.txt")
        with Image.open(image_path) as handle:
            source = np.asarray(handle.convert("RGB"))
        canvas, geometry = letterbox_image(source, self._input_size)
        boxes = letterbox_boxes(boxes, geometry)
        image = np.transpose(canvas.astype(np.float32) / 255.0, (2, 0, 1))  # HWC -> CHW
        if flip:
            image = image[:, :, ::-1].copy()
            if boxes.size:
                boxes = boxes.copy()
                boxes[:, 0] = 1.0 - boxes[:, 0]
        return Sample(
            image=image,
            boxes=boxes,
            labels=labels,
            path=str(image_path.relative_to(self._training_dir)),
        )

    def _read_labels(self, path: Path) -> tuple[np.ndarray, np.ndarray]:
        if not path.is_file():
            raise TrainingConfigurationError(f"no label file for image: {path}")
        boxes: list[list[float]] = []
        labels: list[int] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 5:
                raise TrainingConfigurationError(
                    f"{path}:{line_number}: expected 'class cx cy w h', got '{line}'"
                )
            class_index, cx, cy, w, h = parts
            labels.append(int(class_index))
            boxes.append([float(cx), float(cy), float(w), float(h)])
        if not boxes:
            raise TrainingConfigurationError(f"{path}: no boxes — an empty label is invalid")
        return np.array(boxes, dtype=np.float32), np.array(labels, dtype=np.int64)


class LazyBatches:
    """A ``len()``-able, once-iterable batch sequence that decodes lazily.

    Only the batch currently being produced is materialized as pixels;
    everything else stays a list of paths + flip flags. Safe for one full
    pass per ``iter()`` call, matching how the engine consumes it (one
    ``for`` loop per epoch, plus an upfront ``len()``/truthiness check).
    """

    def __init__(
        self,
        module: VideoRegistryDataModule,
        image_paths: list[Path],
        flips: list[bool],
        labels_dir: Path,
        batch_size: int,
    ) -> None:
        self._module = module
        self._image_paths = image_paths
        self._flips = flips
        self._labels_dir = labels_dir
        self._batch_size = batch_size

    def __len__(self) -> int:
        if not self._image_paths:
            return 0
        return -(-len(self._image_paths) // self._batch_size)  # ceil division

    def __iter__(
        self,
    ) -> Iterator[tuple[np.ndarray, list[tuple[np.ndarray, np.ndarray]], list[str]]]:
        for start in range(0, len(self._image_paths), self._batch_size):
            tasks = list(
                zip(
                    self._image_paths[start : start + self._batch_size],
                    self._flips[start : start + self._batch_size],
                    strict=True,
                )
            )
            if self._module._workers > 1 and len(tasks) > 1:  # noqa: SLF001 - same module
                with ThreadPoolExecutor(max_workers=self._module._workers) as pool:  # noqa: SLF001
                    samples = list(
                        pool.map(self._module._load_one, tasks, [self._labels_dir] * len(tasks))  # noqa: SLF001
                    )
            else:
                samples = [self._module._load_one(task, self._labels_dir) for task in tasks]  # noqa: SLF001
            yield (
                np.stack([sample.image for sample in samples]),
                [(sample.boxes, sample.labels) for sample in samples],
                [sample.path for sample in samples],
            )
