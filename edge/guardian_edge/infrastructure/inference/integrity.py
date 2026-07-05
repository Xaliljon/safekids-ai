"""Artifact integrity helpers shared by the registry and the model zoo."""

from __future__ import annotations

import hashlib
from pathlib import Path

_HASH_CHUNK_BYTES = 1 << 20  # 1 MiB


def sha256_of(path: Path) -> str:
    """Streaming SHA-256 of a file (models can be hundreds of MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
