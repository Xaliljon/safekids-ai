"""Data module: the registry is the only door."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest
from training_fixtures import publish_tiny_dataset

from guardian_ai.datasets.errors import DatasetRegistryError
from guardian_ai.training.config import DatasetConfig
from guardian_ai.training.data import RegistryDataModule
from guardian_ai.training.errors import TrainingConfigurationError


@pytest.fixture(scope="module")
def registry_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("registry")
    publish_tiny_dataset(root)
    return root


def make_module(registry_root: Path, input_size: int = 64) -> RegistryDataModule:
    return RegistryDataModule(
        DatasetConfig(registry_root=registry_root, name="tiny-synthetic"), input_size
    )


def test_resolves_through_registry_only(registry_root: Path) -> None:
    module = make_module(registry_root)
    assert module.dataset_name == "tiny-synthetic"
    assert module.dataset_version == "1.0.0"
    assert module.taxonomy_name == "guardian-safety"
    assert module.class_names == ["adult", "child", "person"]


def test_unregistered_dataset_is_refused(registry_root: Path) -> None:
    with pytest.raises(DatasetRegistryError):
        RegistryDataModule(DatasetConfig(registry_root=registry_root, name="loose-folder"), 64)


def test_splits_and_sample_shapes(registry_root: Path) -> None:
    module = make_module(registry_root)
    assert len(module.split("train")) == 6
    assert len(module.split("val")) == 3
    samples = module.samples("train")
    assert len(samples) == 6
    sample = samples[0]
    assert sample.image.shape == (3, 64, 64)
    assert sample.image.dtype == np.float32
    assert float(sample.image.min()) >= 0.0 and float(sample.image.max()) <= 1.0
    assert sample.box.shape == (4,)
    assert 0 <= sample.label < 3


def test_batches_shapes(registry_root: Path) -> None:
    module = make_module(registry_root)
    batches = module.batches("train", batch_size=4)
    assert [images.shape[0] for images, _, _ in batches] == [4, 2]
    images, boxes, labels = batches[0]
    assert images.shape == (4, 3, 64, 64)
    assert boxes.shape == (4, 4)
    assert labels.dtype == np.int64


def test_horizontal_flip_flips_box_and_image(registry_root: Path) -> None:
    module = make_module(registry_root)
    plain = module.samples("train")
    flipped = module.samples("train", augment=True, flip_probability=1.0, rng=random.Random(0))
    for before, after in zip(plain, flipped, strict=True):
        assert after.box[0] == pytest.approx(1.0 - before.box[0], abs=1e-6)
        assert after.box[1] == pytest.approx(before.box[1])
        np.testing.assert_allclose(after.image, before.image[:, :, ::-1], atol=1e-6)


def test_unknown_label_is_refused(registry_root: Path) -> None:
    module = make_module(registry_root)
    with pytest.raises(TrainingConfigurationError, match="not in taxonomy"):
        module.class_index("robot")


def test_missing_media_fails_loudly(registry_root: Path, tmp_path: Path) -> None:
    import shutil

    broken_root = tmp_path / "broken-registry"
    shutil.copytree(registry_root, broken_root)
    shutil.rmtree(broken_root / "tiny-synthetic" / "1.0.0" / "media")
    module = RegistryDataModule(DatasetConfig(registry_root=broken_root, name="tiny-synthetic"), 64)
    with pytest.raises(TrainingConfigurationError, match="media unreadable"):
        module.samples("train")
