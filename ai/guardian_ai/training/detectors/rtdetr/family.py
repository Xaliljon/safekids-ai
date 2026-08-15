"""RtDetrTrainer: the DetectorFamily wrapping RT-DETR from `transformers`.

Output tensor contract (identical to every other Guardian family): one
``(batch, queries, 5 + num_classes)`` tensor of
``[cx, cy, w, h, objectness, class_scores...]``, boxes already normalized.

One architectural difference is disclosed rather than hidden: **RT-DETR runs
no NMS**. It is trained with one-to-one Hungarian matching, so duplicate
predictions are suppressed by the loss rather than by postprocessing, and
adding NMS would be applying a fix for a problem this architecture does not
have. Sprint 22 §14 requires differences like this to be documented, not
smoothed over — see architecture/rtdetr-evaluation.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from guardian_ai.training.detectors.rtdetr.targets import to_rtdetr_labels
from guardian_ai.training.detectors.rtdetr.variants import (
    DEFAULT_INPUT_SIZE,
    LICENSE,
    get_variant,
)
from guardian_ai.training.detectors.rtdetr.wrapper import RtDetrWrapper
from guardian_ai.training.errors import TrainingConfigurationError

_SCORE_FLOOR = 0.05


class RtDetrTrainer:
    """One DetectorFamily per RT-DETR variant — see ``families.py`` for the
    ``rtdetr-<variant>`` registrations."""

    license = LICENSE

    def __init__(self, variant: str) -> None:
        self._variant = get_variant(variant)
        self.name = f"rtdetr-{variant}"
        self._input_size = DEFAULT_INPUT_SIZE
        self._num_classes = 1
        self._wrapper: RtDetrWrapper | None = None

    def build(
        self,
        num_classes: int,
        input_size: int,
        pretrained: bool = False,
        checkpoint: Path | None = None,
    ) -> Any:
        try:
            from transformers import RTDetrConfig, RTDetrForObjectDetection
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise TrainingConfigurationError(
                f"{self.name}: transformers is required for RT-DETR "
                f"(Apache-2.0, declared in ai/pyproject.toml): {exc}"
            ) from exc

        self._num_classes = num_classes
        self._input_size = input_size
        checkpoint_sha256: str | None = None

        if checkpoint is not None:
            model = RTDetrForObjectDetection.from_pretrained(
                str(checkpoint), num_labels=num_classes, ignore_mismatched_sizes=True
            )
            checkpoint_sha256 = _sha256_of_tree(Path(checkpoint))
        elif pretrained:
            # COCO weights for everything except the classification head,
            # which cannot transfer: 80 classes in, num_classes out.
            model = RTDetrForObjectDetection.from_pretrained(
                self._variant.model_id,
                revision=self._variant.revision,
                num_labels=num_classes,
                ignore_mismatched_sizes=True,
            )
        else:
            config = RTDetrConfig.from_pretrained(
                self._variant.model_id, revision=self._variant.revision
            )
            config.num_labels = num_classes
            model = RTDetrForObjectDetection(config)

        self._wrapper = RtDetrWrapper(model)
        self._wrapper.checkpoint_sha256 = checkpoint_sha256
        return self._wrapper

    def loss(self, outputs: Any, targets: list[tuple[Any, Any]]) -> Any:
        if self._wrapper is None:
            raise TrainingConfigurationError(f"{self.name}: build() must run before loss()")
        device = getattr(outputs, "device", None)
        return self._wrapper.compute_loss(to_rtdetr_labels(targets, device))

    def decode(self, outputs: Any) -> list[Any]:
        from guardian_ai.training.families import Prediction

        raw = outputs.detach().cpu().numpy() if hasattr(outputs, "detach") else np.asarray(outputs)
        predictions = []
        for image in raw:
            boxes = image[:, :4]  # already normalized — RT-DETR predicts in [0,1]
            objectness = image[:, 4]
            class_scores = image[:, 5:]
            labels = class_scores.argmax(axis=1)
            scores = objectness * class_scores.max(axis=1)
            keep = scores >= _SCORE_FLOOR
            # No NMS: one-to-one Hungarian matching already suppresses
            # duplicates, and running it anyway would silently change the
            # comparison against YOLOX in RT-DETR's favour or against it.
            predictions.append(
                Prediction(
                    boxes=boxes[keep].astype(np.float32),
                    scores=scores[keep].astype(np.float32),
                    labels=labels[keep].astype(np.int64),
                )
            )
        return predictions

    def input_name(self) -> str:
        return "images"

    def output_name(self) -> str:
        return "output"


def _sha256_of_tree(path: Path) -> str | None:
    """Checksum of a local checkpoint file, or None for a directory export."""
    import hashlib

    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
