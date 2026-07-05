"""Dataset manifest (dataset.json): identity, provenance, and privacy posture.

The manifest is where docs/04 dataset ethics become required fields instead
of good intentions: who collected the data, under which consent, whether
minors appear, and which ethics review approved it. A dataset without these
answers cannot be published.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_ai.datasets.errors import DatasetValidationError
from guardian_ai.datasets.versioning import DatasetVersion

DATASET_MANIFEST_NAME = "dataset.json"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the data came from, lawfully."""

    collected_by: str
    consent_reference: str
    """Pointer to the consent documentation (agreement id, document path)."""

    notes: str = ""

    def __post_init__(self) -> None:
        if not self.collected_by.strip():
            raise DatasetValidationError("provenance.collected_by must not be empty")


@dataclass(frozen=True, slots=True)
class PrivacyDeclaration:
    """The dataset's explicit privacy posture — never implicit."""

    contains_minors: bool
    anonymized: bool
    review_reference: str = ""
    """Pointer to the ethics review record (mandatory when minors appear)."""


@dataclass(frozen=True, slots=True)
class SplitFile:
    """One split's annotation file; checksum/count are set at publish."""

    file_name: str
    sha256: str | None = None
    samples: int | None = None

    def __post_init__(self) -> None:
        if not self.file_name.strip():
            raise DatasetValidationError("split file_name must not be empty")


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Everything the platform needs to know about one dataset version."""

    name: str
    version: str
    description: str
    taxonomy_name: str
    taxonomy_version: str
    created_utc: str
    provenance: Provenance
    privacy: PrivacyDeclaration
    splits: Mapping[str, SplitFile]
    license: str = "Proprietary-GuardianAI"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DatasetValidationError("dataset name must not be empty")
        DatasetVersion.parse(self.version)
        if not self.taxonomy_name.strip() or not self.taxonomy_version.strip():
            raise DatasetValidationError(f"dataset '{self.name}': taxonomy binding is required")
        if not self.created_utc.strip():
            raise DatasetValidationError(f"dataset '{self.name}': created_utc is required")
        if not self.splits:
            raise DatasetValidationError(f"dataset '{self.name}': at least one split is required")


def load_manifest(path: Path) -> DatasetManifest:
    """Load and validate a dataset.json; raises DatasetValidationError."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetValidationError(f"cannot read manifest '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"manifest '{path}' is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise DatasetValidationError(f"manifest '{path}' must be a JSON object")
    try:
        return _parse(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise DatasetValidationError(f"manifest '{path}' is invalid: {exc}") from exc


def save_manifest(path: Path, manifest: DatasetManifest) -> None:
    path.write_text(json.dumps(_to_dict(manifest), indent=2, sort_keys=True), encoding="utf-8")


def _parse(raw: dict[str, Any]) -> DatasetManifest:
    provenance_raw = raw["provenance"]
    privacy_raw = raw["privacy"]
    if "contains_minors" not in privacy_raw or "anonymized" not in privacy_raw:
        raise DatasetValidationError(
            "privacy declaration must state contains_minors and anonymized explicitly"
        )
    splits = {
        str(name): SplitFile(
            file_name=str(entry["file"]),
            sha256=str(entry["sha256"]) if entry.get("sha256") is not None else None,
            samples=int(entry["samples"]) if entry.get("samples") is not None else None,
        )
        for name, entry in raw["splits"].items()
    }
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise DatasetValidationError("'metadata' must be an object")
    return DatasetManifest(
        name=str(raw["name"]),
        version=str(raw["version"]),
        description=str(raw.get("description", "")),
        taxonomy_name=str(raw["taxonomy"]["name"]),
        taxonomy_version=str(raw["taxonomy"]["version"]),
        created_utc=str(raw["created_utc"]),
        provenance=Provenance(
            collected_by=str(provenance_raw["collected_by"]),
            consent_reference=str(provenance_raw.get("consent_reference", "")),
            notes=str(provenance_raw.get("notes", "")),
        ),
        privacy=PrivacyDeclaration(
            contains_minors=bool(privacy_raw["contains_minors"]),
            anonymized=bool(privacy_raw["anonymized"]),
            review_reference=str(privacy_raw.get("review_reference", "")),
        ),
        splits=splits,
        license=str(raw.get("license", "Proprietary-GuardianAI")),
        metadata=metadata,
    )


def _to_dict(manifest: DatasetManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "taxonomy": {"name": manifest.taxonomy_name, "version": manifest.taxonomy_version},
        "created_utc": manifest.created_utc,
        "provenance": {
            "collected_by": manifest.provenance.collected_by,
            "consent_reference": manifest.provenance.consent_reference,
            "notes": manifest.provenance.notes,
        },
        "privacy": {
            "contains_minors": manifest.privacy.contains_minors,
            "anonymized": manifest.privacy.anonymized,
            "review_reference": manifest.privacy.review_reference,
        },
        "splits": {
            name: {"file": split.file_name, "sha256": split.sha256, "samples": split.samples}
            for name, split in manifest.splits.items()
        },
        "license": manifest.license,
        "metadata": dict(manifest.metadata),
    }
