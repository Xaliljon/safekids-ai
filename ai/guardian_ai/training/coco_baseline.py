"""COCO-pretrained YOLOX-Tiny baseline — for the mandated comparison
against Guardian Model v1 (Sprint 19 requirement #10: "COCO pretrained
vs Guardian Model v1... Recommendation: PROMOTE or KEEP COCO").

The official artifact is Apache-2.0 (Megvii, ADR-0003) and already has a
reviewed, pinned-hash installer at
``edge/guardian_edge/tools/install_yolox.py``. This module invokes that
installer as a **subprocess** (a sibling app's CLI, not an import) —
ADR-0001 forbids ``ai/`` importing ``edge/`` in-process, and a
same-repo subprocess call to an existing, hash-verified tool is not the
same thing as this module inventing and fetching its own URL.

Decoding is reimplemented independently here, matching the *documented*
contract of that exact artifact (see the install script and
``edge/guardian_edge/infrastructure/vision/yolox.py``'s docstring, read
but never imported): 416x416 canvas, BGR, 0-255 (no mean/std
normalization), letterboxed with 114 padding anchored at the top-left
(NOT centered), output ``[1, N, 5+80]`` with objectness/class already
sigmoided. Only COCO class 0 ("person") is kept, mapped onto whichever
class index the comparison dataset calls "person" — the only COCO class
SafeKids consumes (ADR-0003 §3).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.families import Prediction
from guardian_ai.training.video_data import VideoRegistryDataModule
from guardian_ai.training.yolox_tiny import _nms

logger = logging.getLogger(__name__)

MODEL_NAME = "yolox-tiny"
MODEL_VERSION = "0.1.1-rc0"
COCO_INPUT_SIZE = 416
COCO_PERSON_CLASS_INDEX = 0
_PAD_VALUE = 114
_SCORE_FLOOR = 0.05
_NMS_IOU_THRESHOLD = 0.45


def fetch_official_checkpoint(zoo_root: Path, edge_project_root: Path) -> Path:
    """Runs the existing edge/ installer (hash-pinned, ADR-0003) as a
    subprocess — the model zoo layout it produces, unmodified."""
    destination = zoo_root / MODEL_NAME / MODEL_VERSION / "model.onnx"
    if destination.is_file():
        return destination
    if not edge_project_root.is_dir():
        raise TrainingConfigurationError(
            f"edge project not found at {edge_project_root} — cannot fetch the "
            "COCO-pretrained baseline via its installer"
        )
    command = [
        "uv",
        "run",
        "--project",
        str(edge_project_root),
        "python",
        "-m",
        "guardian_edge.tools.install_yolox",
        "--dest",
        str(zoo_root),
    ]
    logger.info("fetching COCO-pretrained baseline: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)  # noqa: S603
    if result.returncode != 0 or not destination.is_file():
        raise TrainingConfigurationError(
            f"COCO baseline install failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:500]}"
        )
    return destination


def preprocess(
    image_rgb_hwc: np.ndarray, input_size: int = COCO_INPUT_SIZE
) -> tuple[np.ndarray, float]:
    """Official YOLOX preprocessing: BGR, 0-255, top-left 114-padded letterbox."""
    height, width = image_rgb_hwc.shape[:2]
    ratio = min(input_size / height, input_size / width)
    new_size = (round(width * ratio), round(height * ratio))
    resized = np.asarray(Image.fromarray(image_rgb_hwc).resize(new_size, Image.Resampling.BILINEAR))
    canvas = np.full((input_size, input_size, 3), _PAD_VALUE, dtype=np.uint8)
    canvas[: resized.shape[0], : resized.shape[1]] = resized
    bgr = canvas[:, :, ::-1].astype(np.float32)  # RGB -> BGR, no normalization
    tensor = np.ascontiguousarray(bgr.transpose(2, 0, 1)[np.newaxis, ...])
    return tensor, ratio


def _grid_and_stride(
    input_size: int, strides: tuple[int, ...] = (8, 16, 32)
) -> tuple[np.ndarray, np.ndarray]:
    grids, strides_out = [], []
    for stride in strides:
        size = input_size // stride
        ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
        grids.append(np.stack([xs.ravel(), ys.ravel()], axis=1))
        strides_out.append(np.full((size * size, 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides_out).astype(np.float32)


def decode(
    raw_output: np.ndarray,
    ratio: float,
    original_width: int,
    original_height: int,
    input_size: int = COCO_INPUT_SIZE,
    person_class_index: int = COCO_PERSON_CLASS_INDEX,
    target_label_index: int = 0,
) -> Prediction:
    """Grid-decode one image's raw head output; keeps COCO 'person' only."""
    predictions = raw_output[0]
    grid, stride = _grid_and_stride(input_size)
    if predictions.shape[0] != grid.shape[0]:
        raise TrainingConfigurationError(
            f"COCO baseline output has {predictions.shape[0]} cells, expected "
            f"{grid.shape[0]} for a {input_size}x{input_size} input"
        )
    centers = (predictions[:, 0:2] + grid) * stride
    sizes = np.exp(predictions[:, 2:4]) * stride
    class_scores = predictions[:, 5:]
    person_scores = predictions[:, 4] * class_scores[:, person_class_index]
    keep = person_scores >= _SCORE_FLOOR
    if not keep.any():
        return Prediction(
            boxes=np.zeros((0, 4), dtype=np.float32),
            scores=np.zeros((0,), dtype=np.float32),
            labels=np.zeros((0,), dtype=np.int64),
        )

    # canvas pixels -> original pixels (undo the letterbox) -> normalized [0,1]
    x1 = (centers[keep, 0] - sizes[keep, 0] / 2) / ratio
    y1 = (centers[keep, 1] - sizes[keep, 1] / 2) / ratio
    x2 = (centers[keep, 0] + sizes[keep, 0] / 2) / ratio
    y2 = (centers[keep, 1] + sizes[keep, 1] / 2) / ratio
    boxes_cxcywh = np.stack(
        [
            np.clip((x1 + x2) / 2 / original_width, 0, 1),
            np.clip((y1 + y2) / 2 / original_height, 0, 1),
            np.clip((x2 - x1) / original_width, 0, 1),
            np.clip((y2 - y1) / original_height, 0, 1),
        ],
        axis=1,
    ).astype(np.float32)
    scores = np.minimum(person_scores[keep], 1.0).astype(np.float32)

    keep_indices = _nms(boxes_cxcywh, scores, _NMS_IOU_THRESHOLD)
    return Prediction(
        boxes=boxes_cxcywh[keep_indices],
        scores=scores[keep_indices],
        labels=np.full(len(keep_indices), target_label_index, dtype=np.int64),
    )


def evaluate_coco_baseline(
    onnx_path: Path,
    data_module: VideoRegistryDataModule,
    split_name: str,
    score_threshold: float = 0.25,
) -> dict[str, Any]:
    """Run the official COCO model over one split, evaluated with OUR harness."""
    import onnxruntime

    from guardian_ai.evaluation.detection import evaluate_detections

    person_index = data_module.class_index("person")
    session = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    predictions: list[Prediction] = []
    ground_truths: list[tuple[np.ndarray, np.ndarray]] = []
    for image_path in data_module.split(split_name):
        sample = data_module.load_one(image_path, split_name)
        canvas = data_module.load_canvas(image_path)
        tensor, ratio = preprocess(canvas)
        (raw_output,) = session.run([output_name], {input_name: tensor})
        prediction = decode(
            raw_output,
            ratio,
            canvas.shape[1],
            canvas.shape[0],
            target_label_index=person_index,
        )
        predictions.append(prediction)
        ground_truths.append((sample.boxes, sample.labels))

    return evaluate_detections(
        predictions, ground_truths, data_module.class_names, score_threshold=score_threshold
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper
    import argparse
    import json

    from guardian_ai.training.config import DatasetConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", required=True, type=Path)
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-version", default=None)
    parser.add_argument("--split", default="test")
    parser.add_argument("--zoo-root", required=True, type=Path)
    parser.add_argument("--edge-project-root", required=True, type=Path)
    arguments = parser.parse_args(argv)

    onnx_path = fetch_official_checkpoint(arguments.zoo_root, arguments.edge_project_root)
    data_module = VideoRegistryDataModule(
        DatasetConfig(
            registry_root=arguments.registry_root,
            name=arguments.dataset_name,
            version=arguments.dataset_version,
            format="video",
        ),
        input_size=640,
    )
    result = evaluate_coco_baseline(onnx_path, data_module, arguments.split)
    print(json.dumps(result["overall"], indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
