"""Deterministic train/validation/test splitting.

A sample's split is a pure function of its path (stable hash), never of a
random seed or insertion order. Two properties fall out (ADR-0010):

- Reproducible: everyone computes the same split, on any machine, forever.
- Stable under growth: adding samples to a dataset never moves an existing
  sample between splits — the quiet way evaluation sets leak into training
  across dataset versions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from guardian_ai.datasets.annotations import SampleRecord
from guardian_ai.datasets.errors import DatasetValidationError

DEFAULT_SPLIT_RATIOS: dict[str, float] = {"train": 0.8, "val": 0.1, "test": 0.1}

_RATIO_TOLERANCE = 1e-6
_HASH_BYTES = 8
_HASH_SPAN = float(1 << (8 * _HASH_BYTES))


def validate_ratios(ratios: Mapping[str, float]) -> None:
    if not ratios:
        raise DatasetValidationError("split ratios must not be empty")
    for name, ratio in ratios.items():
        if not name.strip():
            raise DatasetValidationError("split names must not be empty")
        if ratio <= 0.0:
            raise DatasetValidationError(f"split '{name}' ratio must be positive, got {ratio}")
    total = sum(ratios.values())
    if abs(total - 1.0) > _RATIO_TOLERANCE:
        raise DatasetValidationError(f"split ratios must sum to 1.0, got {total}")


def assign_split(sample_path: str, ratios: Mapping[str, float] | None = None) -> str:
    """The split this sample belongs to — a pure function of its path."""
    ratios = ratios or DEFAULT_SPLIT_RATIOS
    validate_ratios(ratios)
    digest = hashlib.sha256(sample_path.encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:_HASH_BYTES], "big") / _HASH_SPAN
    cumulative = 0.0
    names = list(ratios)
    for name in names:
        cumulative += ratios[name]
        if fraction < cumulative:
            return name
    return names[-1]  # guard against floating-point edge at fraction ~= 1.0


def split_records(
    records: Iterable[SampleRecord], ratios: Mapping[str, float] | None = None
) -> dict[str, list[SampleRecord]]:
    """Partition records into named splits; every split key is present."""
    ratios = ratios or DEFAULT_SPLIT_RATIOS
    validate_ratios(ratios)
    result: dict[str, list[SampleRecord]] = {name: [] for name in ratios}
    for record in records:
        result[assign_split(record.path, ratios)].append(record)
    return result
