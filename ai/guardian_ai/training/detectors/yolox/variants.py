"""Model-size variants — configuration only, nothing hardcoded elsewhere.

Depth/width multipliers match the official ``exps/default/*.py`` exactly
(read, not imported — these five numbers are the entire "variant table";
duplicating five floats per variant is not the kind of coupling ADR-0001
cares about). Adding a new variant is one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass

_BASE_IN_CHANNELS = (256, 512, 1024)
_STRIDES = (8, 16, 32)
_CKPT_RELEASE = "0.1.1rc0"
_CKPT_ROOT = f"https://github.com/Megvii-BaseDetection/YOLOX/releases/download/{_CKPT_RELEASE}"


@dataclass(frozen=True, slots=True)
class YoloxVariant:
    name: str
    depth: float
    width: float
    depthwise: bool
    checkpoint_url: str
    checkpoint_sha256: str | None
    """Pinned once a real download has recorded it — see checkpoints.py.
    None means "unpinned yet"; the first successful download pins it."""


VARIANTS: dict[str, YoloxVariant] = {
    "nano": YoloxVariant(
        "nano",
        depth=0.33,
        width=0.25,
        depthwise=True,
        checkpoint_url=f"{_CKPT_ROOT}/yolox_nano.pth",
        checkpoint_sha256=None,
    ),
    "tiny": YoloxVariant(
        "tiny",
        depth=0.33,
        width=0.375,
        depthwise=False,
        checkpoint_url=f"{_CKPT_ROOT}/yolox_tiny.pth",
        checkpoint_sha256=None,
    ),
    "s": YoloxVariant(
        "s",
        depth=0.33,
        width=0.50,
        depthwise=False,
        checkpoint_url=f"{_CKPT_ROOT}/yolox_s.pth",
        checkpoint_sha256=None,
    ),
    "m": YoloxVariant(
        "m",
        depth=0.67,
        width=0.75,
        depthwise=False,
        checkpoint_url=f"{_CKPT_ROOT}/yolox_m.pth",
        checkpoint_sha256=None,
    ),
    "l": YoloxVariant(
        "l",
        depth=1.0,
        width=1.0,
        depthwise=False,
        checkpoint_url=f"{_CKPT_ROOT}/yolox_l.pth",
        checkpoint_sha256=None,
    ),
}


def base_in_channels() -> tuple[int, int, int]:
    return _BASE_IN_CHANNELS


def strides() -> tuple[int, int, int]:
    return _STRIDES


def get_variant(name: str) -> YoloxVariant:
    from guardian_ai.training.errors import TrainingConfigurationError

    variant = VARIANTS.get(name)
    if variant is None:
        raise TrainingConfigurationError(
            f"unknown yolox variant '{name}' (available: {sorted(VARIANTS)})"
        )
    return variant
