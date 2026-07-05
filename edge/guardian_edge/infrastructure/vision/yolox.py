"""YOLOX model family adapters (ADR-0003).

The first real detector, integrated exclusively through the existing seams:
a ``Preprocessor`` + ``OutputDecoder`` pair around the generic
``EngineDetector`` (ADR-0006), loading through the model registry and the
ONNX Runtime engine (ADR-0008/0009). Nothing above the Detector port knows
YOLOX exists.

YOLOX I/O contract (official ONNX exports, decode_in_inference=False):

- input: BGR image, float32 0..255 (no mean/std normalization), letterboxed
  into a fixed canvas padded with 114.
- output: ``[1, N, 5 + num_classes]`` raw head predictions; xy need grid
  offsets, wh are log-space, objectness/class scores are already sigmoided.
  N is the grid-cell count over strides 8/16/32 (3549 for 416x416).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from guardian_edge.application.inference.loader import ModelLoader
from guardian_edge.application.inference.ports import InferenceEngineFactory, ModelRegistry
from guardian_edge.application.vision.detector import DetectorConfig, EngineDetector
from guardian_edge.application.vision.ports import PreprocessedFrame, RawDetection
from guardian_edge.domain.detection import BoundingBox
from guardian_edge.domain.errors import DetectorError, VisionConfigurationError
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.inference.onnx_engine import OnnxRuntimeEngineFactory

YOLOX_MODEL_NAME = "yolox-tiny"
_PAD_VALUE = 114
_STRIDES = (8, 16, 32)
_BOX_FIELDS = 5  # cx, cy, w, h, objectness

COCO_LABELS: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class YoloxMeta:
    """Geometry handed from the YOLOX preprocessor to its decoder."""

    ratio: float
    original_width: int
    original_height: int
    input_width: int
    input_height: int


class YoloxPreprocessor:
    """Official YOLOX preprocessing: aspect-preserving letterbox, BGR 0-255."""

    def __init__(self, input_name: str, input_size: tuple[int, int]) -> None:
        """``input_size`` is (height, width) of the model canvas."""
        self._input_name = input_name
        self._height, self._width = input_size

    def preprocess(self, frame: Frame) -> PreprocessedFrame:
        image = frame.data
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) != 3 or shape[2] != 3:
            raise DetectorError(
                f"camera {frame.camera_id}: frame buffer is not an HxWx3 image "
                f"(got {type(image).__name__} with shape {shape})"
            )
        height, width = int(shape[0]), int(shape[1])
        ratio = min(self._height / height, self._width / width)
        resized = cv2.resize(
            image,
            (round(width * ratio), round(height * ratio)),
            interpolation=cv2.INTER_LINEAR,
        )
        canvas = np.full((self._height, self._width, 3), _PAD_VALUE, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32))
        return PreprocessedFrame(
            inputs={self._input_name: tensor},
            meta=YoloxMeta(
                ratio=ratio,
                original_width=frame.width,
                original_height=frame.height,
                input_width=self._width,
                input_height=self._height,
            ),
        )


class YoloxDecoder:
    """Grid-decodes raw YOLOX head output into normalized RawDetections.

    ``score_floor`` cheaply discards the overwhelmingly-background grid
    cells before object construction; the real confidence gate remains
    DetectorConfig's threshold in EngineDetector.
    """

    def __init__(self, output_name: str = "output", score_floor: float = 0.05) -> None:
        self._output_name = output_name
        self._score_floor = score_floor
        self._grid_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    def decode(self, outputs: Mapping[str, Any], meta: Any) -> list[RawDetection]:
        if not isinstance(meta, YoloxMeta):
            raise DetectorError("YoloxDecoder requires YoloxMeta from YoloxPreprocessor")
        raw = outputs.get(self._output_name)
        if raw is None:
            raise DetectorError(
                f"model output '{self._output_name}' missing (got {sorted(outputs)})"
            )
        predictions = raw[0]
        grid, stride = self._grids_for(meta.input_height, meta.input_width)
        if predictions.shape[0] != grid.shape[0]:
            raise DetectorError(
                f"output has {predictions.shape[0]} cells, expected {grid.shape[0]} "
                f"for a {meta.input_width}x{meta.input_height} input"
            )
        centers = (predictions[:, 0:2] + grid) * stride
        sizes = np.exp(predictions[:, 2:4]) * stride
        class_scores = predictions[:, _BOX_FIELDS:]
        scores = predictions[:, 4] * class_scores.max(axis=1)
        labels = class_scores.argmax(axis=1)
        keep = scores >= self._score_floor

        detections: list[RawDetection] = []
        for center, size, score, label in zip(
            centers[keep], sizes[keep], scores[keep], labels[keep], strict=True
        ):
            box = self._to_normalized_box(center, size, meta)
            if box is not None:
                detections.append(
                    RawDetection(
                        label_index=int(label),
                        confidence=float(min(score, 1.0)),
                        box=box,
                    )
                )
        return detections

    def _to_normalized_box(
        self, center: np.ndarray, size: np.ndarray, meta: YoloxMeta
    ) -> BoundingBox | None:
        # canvas pixels -> original pixels (undo letterbox) -> normalized
        x1 = (float(center[0]) - float(size[0]) / 2.0) / meta.ratio / meta.original_width
        y1 = (float(center[1]) - float(size[1]) / 2.0) / meta.ratio / meta.original_height
        x2 = (float(center[0]) + float(size[0]) / 2.0) / meta.ratio / meta.original_width
        y2 = (float(center[1]) + float(size[1]) / 2.0) / meta.ratio / meta.original_height
        left = min(max(x1, 0.0), 1.0)
        top = min(max(y1, 0.0), 1.0)
        width = min(x2, 1.0) - left
        height = min(y2, 1.0) - top
        if width <= 0.0 or height <= 0.0:
            return None
        return BoundingBox(x=left, y=top, width=width, height=height)

    def _grids_for(self, height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
        key = (height, width)
        cached = self._grid_cache.get(key)
        if cached is not None:
            return cached
        grids = []
        strides = []
        for stride in _STRIDES:
            grid_h, grid_w = height // stride, width // stride
            ys, xs = np.meshgrid(np.arange(grid_h), np.arange(grid_w), indexing="ij")
            grids.append(np.stack((xs, ys), axis=2).reshape(-1, 2).astype(np.float32))
            strides.append(np.full((grid_h * grid_w, 1), stride, dtype=np.float32))
        result = (np.concatenate(grids), np.concatenate(strides))
        self._grid_cache[key] = result
        return result


def create_yolox_detector(
    registry: ModelRegistry,
    engine_factory: InferenceEngineFactory | None = None,
    model_name: str = YOLOX_MODEL_NAME,
    **config_overrides: Any,
) -> EngineDetector:
    """Load a YOLOX model from the registry and wrap it in an EngineDetector.

    Thresholds and labels come from the model's manifest metadata;
    keyword overrides win (per-deployment tuning without touching models).
    """
    loader = ModelLoader(
        registry=registry,
        engine_factory=engine_factory or OnnxRuntimeEngineFactory(),
    )
    engine = loader.load(model_name)
    manifest = engine.manifest
    input_spec = manifest.inputs[0]
    if len(input_spec.shape) != 4 or input_spec.shape[2] is None or input_spec.shape[3] is None:
        raise VisionConfigurationError(
            f"model {manifest.model.name}: YOLOX requires a fixed NCHW input shape, "
            f"got {input_spec.shape}"
        )
    return EngineDetector(
        engine=engine,
        preprocessor=YoloxPreprocessor(
            input_name=input_spec.name,
            input_size=(input_spec.shape[2], input_spec.shape[3]),
        ),
        decoder=YoloxDecoder(output_name=manifest.outputs[0].name),
        config=DetectorConfig.from_manifest(manifest, **config_overrides),
    )
