"""guardian_dataset_v1 — the one layout every dataset ends in.

    <workspace>/
      dataset.json            manifest: name, taxonomy binding, provenance, privacy
      train/clips.jsonl       split membership (one clip id per line)
      val/clips.jsonl
      test/clips.jsonl
      videos/<clip>.mp4       normalized clips (deterministic encoding)
      annotations/<clip>.json Guardian Video Annotation v1
      metadata/<clip>.json    per-clip provenance + lineage (source, camera angle…)
      metadata/review.json    review workflow state + audit history
      taxonomy/taxonomy.json  the bound taxonomy snapshot

Split assignment is the ADR-0010 hash function — stable, seedless,
growth-proof — applied to the clip's *split group* (its room, camera or
subject) rather than to the clip id, so material that recurs across clips
cannot straddle train and val.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.annotations import ClipAnnotation, load_annotation, save_annotation
from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.taxonomy import GUARDIAN_VIDEO_TAXONOMY_V1
from guardian_ai.datasets.splits import assign_split

MANIFEST_FILE = "dataset.json"
SPLIT_NAMES = ("train", "val", "test")
SPLIT_FILE = "clips.jsonl"
VIDEOS_DIR = "videos"
ANNOTATIONS_DIR = "annotations"
METADATA_DIR = "metadata"
TAXONOMY_DIR = "taxonomy"
TAXONOMY_FILE = "taxonomy.json"


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    """Ethics-bearing manifest, mirroring ADR-0010 §3 for video datasets."""

    name: str
    description: str
    collected_by: str
    consent_reference: str
    contains_minors: bool
    anonymized: bool
    review_reference: str = ""
    license: str = "Proprietary-GuardianAI"
    created_utc: str = ""
    attributes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "guardian-dataset/1",
            "name": self.name,
            "description": self.description,
            "taxonomy": {
                "name": GUARDIAN_VIDEO_TAXONOMY_V1.name,
                "version": GUARDIAN_VIDEO_TAXONOMY_V1.version,
            },
            "provenance": {
                "collected_by": self.collected_by,
                "consent_reference": self.consent_reference,
            },
            "privacy": {
                "contains_minors": self.contains_minors,
                "anonymized": self.anonymized,
                "review_reference": self.review_reference,
            },
            "license": self.license,
            "created_utc": self.created_utc,
            "attributes": self.attributes,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> WorkspaceManifest:
        return WorkspaceManifest(
            name=str(raw["name"]),
            description=str(raw.get("description", "")),
            collected_by=str(raw["provenance"]["collected_by"]),
            consent_reference=str(raw["provenance"]["consent_reference"]),
            contains_minors=bool(raw["privacy"]["contains_minors"]),
            anonymized=bool(raw["privacy"]["anonymized"]),
            review_reference=str(raw["privacy"].get("review_reference", "")),
            license=str(raw.get("license", "Proprietary-GuardianAI")),
            created_utc=str(raw.get("created_utc", "")),
            attributes={str(k): str(v) for k, v in raw.get("attributes", {}).items()},
        )


class DatasetWorkspace:
    """One dataset in the making — the only API that touches the layout."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------ creation

    @staticmethod
    def create(root: Path, manifest: WorkspaceManifest) -> DatasetWorkspace:
        if (root / MANIFEST_FILE).exists():
            raise AcquisitionError(f"workspace already exists: {root}")
        for name in (VIDEOS_DIR, ANNOTATIONS_DIR, METADATA_DIR, TAXONOMY_DIR, *SPLIT_NAMES):
            (root / name).mkdir(parents=True, exist_ok=True)
        _write_json(root / MANIFEST_FILE, manifest.to_dict())
        taxonomy = GUARDIAN_VIDEO_TAXONOMY_V1
        _write_json(
            root / TAXONOMY_DIR / TAXONOMY_FILE,
            {
                "name": taxonomy.name,
                "version": taxonomy.version,
                "labels": [
                    {"name": label.name, "description": label.description}
                    for label in taxonomy.labels
                ],
            },
        )
        for split in SPLIT_NAMES:
            (root / split / SPLIT_FILE).touch()
        return DatasetWorkspace(root)

    @staticmethod
    def open(root: Path) -> DatasetWorkspace:
        if not (root / MANIFEST_FILE).is_file():
            raise AcquisitionError(f"not a guardian_dataset_v1 workspace: {root}")
        return DatasetWorkspace(root)

    # ------------------------------------------------------------ manifest

    @property
    def manifest(self) -> WorkspaceManifest:
        raw = json.loads((self.root / MANIFEST_FILE).read_text(encoding="utf-8"))
        return WorkspaceManifest.from_dict(raw)

    def manifest_raw(self) -> dict[str, Any]:
        return dict(json.loads((self.root / MANIFEST_FILE).read_text(encoding="utf-8")))

    # --------------------------------------------------------------- clips

    def add_clip(
        self,
        clip_id: str,
        video_source: Path,
        annotation: ClipAnnotation,
        metadata: dict[str, Any],
        split_group: str | None = None,
    ) -> str:
        """Register a normalized clip; returns its split. Move, not copy —
        the normalizer already produced the file; raws are never stored.

        The split is hashed from ``split_group`` when the importer names one,
        so every clip sharing a room, camera or subject lands in the same
        split. Hashing the clip id instead is what let all four Le2i scenes
        appear in both train and val, and a validation set that shares its
        rooms with training cannot report generalization.
        """
        if clip_id != annotation.clip_id:
            raise AcquisitionError(
                f"clip id '{clip_id}' does not match annotation '{annotation.clip_id}'"
            )
        destination = self.video_path(clip_id)
        if destination.exists():
            raise AcquisitionError(f"clip '{clip_id}' already in workspace")
        video_source.replace(destination)
        save_annotation(annotation, self.annotation_path(clip_id))
        _write_json(self.metadata_path(clip_id), metadata)
        split = assign_split(split_group or clip_id)
        entry: dict[str, Any] = {"clip_id": clip_id}
        if split_group is not None:
            entry["split_group"] = split_group
        with (self.root / split / SPLIT_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return split

    def split_groups(self, split: str | None = None) -> dict[str, str]:
        """Group key per clip id, for clips whose importer declared one."""
        splits = (split,) if split else SPLIT_NAMES
        groups: dict[str, str] = {}
        for name in splits:
            path = self.root / name / SPLIT_FILE
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("split_group") is not None:
                    groups[str(entry["clip_id"])] = str(entry["split_group"])
        return groups

    def straddling_groups(self) -> dict[str, list[str]]:
        """Group keys that appear in more than one split — should be empty.

        The check the candidate provenance review had to do by hand. It is
        cheap, and it is the only thing standing between a future import and
        a validation score that measures memorization.
        """
        per_group: dict[str, set[str]] = {}
        for split in SPLIT_NAMES:
            for group in self.split_groups(split).values():
                per_group.setdefault(group, set()).add(split)
        return {group: sorted(splits) for group, splits in per_group.items() if len(splits) > 1}

    def clip_ids(self, split: str | None = None) -> list[str]:
        splits = (split,) if split else SPLIT_NAMES
        ids: list[str] = []
        for name in splits:
            path = self.root / str(name) / SPLIT_FILE
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ids.append(str(json.loads(line)["clip_id"]))
        return ids

    def split_of(self, clip_id: str) -> str:
        for split in SPLIT_NAMES:
            if clip_id in self.clip_ids(split):
                return split
        raise AcquisitionError(f"clip '{clip_id}' is not in any split")

    def video_path(self, clip_id: str) -> Path:
        return self.root / VIDEOS_DIR / f"{clip_id}.mp4"

    def annotation_path(self, clip_id: str) -> Path:
        return self.root / ANNOTATIONS_DIR / f"{clip_id}.json"

    def metadata_path(self, clip_id: str) -> Path:
        return self.root / METADATA_DIR / f"{clip_id}.json"

    def annotation(self, clip_id: str) -> ClipAnnotation:
        return load_annotation(self.annotation_path(clip_id))

    def metadata(self, clip_id: str) -> dict[str, Any]:
        return dict(json.loads(self.metadata_path(clip_id).read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)
