"""Bridges RT-DETR's ``forward(pixel_values, labels) -> loss`` convention
onto Guardian's ``forward(images) -> outputs`` then ``loss(outputs,
targets)`` convention, exactly as ``OfficialYoloxWrapper`` does for YOLOX.

The two upstreams have the same shape of mismatch — both compute their loss
inside their own forward pass, and Guardian's ``DetectorFamily`` protocol
does not thread targets through ``forward()``. Solving it the same way twice
is deliberate: a second solution would be a second thing to understand, and
the protocol is not deficient (Sprint 22 §3) just because two vendors happen
to share a convention Guardian does not.

Cost is one extra forward pass per training step, same as YOLOX, and for the
same reason: reusing upstream's unmodified training path beats
reimplementing a DETR loss with Hungarian matching and denoising queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from torch import nn

if TYPE_CHECKING:
    import torch


class RtDetrWrapper(nn.Module):
    """Guardian-shaped façade over ``RTDetrForObjectDetection``.

    ``forward`` returns the concatenated ``(batch, queries, 5 + classes)``
    tensor every Guardian family returns: ``[cx, cy, w, h, objectness,
    class_scores...]``. RT-DETR is DETR-style and has no objectness head, so
    that column is a constant 1.0 and the whole score lives in the class
    probabilities — see ``family.decode``, which multiplies the two exactly
    as the YOLOX family does and therefore needs no special case.
    """

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.rtdetr_model = model
        self._cached_images: torch.Tensor | None = None
        self.checkpoint_sha256: str | None = None
        """Set by the owning family's ``build()``; read by engine.py for the
        experiment record, never referenced by name (duck-typed)."""

    def forward(self, images: torch.Tensor) -> Any:
        import torch

        if self.training:
            self._cached_images = images
            was_training = self.rtdetr_model.training
            self.rtdetr_model.eval()
            with torch.no_grad():
                outputs = self.rtdetr_model(pixel_values=images)
            if was_training:
                self.rtdetr_model.train()
            return _to_guardian_tensor(outputs)
        return _to_guardian_tensor(self.rtdetr_model(pixel_values=images))

    def compute_loss(self, labels: list[dict[str, Any]]) -> torch.Tensor:
        if self._cached_images is None:
            raise RuntimeError(
                "RtDetrWrapper.forward() must run before compute_loss() — "
                "the engine always calls model(images) before family.loss(...)"
            )
        self.rtdetr_model.train()
        outputs = self.rtdetr_model(pixel_values=self._cached_images, labels=labels)
        loss: torch.Tensor = outputs.loss
        return loss


def _to_guardian_tensor(outputs: Any) -> torch.Tensor:
    """``logits`` + ``pred_boxes`` -> the one tensor Guardian families return."""
    import torch

    boxes = outputs.pred_boxes  # (B, queries, 4) normalized cx, cy, w, h
    scores = outputs.logits.sigmoid()  # (B, queries, classes)
    objectness = torch.ones_like(scores[..., :1])
    return torch.cat([boxes, objectness, scores], dim=-1)
