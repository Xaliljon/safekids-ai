"""Shared builders for dataset platform tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guardian_ai.datasets.annotations import (
    Annotation,
    BoundingBox,
    SampleRecord,
    write_records,
)
from guardian_ai.datasets.manifest import (
    DatasetManifest,
    PrivacyDeclaration,
    Provenance,
    SplitFile,
)
from guardian_ai.datasets.taxonomy import GUARDIAN_TAXONOMY_V1

BOX = BoundingBox(x=0.1, y=0.1, width=0.3, height=0.3)


def make_record(
    path: str = "images/000001.jpg",
    labels: tuple[str, ...] = ("child",),
    attributes: dict[str, str] | None = None,
    annotation_attributes: dict[str, str] | None = None,
) -> SampleRecord:
    return SampleRecord(
        path=path,
        width=1920,
        height=1080,
        annotations=tuple(
            Annotation(label=label, box=BOX, attributes=annotation_attributes or {})
            for label in labels
        ),
        attributes=attributes or {},
    )


def make_manifest(
    name: str = "kindergarten-scenes",
    version: str = "1.0.0",
    splits: dict[str, SplitFile] | None = None,
    consent_reference: str = "consent/agreement-2026-001",
    contains_minors: bool = True,
    review_reference: str = "ethics/review-2026-007",
) -> DatasetManifest:
    return DatasetManifest(
        name=name,
        version=version,
        description="Test dataset",
        taxonomy_name=GUARDIAN_TAXONOMY_V1.name,
        taxonomy_version=GUARDIAN_TAXONOMY_V1.version,
        created_utc="2026-07-05T12:00:00Z",
        provenance=Provenance(
            collected_by="Guardian AI pilot team",
            consent_reference=consent_reference,
        ),
        privacy=PrivacyDeclaration(
            contains_minors=contains_minors,
            anonymized=True,
            review_reference=review_reference,
        ),
        splits=splits
        or {
            "train": SplitFile(file_name="train.jsonl"),
            "val": SplitFile(file_name="val.jsonl"),
        },
    )


def build_bundle_dir(
    bundle_dir: Path,
    split_records: dict[str, list[SampleRecord]] | None = None,
    manifest: DatasetManifest | None = None,
    manifest_overrides: dict[str, Any] | None = None,
) -> Path:
    """Author a publishable dataset bundle directory."""
    split_records = split_records or {
        "train": [make_record(f"images/train-{i:03d}.jpg") for i in range(4)],
        "val": [make_record(f"images/val-{i:03d}.jpg") for i in range(2)],
    }
    manifest = manifest or make_manifest(
        splits={name: SplitFile(file_name=f"{name}.jsonl") for name in split_records}
    )
    annotations_dir = bundle_dir / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    for split_name, records in split_records.items():
        write_records(annotations_dir / f"{split_name}.jsonl", records)
    from guardian_ai.datasets.manifest import _to_dict  # test-only shortcut

    raw = _to_dict(manifest)
    if manifest_overrides:
        raw.update(manifest_overrides)
    (bundle_dir / "dataset.json").write_text(json.dumps(raw), encoding="utf-8")
    return bundle_dir
