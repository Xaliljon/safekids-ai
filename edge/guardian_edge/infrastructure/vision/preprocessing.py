"""Model-independent image preprocessing.

Converts a captured BGR uint8 frame buffer into a float32 NCHW tensor in
[0, 1] — the common denominator of CNN detection models. Fixed input sizes
resize with OpenCV; dynamic models receive the frame at native size.

Boxes are normalized end-to-end (ADR-0006), so a plain resize needs no
coordinate correction at decode time. Aspect-preserving letterboxing is a
model-family concern and belongs in that family's own Preprocessor.
"""

from __future__ import annotations

import cv2
import numpy as np

from guardian_edge.application.vision.ports import PreprocessedFrame
from guardian_edge.domain.errors import DetectorError
from guardian_edge.domain.frame import Frame

_CHANNELS = 3
_UINT8_MAX = 255.0


class ImageMeta:
    """Geometry context handed from preprocessing to decoding."""

    __slots__ = ("input_height", "input_width", "original_height", "original_width")

    def __init__(
        self,
        original_width: int,
        original_height: int,
        input_width: int,
        input_height: int,
    ) -> None:
        self.original_width = original_width
        self.original_height = original_height
        self.input_width = input_width
        self.input_height = input_height


class ImagePreprocessor:
    """BGR uint8 HxWx3 buffer -> float32 [1, 3, H, W] tensor in [0, 1]."""

    def __init__(
        self,
        input_name: str,
        target_size: tuple[int, int] | None = None,
        swap_to_rgb: bool = False,
    ) -> None:
        """``target_size`` is (width, height); None keeps the frame's size
        (for models with dynamic spatial dimensions). ``swap_to_rgb`` for
        models trained on RGB input."""
        self._input_name = input_name
        self._target_size = target_size
        self._swap_to_rgb = swap_to_rgb

    def preprocess(self, frame: Frame) -> PreprocessedFrame:
        image = frame.data
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) != _CHANNELS or shape[2] != _CHANNELS:
            raise DetectorError(
                f"camera {frame.camera_id}: frame buffer is not an HxWx3 image "
                f"(got {type(image).__name__} with shape {shape})"
            )
        if self._target_size is not None:
            image = cv2.resize(image, self._target_size, interpolation=cv2.INTER_LINEAR)
        if self._swap_to_rgb:
            image = image[..., ::-1]
        tensor = np.ascontiguousarray(
            image.astype(np.float32).transpose(2, 0, 1)[np.newaxis, ...] / _UINT8_MAX
        )
        height, width = image.shape[:2]
        return PreprocessedFrame(
            inputs={self._input_name: tensor},
            meta=ImageMeta(
                original_width=frame.width,
                original_height=frame.height,
                input_width=int(width),
                input_height=int(height),
            ),
        )
