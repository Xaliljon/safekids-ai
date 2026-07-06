"""Detector families: the training engine never depends on one detector.

A ``DetectorFamily`` owns everything architecture-specific — building the
torch module, the loss, decoding predictions, and the export interface.
The engine only speaks this protocol, so YOLOv8 / YOLO11 / RT-DETR each
land as one new registered family, never as engine changes.

Families in v1:

- ``tiny-ssd``  — a small, genuinely trainable single-object detector used
  to prove the whole platform end to end (smoke training on the dummy
  dataset). Not a production model.
- ``yolox-tiny`` — RESERVED. The production family; its trainer lands with
  the first real training run, which is gated behind the Sprint 17
  architecture review ("do not train any model yet"). Configs referencing
  it fail loudly with that explanation, never silently.
- ``yolov8`` / ``yolo11`` — RESERVED and additionally license-blocked
  (AGPL, ADR-0003) until a compliant implementation path is approved.
- ``rt-detr`` — RESERVED (Apache-2.0; scheduled after YOLOX).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    """Everything architecture-specific, behind one port."""

    name: str
    license: str

    def build(self, num_classes: int, input_size: int) -> torch.nn.Module: ...

    def loss(
        self, outputs: torch.Tensor, boxes: torch.Tensor, labels: torch.Tensor
    ) -> torch.Tensor: ...

    def decode(self, outputs: torch.Tensor) -> list[Prediction]: ...

    def input_name(self) -> str: ...

    def output_name(self) -> str: ...


_FAMILIES: dict[str, Callable[[], DetectorFamily]] = {}
_RESERVED: dict[str, str] = {
    "yolox-tiny": (
        "the production YOLOX-tiny trainer lands with the first REAL training "
        "run — gated behind the Sprint 17 architecture review "
        "('do not train any model yet'). Use family 'tiny-ssd' for platform "
        "smoke runs."
    ),
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

    def build(self, num_classes: int, input_size: int) -> torch.nn.Module:
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
        self, outputs: torch.Tensor, boxes: torch.Tensor, labels: torch.Tensor
    ) -> torch.Tensor:
        import torch
        from torch.nn import functional

        box_loss = functional.l1_loss(outputs[:, :4], boxes)
        objectness_loss = functional.binary_cross_entropy_with_logits(
            outputs[:, 4], torch.ones_like(outputs[:, 4])
        )
        class_loss = functional.cross_entropy(outputs[:, 5:], labels)
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
