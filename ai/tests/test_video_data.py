"""Video dataset access: letterbox math, lazy batching, memory-bounded."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from model_v1_fixtures import publish_tiny_video_dataset, video_dataset_config

from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.video_data import (
    LazyBatches,
    LetterboxGeometry,
    VideoRegistryDataModule,
    letterbox_boxes,
    letterbox_image,
)


class TestLetterbox:
    def test_wider_than_target_pads_vertically(self) -> None:
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        image[:] = 200
        canvas, geometry = letterbox_image(image, 640)
        assert canvas.shape == (640, 640, 3)
        assert geometry.scale == pytest.approx(1.0)
        assert geometry.pad_y == pytest.approx(80.0)
        assert geometry.pad_x == pytest.approx(0.0)
        # padding rows are zero (untouched), content rows are the source value
        assert canvas[0, 0, 0] == 0
        assert canvas[80, 0, 0] == 200

    def test_taller_than_target_pads_horizontally(self) -> None:
        image = np.zeros((640, 480, 3), dtype=np.uint8)
        canvas, geometry = letterbox_image(image, 640)
        assert geometry.pad_x == pytest.approx(80.0)
        assert geometry.pad_y == pytest.approx(0.0)

    def test_box_transform_matches_hand_computation(self) -> None:
        # a box at the exact center of a 640x480 source, half-width/height
        boxes = np.array([[0.5, 0.5, 0.5, 0.5]], dtype=np.float32)
        geometry = LetterboxGeometry(
            scale=1.0,
            pad_x=0.0,
            pad_y=80.0,
            source_width=640,
            source_height=480,
            target_size=640,
        )
        transformed = letterbox_boxes(boxes, geometry)
        # cx: 0.5*640=320, *1.0=320, +0 pad, /640 = 0.5 (unchanged)
        # cy: 0.5*480=240, *1.0=240, +80 pad = 320, /640 = 0.5 (unchanged, since centered)
        assert transformed[0, 0] == pytest.approx(0.5)
        assert transformed[0, 1] == pytest.approx(0.5)
        # w: 0.5*640=320,*1=320,/640=0.5 (unchanged); h: 0.5*480=240,/640=0.375 (shrinks)
        assert transformed[0, 2] == pytest.approx(0.5)
        assert transformed[0, 3] == pytest.approx(0.375)

    def test_box_transform_off_center(self) -> None:
        # a box touching the top edge of the 480-tall source
        boxes = np.array([[0.5, 0.0, 0.2, 0.1]], dtype=np.float32)
        geometry = LetterboxGeometry(1.0, 0.0, 80.0, 640, 480, 640)
        transformed = letterbox_boxes(boxes, geometry)
        # y absolute = 0*480=0, +80 pad = 80, /640 = 0.125
        assert transformed[0, 1] == pytest.approx(0.125)

    def test_empty_boxes_pass_through(self) -> None:
        geometry = LetterboxGeometry(1.0, 0.0, 80.0, 640, 480, 640)
        empty = np.zeros((0, 4), dtype=np.float32)
        result = letterbox_boxes(empty, geometry)
        assert result.shape == (0, 4)


class TestVideoRegistryDataModule:
    @pytest.fixture()
    def dataset_root(self, tmp_path: Path) -> Path:
        publish_tiny_video_dataset(tmp_path, clip_count=3)
        return tmp_path

    def test_resolves_through_registry_and_reads_data_yaml(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        assert module.dataset_name == "tiny-video-dataset"
        assert module.dataset_version == "1.0.0"
        assert module.taxonomy_name == "guardian-video-safety"
        assert module.class_names == ["adult", "child", "person", "unknown"]
        assert module.class_index("person") == 2

    def test_split_and_batches_shapes(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        image_paths = module.split("train")
        assert len(image_paths) >= 1
        batches = module.batches("train", batch_size=1)
        assert len(batches) == len(image_paths)
        total = 0
        for images, targets, paths in batches:
            assert images.dtype == np.float32
            assert images.shape[1:] == (3, 64, 64)
            assert len(targets) == len(paths)
            for boxes, labels in targets:
                assert boxes.shape[1] == 4
                assert labels.dtype == np.int64
            total += images.shape[0]
        assert total == len(image_paths)

    def test_batches_is_lazy_and_sized(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        batches = module.batches("train", batch_size=1)
        assert isinstance(batches, LazyBatches)
        assert len(batches) > 0
        assert bool(batches) is True
        # a fresh __iter__ each time -> the same object can be consumed twice
        first_pass = sum(images.shape[0] for images, _, _ in batches)
        second_pass = sum(images.shape[0] for images, _, _ in batches)
        assert first_pass == second_pass

    def test_empty_split_is_falsy_and_zero_length(self, tmp_path: Path) -> None:
        publish_tiny_video_dataset(tmp_path, clip_count=1)
        module = VideoRegistryDataModule(video_dataset_config(tmp_path), input_size=64)
        # test split may legitimately be empty for a 1-clip fixture dataset
        batches = module.batches("test", batch_size=4)
        if len(module.split("test")) == 0:
            assert len(batches) == 0
            assert not batches
            assert list(batches) == []

    def test_max_samples_caps_the_split_deterministically(self, dataset_root: Path) -> None:
        uncapped = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        all_paths = uncapped.split("train")
        if len(all_paths) < 2:
            pytest.skip("fixture didn't produce enough train images to test capping")
        capped = VideoRegistryDataModule(
            video_dataset_config(dataset_root, max_samples=1), input_size=64
        )
        assert capped.split("train") == all_paths[:1]

    def test_workers_greater_than_one_yields_identical_batches(self, dataset_root: Path) -> None:
        single = VideoRegistryDataModule(
            video_dataset_config(dataset_root), input_size=64, workers=1
        )
        parallel = VideoRegistryDataModule(
            video_dataset_config(dataset_root), input_size=64, workers=4
        )
        single_images = np.concatenate(
            [images for images, _, _ in single.batches("train", batch_size=2)]
        )
        parallel_images = np.concatenate(
            [images for images, _, _ in parallel.batches("train", batch_size=2)]
        )
        np.testing.assert_allclose(single_images, parallel_images)

    def test_flip_and_shuffle_are_reproducible_given_a_seed(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        first = list(
            module.batches(
                "train", batch_size=1, shuffle=True, augment=True, flip_probability=0.5, seed=7
            )
        )
        second = list(
            module.batches(
                "train", batch_size=1, shuffle=True, augment=True, flip_probability=0.5, seed=7
            )
        )
        for (images_a, _, paths_a), (images_b, _, paths_b) in zip(first, second, strict=True):
            assert paths_a == paths_b
            np.testing.assert_array_equal(images_a, images_b)

    def test_load_one_and_load_canvas(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        image_path = module.split("train")[0]
        sample = module.load_one(image_path, "train")
        assert sample.image.shape == (3, 64, 64)
        canvas = module.load_canvas(image_path)
        assert canvas.shape == (64, 64, 3)
        assert canvas.dtype == np.uint8

    def test_malformed_label_line_is_rejected(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        image_path = module.split("train")[0]
        label_path = (
            dataset_root
            / "registry"
            / "tiny-video-dataset"
            / "1.0.0"
            / "training"
            / "labels"
            / "train"
            / f"{image_path.stem}.txt"
        )
        original = label_path.read_text()
        try:
            label_path.write_text("not enough fields\n")
            with pytest.raises(TrainingConfigurationError, match="expected 'class cx cy w h'"):
                module.load_one(image_path, "train")
        finally:
            label_path.write_text(original)

    def test_missing_split_directory_is_refused(self, dataset_root: Path) -> None:
        module = VideoRegistryDataModule(video_dataset_config(dataset_root), input_size=64)
        with pytest.raises(TrainingConfigurationError, match="no training/images"):
            module.split("nonexistent-split")
