"""Shared builders for training platform tests: a tiny REAL dataset.

Publishes a synthetic single-object detection dataset (colored rectangle
on a flat background) through the Sprint-7 registry — media included —
so training tests exercise the registry-only data path end to end.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from guardian_ai.datasets.annotations import (
    Annotation,
    BoundingBox,
    SampleRecord,
    write_records,
)
from guardian_ai.datasets.manifest import (
    DATASET_MANIFEST_NAME,
    DatasetManifest,
    PrivacyDeclaration,
    Provenance,
    SplitFile,
    save_manifest,
)
from guardian_ai.datasets.registry import FileSystemDatasetRegistry
from guardian_ai.datasets.taxonomy import GUARDIAN_TAXONOMY_V1
from guardian_ai.training.config import (
    DatasetConfig,
    EarlyStoppingConfig,
    ModelConfig,
    TrainingConfig,
)

IMAGE_SIZE = 64
CLASS_COLORS = {"child": (220, 60, 60), "adult": (60, 60, 220), "person": (60, 200, 60)}


def publish_tiny_dataset(
    registry_root: Path,
    name: str = "tiny-synthetic",
    version: str = "1.0.0",
    split_sizes: dict[str, int] | None = None,
    seed: int = 7,
) -> None:
    """Publish a small synthetic dataset (with media) into a registry."""
    split_sizes = split_sizes or {"train": 6, "val": 3, "test": 3}
    rng = random.Random(seed)
    staging = registry_root.parent / f".fixture-{name}-{version}"
    bundle = staging / "bundle"
    media = staging / "media"
    (bundle / "annotations").mkdir(parents=True)

    for split, count in split_sizes.items():
        records = []
        for index in range(count):
            label = rng.choice(sorted(CLASS_COLORS))
            width, height = rng.uniform(0.3, 0.4), rng.uniform(0.3, 0.4)
            x, y = rng.uniform(0.1, 0.9 - width), rng.uniform(0.1, 0.9 - height)
            pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), 110, dtype=np.uint8)
            left, top = int(x * IMAGE_SIZE), int(y * IMAGE_SIZE)
            right = int((x + width) * IMAGE_SIZE)
            bottom = int((y + height) * IMAGE_SIZE)
            pixels[top:bottom, left:right] = CLASS_COLORS[label]
            relative = f"images/{split}-{index:03d}.png"
            (media / relative).parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(pixels).save(media / relative)
            records.append(
                SampleRecord(
                    path=relative,
                    width=IMAGE_SIZE,
                    height=IMAGE_SIZE,
                    annotations=(
                        Annotation(
                            label=label,
                            box=BoundingBox(x=x, y=y, width=width, height=height),
                        ),
                    ),
                )
            )
        write_records(bundle / "annotations" / f"{split}.jsonl", records)

    manifest = DatasetManifest(
        name=name,
        version=version,
        description="Synthetic fixture dataset for training-platform tests.",
        taxonomy_name=GUARDIAN_TAXONOMY_V1.name,
        taxonomy_version=GUARDIAN_TAXONOMY_V1.version,
        created_utc=datetime.now(tz=timezone.utc).isoformat(),
        provenance=Provenance(
            collected_by="training_fixtures.py",
            consent_reference="synthetic/no-human-subjects",
        ),
        privacy=PrivacyDeclaration(
            contains_minors=False,
            anonymized=True,
            review_reference="synthetic/no-review-needed",
        ),
        splits={split: SplitFile(file_name=f"{split}.jsonl") for split in split_sizes},
    )
    save_manifest(bundle / DATASET_MANIFEST_NAME, manifest)
    registry = FileSystemDatasetRegistry(registry_root)
    published = registry.publish(bundle, GUARDIAN_TAXONOMY_V1)

    import shutil

    shutil.copytree(media, registry_root / published.name / published.version / "media")
    shutil.rmtree(staging, ignore_errors=True)


def make_training_config(
    registry_root: Path,
    output_dir: Path,
    name: str = "test-run",
    epochs: int = 2,
    dataset_name: str = "tiny-synthetic",
    early_stopping: EarlyStoppingConfig | None = None,
    seed: int = 2026,
) -> TrainingConfig:
    return TrainingConfig(
        name=name,
        model=ModelConfig(family="tiny-ssd", input_size=64),
        dataset=DatasetConfig(registry_root=registry_root, name=dataset_name),
        epochs=epochs,
        batch_size=4,
        early_stopping=early_stopping or EarlyStoppingConfig(enabled=False),
        seed=seed,
        output_dir=output_dir,
    )
