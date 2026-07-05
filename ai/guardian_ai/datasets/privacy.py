"""Dataset privacy checker.

Mechanical enforcement of the docs/04 dataset-ethics floor: consent must be
referenced, the presence of minors declared, and no identity-bearing data
may ride along in annotations. Children's data is the most sensitive thing
this company touches — a violation here blocks publication outright.

This checker is a floor, not a ceiling: passing it never replaces the human
ethics review the manifest's ``review_reference`` points to (docs/04,
responsible AI lifecycle).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from guardian_ai.datasets.annotations import SampleRecord
from guardian_ai.datasets.manifest import DatasetManifest

FORBIDDEN_ATTRIBUTE_KEYS = frozenset(
    {
        "name",
        "full_name",
        "first_name",
        "last_name",
        "face_id",
        "identity",
        "person_id",
        "student_id",
        "child_id",
        "address",
        "phone",
        "email",
        "birth_date",
        "national_id",
    }
)
"""Attribute keys that identify people. Guardian AI datasets describe
scenes, never individuals (docs/04: no facial recognition, no profiling)."""

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


@dataclass(frozen=True, slots=True)
class PrivacyViolation:
    message: str
    sample: str | None = None


@dataclass(frozen=True, slots=True)
class PrivacyReport:
    violations: tuple[PrivacyViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def check_privacy(
    manifest: DatasetManifest, splits: Mapping[str, Sequence[SampleRecord]]
) -> PrivacyReport:
    """Check a dataset's manifest and every record for privacy violations."""
    violations: list[PrivacyViolation] = []
    violations.extend(_check_manifest(manifest))
    for records in splits.values():
        for record in records:
            violations.extend(_check_record(record))
    return PrivacyReport(violations=tuple(violations))


def _check_manifest(manifest: DatasetManifest) -> list[PrivacyViolation]:
    violations: list[PrivacyViolation] = []
    if not manifest.provenance.consent_reference.strip():
        violations.append(
            PrivacyViolation(
                "manifest declares no consent_reference — data without documented "
                "consent is never published (docs/04, dataset ethics)"
            )
        )
    if manifest.privacy.contains_minors and not manifest.privacy.review_reference.strip():
        violations.append(
            PrivacyViolation(
                "dataset contains minors but declares no ethics review_reference — "
                "children's data requires documented review before publication"
            )
        )
    return violations


def _check_record(record: SampleRecord) -> list[PrivacyViolation]:
    violations: list[PrivacyViolation] = []
    violations.extend(_check_path(record))
    attribute_sets = [record.attributes]
    attribute_sets.extend(annotation.attributes for annotation in record.annotations)
    for attributes in attribute_sets:
        for key, value in attributes.items():
            if key.lower() in FORBIDDEN_ATTRIBUTE_KEYS:
                violations.append(
                    PrivacyViolation(
                        f"attribute key '{key}' identifies a person and is forbidden",
                        sample=record.path,
                    )
                )
            if _EMAIL_PATTERN.search(value):
                violations.append(
                    PrivacyViolation(
                        f"attribute '{key}' contains an email address", sample=record.path
                    )
                )
            elif _PHONE_PATTERN.search(value):
                violations.append(
                    PrivacyViolation(
                        f"attribute '{key}' contains a phone-like number", sample=record.path
                    )
                )
    return violations


def _check_path(record: SampleRecord) -> list[PrivacyViolation]:
    path = PurePosixPath(record.path)
    if path.is_absolute() or record.path.startswith(("~", "\\")) or ".." in path.parts:
        return [
            PrivacyViolation(
                "sample paths must be relative to the dataset (absolute or escaping "
                "paths leak collection-machine structure)",
                sample=record.path,
            )
        ]
    return []
