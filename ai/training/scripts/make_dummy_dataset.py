"""Generate and publish a synthetic detection dataset for platform smoke runs.

Sprint 17 rule: "Do not train any model yet... use dummy datasets." This
script fabricates images (one colored rectangle per class on a noisy
background), authors a Sprint-7 dataset bundle, pushes it through the
registry's publish gates (quality + privacy) and installs the media next
to the registered version. Nothing here is real child data — the privacy
declaration says exactly that.

Usage:
    python ai/training/scripts/make_dummy_dataset.py \
        --registry ai/training/datasets/registry --version 1.0.0
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
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

IMAGE_SIZE = 128
# One unmistakable color per class so a tiny model can genuinely learn.
CLASS_COLORS = {"child": (220, 60, 60), "adult": (60, 60, 220), "person": (60, 200, 60)}
SPLIT_SIZES = {"train": 24, "val": 8, "test": 8}


def _make_sample(rng: random.Random, split: str, index: int, media_dir: Path) -> SampleRecord:
    label = rng.choice(sorted(CLASS_COLORS))
    width = rng.uniform(0.25, 0.45)
    height = rng.uniform(0.25, 0.45)
    x = rng.uniform(0.05, 0.95 - width)
    y = rng.uniform(0.05, 0.95 - height)

    noise = np.asarray(
        [[rng.randint(90, 130) for _ in range(IMAGE_SIZE * 3)] for _ in range(IMAGE_SIZE)],
        dtype=np.uint8,
    ).reshape(IMAGE_SIZE, IMAGE_SIZE, 3)
    left, top = int(x * IMAGE_SIZE), int(y * IMAGE_SIZE)
    right, bottom = int((x + width) * IMAGE_SIZE), int((y + height) * IMAGE_SIZE)
    noise[top:bottom, left:right] = CLASS_COLORS[label]

    relative = f"images/{split}-{index:03d}.png"
    destination = media_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(noise).save(destination)
    return SampleRecord(
        path=relative,
        width=IMAGE_SIZE,
        height=IMAGE_SIZE,
        annotations=(
            Annotation(label=label, box=BoundingBox(x=x, y=y, width=width, height=height)),
        ),
    )


def build_and_publish(registry_root: Path, name: str, version: str, seed: int) -> dict:
    rng = random.Random(seed)
    staging = registry_root.parent / ".dummy-build"
    bundle_dir = staging / "bundle"
    media_dir = staging / "media"
    shutil.rmtree(staging, ignore_errors=True)
    (bundle_dir / "annotations").mkdir(parents=True)

    split_records: dict[str, list[SampleRecord]] = {}
    for split, count in SPLIT_SIZES.items():
        split_records[split] = [
            _make_sample(rng, split, index, media_dir) for index in range(count)
        ]
        write_records(bundle_dir / "annotations" / f"{split}.jsonl", split_records[split])

    manifest = DatasetManifest(
        name=name,
        version=version,
        description=(
            "Synthetic single-object detection dataset for training-platform "
            "smoke runs. Colored rectangles, no real imagery, no people."
        ),
        taxonomy_name=GUARDIAN_TAXONOMY_V1.name,
        taxonomy_version=GUARDIAN_TAXONOMY_V1.version,
        created_utc=datetime.now(tz=timezone.utc).isoformat(),
        provenance=Provenance(
            collected_by="make_dummy_dataset.py",
            consent_reference="synthetic/no-human-subjects",
        ),
        privacy=PrivacyDeclaration(
            contains_minors=False,
            anonymized=True,
            review_reference="synthetic/no-review-needed",
        ),
        splits={split: SplitFile(file_name=f"{split}.jsonl") for split in SPLIT_SIZES},
    )
    save_manifest(bundle_dir / DATASET_MANIFEST_NAME, manifest)

    registry = FileSystemDatasetRegistry(registry_root)
    published = registry.publish(bundle_dir, GUARDIAN_TAXONOMY_V1)

    # Media travels beside the registered metadata (DVC territory in real
    # datasets; copied directly for the synthetic one).
    version_media = registry_root / published.name / published.version / "media"
    shutil.copytree(media_dir, version_media)
    shutil.rmtree(staging, ignore_errors=True)

    return {
        "dataset": published.name,
        "version": published.version,
        "taxonomy": f"{published.taxonomy_name}@{published.taxonomy_version}",
        "splits": {split: len(records) for split, records in split_records.items()},
        "registry": str(registry_root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="ai/training/datasets/registry", type=Path)
    parser.add_argument("--name", default="dummy-detection")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--seed", type=int, default=2026)
    arguments = parser.parse_args(argv)
    summary = build_and_publish(
        arguments.registry, arguments.name, arguments.version, arguments.seed
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
