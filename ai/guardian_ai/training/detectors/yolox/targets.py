"""Adapts Guardian's per-image (boxes, labels) targets into YOLOX's own
padded-tensor label format: ``(batch, max_boxes, 5)`` =
``[class, cx, cy, w, h]`` in absolute pixel coordinates of the model's
input canvas, zero-padded for images with fewer boxes than the batch max
(YOLOX's own convention for detecting "real" vs. padding rows)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch


def to_yolox_labels(
    targets: list[tuple[torch.Tensor, torch.Tensor]], input_size: int
) -> torch.Tensor:
    import torch

    max_boxes = max((boxes.shape[0] for boxes, _ in targets), default=0)
    max_boxes = max(max_boxes, 1)  # keep a real dimension even for an all-empty batch
    device = targets[0][0].device if targets else torch.device("cpu")
    batch = torch.zeros((len(targets), max_boxes, 5), dtype=torch.float32, device=device)
    for image_index, (boxes, labels) in enumerate(targets):
        if boxes.shape[0] == 0:
            continue
        batch[image_index, : boxes.shape[0], 0] = labels.to(torch.float32)
        batch[image_index, : boxes.shape[0], 1:5] = boxes.to(torch.float32) * input_size
    return batch
