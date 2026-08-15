"""RT-DETR model-size variants — configuration only.

Guardian reaches RT-DETR through `transformers`, not through the paper
authors' repository. Both are Apache-2.0, but `lyuwenyu/RT-DETR` ships no
setup.py or pyproject.toml: it is research code rather than a package, so
using it would mean vendoring a copy — which is exactly what
architecture/detector-integration.md step 2 forbids ("never a fork").

Ultralytics also implements RT-DETR and is AGPL-3.0. It must never be the
source here, and `guardian_ai.training.families` blocks that family by name.
"""

from __future__ import annotations

from dataclasses import dataclass

LICENSE = "Apache-2.0"
DEFAULT_INPUT_SIZE = 640


@dataclass(frozen=True, slots=True)
class RtDetrVariant:
    name: str
    model_id: str
    """HuggingFace repository holding the COCO-pretrained weights."""

    revision: str
    """Pinned revision. "main" is not a version — a moving reference makes
    an experiment unreproducible, which ADR-0010 does not allow."""

    checkpoint_sha256: str | None = None
    """Pinned once a real download has recorded it; None means unpinned."""


VARIANTS: dict[str, RtDetrVariant] = {
    "r18vd": RtDetrVariant("r18vd", "PekingU/rtdetr_r18vd", revision="main"),
    "r34vd": RtDetrVariant("r34vd", "PekingU/rtdetr_r34vd", revision="main"),
    "r50vd": RtDetrVariant("r50vd", "PekingU/rtdetr_r50vd", revision="main"),
    "r101vd": RtDetrVariant("r101vd", "PekingU/rtdetr_r101vd", revision="main"),
}


def get_variant(name: str) -> RtDetrVariant:
    """Resolve a variant, or fail loudly with the list of real ones."""
    from guardian_ai.training.errors import TrainingConfigurationError

    variant = VARIANTS.get(name)
    if variant is None:
        raise TrainingConfigurationError(
            f"unknown rtdetr variant '{name}' (available: {sorted(VARIANTS)})"
        )
    return variant
