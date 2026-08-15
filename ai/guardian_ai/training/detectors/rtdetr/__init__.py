"""RT-DETR detector integration (Sprint 22).

Apache-2.0 throughout — see architecture/rtdetr-evaluation.md for the
licence audit and why `transformers` is the source rather than the paper
authors' unpackaged repository or Ultralytics' AGPL implementation.
"""

from __future__ import annotations

from guardian_ai.training.detectors.rtdetr.family import RtDetrTrainer
from guardian_ai.training.detectors.rtdetr.variants import VARIANTS, RtDetrVariant, get_variant

__all__ = ["VARIANTS", "RtDetrTrainer", "RtDetrVariant", "get_variant"]
