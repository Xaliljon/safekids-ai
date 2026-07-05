"""Model-independent image preprocessing."""

from datetime import datetime, timezone

import numpy as np
import pytest

from guardian_edge.domain.errors import DetectorError
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.vision.preprocessing import ImageMeta, ImagePreprocessor


def image_frame(width: int = 64, height: int = 48) -> Frame:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[0, 0] = (255, 0, 128)  # known pixel: B=255, G=0, R=128
    return Frame(
        camera_id="cam-1",
        sequence=1,
        captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
        width=width,
        height=height,
        data=image,
    )


def test_converts_to_normalized_nchw_float32() -> None:
    preprocessed = ImagePreprocessor(input_name="image").preprocess(image_frame())
    tensor = preprocessed.inputs["image"]
    assert tensor.shape == (1, 3, 48, 64)
    assert tensor.dtype == np.float32
    assert tensor.min() >= 0.0 and tensor.max() <= 1.0
    assert tensor[0, 0, 0, 0] == pytest.approx(1.0)  # B=255 -> 1.0
    assert tensor[0, 2, 0, 0] == pytest.approx(128 / 255)  # R channel


def test_fixed_target_size_resizes() -> None:
    preprocessed = ImagePreprocessor(input_name="image", target_size=(32, 32)).preprocess(
        image_frame(width=64, height=48)
    )
    tensor = preprocessed.inputs["image"]
    assert tensor.shape == (1, 3, 32, 32)
    meta = preprocessed.meta
    assert isinstance(meta, ImageMeta)
    assert (meta.original_width, meta.original_height) == (64, 48)
    assert (meta.input_width, meta.input_height) == (32, 32)


def test_dynamic_size_keeps_frame_dimensions() -> None:
    preprocessed = ImagePreprocessor(input_name="image").preprocess(image_frame(100, 80))
    meta = preprocessed.meta
    assert isinstance(meta, ImageMeta)
    assert (meta.input_width, meta.input_height) == (100, 80)


def test_swap_to_rgb_flips_channel_order() -> None:
    bgr = ImagePreprocessor(input_name="image").preprocess(image_frame()).inputs["image"]
    rgb = (
        ImagePreprocessor(input_name="image", swap_to_rgb=True)
        .preprocess(image_frame())
        .inputs["image"]
    )
    assert rgb[0, 0, 0, 0] == pytest.approx(float(bgr[0, 2, 0, 0]))  # R first now
    assert rgb[0, 2, 0, 0] == pytest.approx(float(bgr[0, 0, 0, 0]))


def test_tensor_is_contiguous_for_the_backend() -> None:
    tensor = (
        ImagePreprocessor(input_name="image", swap_to_rgb=True)
        .preprocess(image_frame())
        .inputs["image"]
    )
    assert tensor.flags["C_CONTIGUOUS"]


def test_non_image_buffer_fails_loudly() -> None:
    frame = Frame(
        camera_id="cam-1",
        sequence=1,
        captured_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
        width=64,
        height=48,
        data=object(),
    )
    with pytest.raises(DetectorError, match="not an HxWx3 image"):
        ImagePreprocessor(input_name="image").preprocess(frame)
