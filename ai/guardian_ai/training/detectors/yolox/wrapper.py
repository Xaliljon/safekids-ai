"""Bridges YOLOX's own ``forward(images, targets) -> loss`` convention
onto Guardian's ``forward(images) -> outputs`` then
``loss(outputs, targets) -> Tensor`` convention (``DetectorFamily``),
without touching ``engine.py``'s training loop or upstream source.

``engine.py`` always calls ``model(images)`` first (the ``DetectorFamily``
protocol doesn't thread targets through ``forward()``), so in train mode
this wrapper runs one throwaway eval-style pass (``no_grad``, purely so
the caller gets a same-shaped tensor back) and caches the input; the
real, gradient-carrying pass happens inside ``compute_loss()``, which
re-invokes the underlying YOLOX model *with* targets. This costs one
extra forward pass per training step — an accepted, documented tradeoff
for reusing upstream's unmodified training path instead of reimplementing
it (architecture/detector-integration.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from torch import nn

if TYPE_CHECKING:
    import torch


class OfficialYoloxWrapper(nn.Module):
    def __init__(self, yolox_model: nn.Module) -> None:
        super().__init__()
        self.yolox_model = yolox_model
        self._cached_images: torch.Tensor | None = None

    def forward(self, images: torch.Tensor) -> Any:
        import torch

        if self.training:
            self._cached_images = images
            was_training = self.yolox_model.training
            self.yolox_model.eval()
            with torch.no_grad():
                outputs = self.yolox_model(images)
            if was_training:
                self.yolox_model.train()
            return outputs
        return self.yolox_model(images)

    def compute_loss(self, padded_labels: torch.Tensor) -> torch.Tensor:
        if self._cached_images is None:
            raise RuntimeError(
                "OfficialYoloxWrapper.forward() must run before compute_loss() — "
                "the engine always calls model(images) before family.loss(...)"
            )
        self.yolox_model.train()
        result = self.yolox_model(self._cached_images, padded_labels)
        loss: torch.Tensor = result["total_loss"]
        return loss
