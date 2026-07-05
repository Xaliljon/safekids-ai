"""Dataset metrics: the numbers bias evaluation starts from.

docs/04 requires every dataset's bias to be measured and documented; these
metrics are the mechanical part — label balance, split composition,
background share. Interpretation stays human.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from guardian_ai.datasets.annotations import SampleRecord


@dataclass(frozen=True, slots=True)
class DatasetMetrics:
    """Point-in-time descriptive statistics for a split dataset."""

    samples_total: int
    annotations_total: int
    samples_per_split: Mapping[str, int]
    annotations_per_label: Mapping[str, int]
    background_samples: int
    """Samples with zero annotations (negatives)."""

    mean_annotations_per_sample: float
    mean_box_area: float
    """Mean normalized box area over all annotations (0..1)."""

    label_imbalance: float | None
    """Most-frequent / least-frequent label count; None with <2 labels.
    Large values flag bias risks that must be reviewed (docs/04)."""


def compute_metrics(splits: Mapping[str, Sequence[SampleRecord]]) -> DatasetMetrics:
    samples_total = 0
    annotations_total = 0
    background = 0
    area_sum = 0.0
    per_split: dict[str, int] = {}
    per_label: dict[str, int] = {}

    for split_name, records in splits.items():
        per_split[split_name] = len(records)
        for record in records:
            samples_total += 1
            if not record.annotations:
                background += 1
            for annotation in record.annotations:
                annotations_total += 1
                area_sum += annotation.box.area
                per_label[annotation.label] = per_label.get(annotation.label, 0) + 1

    imbalance: float | None = None
    if len(per_label) >= 2:
        counts = per_label.values()
        imbalance = round(max(counts) / min(counts), 3)

    return DatasetMetrics(
        samples_total=samples_total,
        annotations_total=annotations_total,
        samples_per_split=dict(sorted(per_split.items())),
        annotations_per_label=dict(sorted(per_label.items())),
        background_samples=background,
        mean_annotations_per_sample=(
            round(annotations_total / samples_total, 3) if samples_total else 0.0
        ),
        mean_box_area=round(area_sum / annotations_total, 5) if annotations_total else 0.0,
        label_imbalance=imbalance,
    )
