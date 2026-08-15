"""Guardian per-image targets -> the label dicts RT-DETR's loss expects.

Guardian passes ``targets[i] = (boxes_i, labels_i)`` with boxes normalized
``cx, cy, w, h``. RT-DETR wants ``{"class_labels": LongTensor(M),
"boxes": FloatTensor(M, 4)}`` in the *same* normalized cx/cy/w/h convention,
so this is packing rather than converting — there is no coordinate
transform here to get subtly wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch


def to_rtdetr_labels(
    targets: list[tuple[torch.Tensor, torch.Tensor]], device: Any = None
) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for boxes, classes in targets:
        entry_boxes = boxes.to(device) if device is not None else boxes
        entry_classes = classes.to(device) if device is not None else classes
        labels.append({"class_labels": entry_classes.long(), "boxes": entry_boxes.float()})
    return labels
