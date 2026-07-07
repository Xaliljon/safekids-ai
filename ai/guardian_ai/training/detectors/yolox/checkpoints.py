"""COCO-pretrained checkpoint loading — automatic download, checksum-pinned.

Downloads go through ``torch.hub`` against YOLOX's own documented release
URLs (``variants.py``, copied from their ``models/build.py`` — not a URL
this module invents). The first successful download's SHA-256 is
recorded into a local manifest (trust-on-first-use, the same pattern as
``edge/guardian_edge/tools/install_yolox.py``) and enforced on every
later load — a corrupted or swapped cache file is rejected, never
silently trusted.

A pretrained checkpoint's head was trained for 80 COCO classes. When our
``num_classes`` differs, only the backbone loads from the checkpoint —
the head starts from scratch (standard transfer-learning practice; the
backbone still carries real, COCO-learned visual features).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from guardian_ai.training.detectors.yolox.variants import YoloxVariant
from guardian_ai.training.errors import TrainingConfigurationError

logger = logging.getLogger(__name__)

MANIFEST_FILE = "checksums.json"
_COCO_CLASSES = 80


def cache_dir() -> Path:
    import torch

    return Path(torch.hub.get_dir()) / "guardian-yolox-checkpoints"


def download_pretrained(variant: YoloxVariant) -> Path:
    """Download (or reuse the cache) + verify checksum. Trust-on-first-use."""
    import torch

    cache_dir().mkdir(parents=True, exist_ok=True)
    destination = cache_dir() / f"yolox_{variant.name}.pth"
    if not destination.is_file():
        logger.info(
            "downloading official YOLOX-%s checkpoint: %s", variant.name, variant.checkpoint_url
        )
        torch.hub.download_url_to_file(variant.checkpoint_url, str(destination))
    digest = sha256_of(destination)
    manifest = _read_manifest()
    recorded = manifest.get(variant.name)
    if recorded is None:
        manifest[variant.name] = digest
        _write_manifest(manifest)
        logger.info("pinned checksum for yolox-%s: %s", variant.name, digest[:16])
    elif recorded != digest:
        raise TrainingConfigurationError(
            f"cached checkpoint for yolox-{variant.name} does not match its pinned "
            f"checksum ({recorded[:16]}... expected, got {digest[:16]}...) — delete "
            f"{destination} and re-download; the cache may be corrupted or tampered"
        )
    return destination


def load_into(model: Any, checkpoint_path: Path, num_classes: int) -> list[str]:
    """Load a .pth state dict into ``model``. Returns which parameter
    groups were skipped (e.g. ``["head"]`` when num_classes != 80)."""
    import torch

    if not checkpoint_path.is_file():
        raise TrainingConfigurationError(f"checkpoint not found: {checkpoint_path}")
    raw = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    state_dict = raw.get("model", raw) if isinstance(raw, dict) else raw
    skipped: list[str] = []
    if num_classes != _COCO_CLASSES:
        state_dict = {k: v for k, v in state_dict.items() if not k.startswith("head.")}
        skipped.append("head")
    missing, unexpected = model.load_state_dict(state_dict, strict=False)
    logger.info(
        "loaded checkpoint %s (skipped=%s, missing=%d, unexpected=%d)",
        checkpoint_path.name,
        skipped,
        len(missing),
        len(unexpected),
    )
    return skipped


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path() -> Path:
    return cache_dir() / MANIFEST_FILE


def _read_manifest() -> dict[str, str]:
    path = _manifest_path()
    if not path.is_file():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_manifest(manifest: dict[str, str]) -> None:
    _manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")
