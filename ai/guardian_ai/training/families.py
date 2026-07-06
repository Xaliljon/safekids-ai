"""Detector families: the training engine never depends on one detector.

A ``DetectorFamily`` owns everything architecture-specific — building the
torch module, the loss, decoding predictions, and the export interface.
The engine only speaks this protocol, so YOLOv8 / YOLO11 / RT-DETR each
land as one new registered family, never as engine changes.

Families in v1:

- ``tiny-ssd``  — a small, genuinely trainable single-object detector used
  to prove the whole platform end to end (smoke training on the dummy
  dataset). Not a production model.
- ``yolox-nano`` / ``yolox-tiny`` / ``yolox-s`` / ``yolox-m`` / ``yolox-l``
  — the production families (ADR-0003: Apache-2.0), all backed by
  ``OfficialYoloxTrainer`` wrapping the real, unmodified upstream YOLOX
  package (Sprint 19.1 — see architecture/detector-integration.md for why
  Guardian does not maintain its own detector training code). Sprint 19
  shipped a from-scratch reimplementation first; an audit found it could
  not even converge objectness on a single overfit example, while the
  official implementation converges cleanly on the same example — that
  finding is why the custom implementation was removed rather than fixed.
- ``yolov8`` / ``yolo11`` — RESERVED and additionally license-blocked
  (AGPL, ADR-0003) until a compliant implementation path is approved.
- ``rt-detr`` — RESERVED (Apache-2.0; scheduled after YOLOX).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from guardian_ai.training.errors import TrainingConfigurationError

if TYPE_CHECKING:  # torch stays an ai/-only dependency; never on the edge
    import torch


@dataclass(frozen=True, slots=True)
class Prediction:
    """Decoded detections for ONE image."""

    boxes: np.ndarray  # (N, 4) normalized cx, cy, w, h
    scores: np.ndarray  # (N,)
    labels: np.ndarray  # (N,) class indices


class DetectorFamily(Protocol):
    """Everything architecture-specific, behind one port.

    ``loss`` takes per-image targets as a list — ``targets[i] = (boxes_i,
    labels_i)`` with ``boxes_i`` shaped ``(M_i, 4)`` — so the engine never
    assumes a fixed number of objects per image. Single-object families
    (tiny-ssd) simply read the first entry of each image's targets.

    ``build``'s ``pretrained``/``checkpoint`` kwargs exist for families
    that support transfer learning (Sprint 19.1 checkpoint support);
    families without a pretrained path (tiny-ssd) just ignore them.
    """

    name: str
    license: str

    def build(
        self,
        num_classes: int,
        input_size: int,
        pretrained: bool = False,
        checkpoint: Path | None = None,
    ) -> torch.nn.Module: ...

    def loss(
        self, outputs: torch.Tensor, targets: list[tuple[torch.Tensor, torch.Tensor]]
    ) -> torch.Tensor: ...

    def decode(self, outputs: torch.Tensor) -> list[Prediction]: ...

    def input_name(self) -> str: ...

    def output_name(self) -> str: ...


_FAMILIES: dict[str, Callable[[], DetectorFamily]] = {}
_RESERVED: dict[str, str] = {
    "yolov8": "license-blocked (AGPL-3.0, ADR-0003) — no compliant path approved yet",
    "yolo11": "license-blocked (AGPL-3.0, ADR-0003) — no compliant path approved yet",
    "rt-detr": "reserved (Apache-2.0); scheduled after YOLOX-tiny lands",
}


def register_family(name: str, factory: Callable[[], DetectorFamily]) -> None:
    _FAMILIES[name] = factory


def available_families() -> list[str]:
    return sorted(_FAMILIES)


def reserved_families() -> dict[str, str]:
    return dict(_RESERVED)


def get_family(name: str) -> DetectorFamily:
    factory = _FAMILIES.get(name)
    if factory is not None:
        return factory()
    if name in _RESERVED:
        raise TrainingConfigurationError(
            f"detector family '{name}' is reserved, not yet trainable: {_RESERVED[name]}"
        )
    raise TrainingConfigurationError(
        f"unknown detector family '{name}' (available: {available_families()}, "
        f"reserved: {sorted(_RESERVED)})"
    )


# --------------------------------------------------------------- tiny-ssd


class TinySsdFamily:
    """Single-object detector small enough to train in a smoke test.

    Output tensor: (batch, 5 + num_classes) = [cx, cy, w, h, objectness,
    class logits...] — everything normalized, batch=1 exportable, and
    decodable without any framework on the consumer side.
    """

    name = "tiny-ssd"
    license = "Proprietary-GuardianAI"

    def build(
        self,
        num_classes: int,
        input_size: int,
        pretrained: bool = False,  # smoke family has no pretrained path; ignored
        checkpoint: Path | None = None,  # ignored
    ) -> torch.nn.Module:
        import torch
        from torch import nn

        class TinySsd(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.backbone = nn.Sequential(
                    nn.Conv2d(3, 8, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv2d(8, 16, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv2d(16, 32, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.AdaptiveAvgPool2d(4),
                )
                self.head = nn.Sequential(
                    nn.Flatten(),
                    nn.Linear(32 * 16, 64),
                    nn.ReLU(),
                    nn.Linear(64, 5 + num_classes),
                )

            def forward(self, images: torch.Tensor) -> torch.Tensor:
                raw = self.head(self.backbone(images))
                box = torch.sigmoid(raw[:, :4])
                objectness = raw[:, 4:5]
                logits = raw[:, 5:]
                return torch.cat([box, objectness, logits], dim=1)

        return TinySsd()

    def loss(
        self, outputs: torch.Tensor, targets: list[tuple[torch.Tensor, torch.Tensor]]
    ) -> torch.Tensor:
        import torch
        from torch.nn import functional

        # single-object smoke family: the first annotation per image is the target
        box_targets = torch.stack([boxes[0] for boxes, _ in targets])
        label_targets = torch.stack([labels[0] for _, labels in targets])
        box_loss = functional.l1_loss(outputs[:, :4], box_targets)
        objectness_loss = functional.binary_cross_entropy_with_logits(
            outputs[:, 4], torch.ones_like(outputs[:, 4])
        )
        class_loss = functional.cross_entropy(outputs[:, 5:], label_targets)
        return box_loss * 5.0 + objectness_loss + class_loss

    def decode(self, outputs: torch.Tensor) -> list[Prediction]:
        import torch

        with torch.no_grad():
            boxes = outputs[:, :4].cpu().numpy()
            objectness = torch.sigmoid(outputs[:, 4]).cpu().numpy()
            probabilities = torch.softmax(outputs[:, 5:], dim=1).cpu().numpy()
        predictions = []
        for index in range(outputs.shape[0]):
            label = int(np.argmax(probabilities[index]))
            score = float(objectness[index] * probabilities[index][label])
            predictions.append(
                Prediction(
                    boxes=boxes[index : index + 1],
                    scores=np.array([score], dtype=np.float32),
                    labels=np.array([label], dtype=np.int64),
                )
            )
        return predictions

    def input_name(self) -> str:
        return "images"

    def output_name(self) -> str:
        return "output"


register_family(TinySsdFamily.name, TinySsdFamily)


# ---------------------------------------------------- official yolox (all sizes)


def _make_official_yolox(variant: str) -> Callable[[], DetectorFamily]:
    def factory() -> DetectorFamily:
        # deferred import: pulls in the full torch + upstream yolox module
        # tree, which every other family already avoids paying for at
        # import time.
        from guardian_ai.training.detectors.yolox.family import OfficialYoloxTrainer

        return OfficialYoloxTrainer(variant)

    return factory


for _variant in ("nano", "tiny", "s", "m", "l"):
    register_family(f"yolox-{_variant}", _make_official_yolox(_variant))


def family_metadata(family: DetectorFamily, num_classes: int, input_size: int) -> dict[str, Any]:
    """Facts the manifest generator needs, without touching torch."""
    return {
        "family": family.name,
        "license": family.license,
        "input_name": family.input_name(),
        "output_name": family.output_name(),
        "input_shape": [1, 3, input_size, input_size],
        "num_classes": num_classes,
    }
