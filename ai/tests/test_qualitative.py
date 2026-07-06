"""Qualitative export: real predictions drawn over the real letterboxed frame."""

from __future__ import annotations

from pathlib import Path

import pytest
from model_v1_fixtures import publish_tiny_video_dataset, video_dataset_config

from guardian_ai.training.families import get_family
from guardian_ai.training.qualitative import export_qualitative_samples
from guardian_ai.training.video_data import VideoRegistryDataModule


@pytest.fixture()
def data_module(tmp_path: Path) -> VideoRegistryDataModule:
    publish_tiny_video_dataset(tmp_path, clip_count=3)
    return VideoRegistryDataModule(video_dataset_config(tmp_path), input_size=64)


@pytest.fixture()
def built_model(data_module: VideoRegistryDataModule):
    family = get_family("yolox-tiny")
    model = family.build(num_classes=len(data_module.class_names), input_size=64)
    return model, family


def test_exports_png_per_requested_sample(
    data_module: VideoRegistryDataModule, built_model, tmp_path: Path
) -> None:
    model, family = built_model
    destination = tmp_path / "qual"
    written = export_qualitative_samples(
        model, family, data_module, "train", destination, count=2, seed=0
    )
    assert len(written) == min(2, len(data_module.split("train")))
    for path in written:
        assert path.is_file()
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_count_larger_than_split_is_capped(
    data_module: VideoRegistryDataModule, built_model, tmp_path: Path
) -> None:
    model, family = built_model
    written = export_qualitative_samples(
        model, family, data_module, "train", tmp_path / "qual", count=10_000, seed=0
    )
    assert len(written) == len(data_module.split("train"))


def test_sampling_is_reproducible_given_a_seed(
    data_module: VideoRegistryDataModule, built_model, tmp_path: Path
) -> None:
    model, family = built_model
    first = export_qualitative_samples(
        model, family, data_module, "train", tmp_path / "a", count=1, seed=42
    )
    second = export_qualitative_samples(
        model, family, data_module, "train", tmp_path / "b", count=1, seed=42
    )
    assert first[0].name == second[0].name


def test_empty_split_is_rejected(
    data_module: VideoRegistryDataModule, built_model, tmp_path: Path
) -> None:
    model, family = built_model
    empty_split = "test" if not data_module.split("test") else None
    if empty_split is None:
        pytest.skip("fixture's test split is non-empty in this run")
    with pytest.raises(ValueError, match="no images"):
        export_qualitative_samples(model, family, data_module, empty_split, tmp_path / "qual")


def test_model_returns_to_train_mode_after_export(
    data_module: VideoRegistryDataModule, built_model, tmp_path: Path
) -> None:
    model, family = built_model
    model.train()
    export_qualitative_samples(model, family, data_module, "train", tmp_path / "qual", count=1)
    assert model.training is True
