"""OfficialYoloxTrainer: the DetectorFamily wrapping upstream YOLOX.

Output tensor contract (matches every other Guardian family): one
concatenated ``(batch, total_anchors, 5 + num_classes)`` tensor —
``[cx, cy, w, h, objectness, class_scores...]``. YOLOX's own
``decode_in_inference`` flag stays at its default (True), so eval-mode
outputs are already grid-decoded to absolute pixel coordinates and
sigmoided — ``decode()`` here only normalizes and runs NMS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.training.detectors.yolox import checkpoints
from guardian_ai.training.detectors.yolox.targets import to_yolox_labels
from guardian_ai.training.detectors.yolox.variants import base_in_channels, get_variant, strides
from guardian_ai.training.detectors.yolox.wrapper import OfficialYoloxWrapper
from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.nms import nms

_SCORE_FLOOR = 0.05
_NMS_IOU_THRESHOLD = 0.45


class OfficialYoloxTrainer:
    """One DetectorFamily per model-size variant (nano/tiny/s/m/l) —
    see ``families.py`` for the ``yolox-<variant>`` registration."""

    license = "Apache-2.0"

    def __init__(self, variant: str) -> None:
        self._variant = get_variant(variant)
        self.name = f"yolox-{variant}"
        self._input_size = 640
        self._num_classes = 1
        self._wrapper: OfficialYoloxWrapper | None = None

    def build(
        self,
        num_classes: int,
        input_size: int,
        pretrained: bool = False,
        checkpoint: Path | None = None,
    ) -> Any:
        from torch import nn
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        self._num_classes = num_classes
        self._input_size = input_size
        in_channels = list(base_in_channels())
        backbone = YOLOPAFPN(
            self._variant.depth,
            self._variant.width,
            in_channels=in_channels,
            depthwise=self._variant.depthwise,
        )
        head = YOLOXHead(
            num_classes,
            self._variant.width,
            strides=list(strides()),
            in_channels=in_channels,
            depthwise=self._variant.depthwise,
        )
        model = YOLOX(backbone, head)

        def init_yolo(module: Any) -> None:
            if isinstance(module, nn.BatchNorm2d):
                module.eps = 1e-3
                module.momentum = 0.03

        model.apply(init_yolo)
        model.head.initialize_biases(1e-2)

        checkpoint_sha256: str | None = None
        if checkpoint is not None:
            checkpoints.load_into(model, checkpoint, num_classes)
            checkpoint_sha256 = checkpoints.sha256_of(checkpoint)
        elif pretrained:
            path = checkpoints.download_pretrained(self._variant)
            checkpoints.load_into(model, path, num_classes)
            checkpoint_sha256 = checkpoints.sha256_of(path)

        self._wrapper = OfficialYoloxWrapper(model)
        self._wrapper.checkpoint_sha256 = checkpoint_sha256
        return self._wrapper

    def loss(self, outputs: Any, targets: list[tuple[Any, Any]]) -> Any:
        if self._wrapper is None:
            raise TrainingConfigurationError(f"{self.name}: build() must run before loss()")
        padded = to_yolox_labels(targets, self._input_size)
        return self._wrapper.compute_loss(padded)

    def decode(self, outputs: Any) -> list[Any]:
        from guardian_ai.training.families import Prediction

        raw = outputs.detach().cpu().numpy() if hasattr(outputs, "detach") else np.asarray(outputs)
        predictions = []
        for image in raw:
            boxes_px = image[:, :4]
            objectness = image[:, 4]
            class_scores = image[:, 5:]
            labels = class_scores.argmax(axis=1)
            scores = objectness * class_scores.max(axis=1)
            keep = scores >= _SCORE_FLOOR
            boxes = boxes_px[keep] / self._input_size
            scores_kept = scores[keep]
            labels_kept = labels[keep]

            kept_indices: list[int] = []
            for label in np.unique(labels_kept):
                mask = labels_kept == label
                local = nms(boxes[mask], scores_kept[mask], _NMS_IOU_THRESHOLD)
                kept_indices.extend(np.nonzero(mask)[0][local].tolist())

            if kept_indices:
                predictions.append(
                    Prediction(
                        boxes=boxes[kept_indices].astype(np.float32),
                        scores=scores_kept[kept_indices].astype(np.float32),
                        labels=labels_kept[kept_indices].astype(np.int64),
                    )
                )
            else:
                predictions.append(
                    Prediction(
                        boxes=np.zeros((0, 4), dtype=np.float32),
                        scores=np.zeros((0,), dtype=np.float32),
                        labels=np.zeros((0,), dtype=np.int64),
                    )
                )
        return predictions

    def input_name(self) -> str:
        return "images"

    def output_name(self) -> str:
        return "output"
