"""Privacy validation: datasets that identify people are rejected.

Mechanical floor over everything textual in a workspace — the manifest,
per-clip metadata, annotation attributes and labels:

- no identity-bearing keys (name, id, email, phone, gps, address, face…)
- no email addresses, phone numbers or GPS coordinates in values
- no face/identity labels anywhere near the taxonomy

The checker cannot see pixels (ADR-0010): anonymization and consent
remain human responsibilities, which is why the manifest must point at a
consent reference and — with minors — an ethics review reference.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from guardian_ai.acquisition.taxonomy import FORBIDDEN_LABEL_TERMS
from guardian_ai.acquisition.workspace import DatasetWorkspace

FORBIDDEN_KEYS = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "surname",
        "full_name",
        "person_id",
        "national_id",
        "passport",
        "ssn",
        "email",
        "e-mail",
        "phone",
        "phone_number",
        "mobile",
        "gps",
        "latitude",
        "longitude",
        "location",
        "address",
        "face",
        "face_id",
        "identity",
        "birthday",
        "birth_date",
    }
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?<![\w/.:-])\+?\d[\d\s().-]{7,}\d(?![\w/])")
_GPS = re.compile(r"(?<![\w.])-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}")


@dataclass(frozen=True, slots=True)
class PrivacyViolation:
    message: str
    where: str


@dataclass(frozen=True, slots=True)
class PrivacyReport:
    violations: tuple[PrivacyViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": [
                {"message": violation.message, "where": violation.where}
                for violation in self.violations
            ],
        }


def check_privacy(workspace: DatasetWorkspace) -> PrivacyReport:
    violations: list[PrivacyViolation] = []

    manifest = workspace.manifest
    if not manifest.consent_reference.strip():
        violations.append(
            PrivacyViolation(
                "manifest declares no consent_reference — data without documented "
                "consent is never published (docs/04)",
                "dataset.json",
            )
        )
    if manifest.contains_minors and not manifest.review_reference.strip():
        violations.append(
            PrivacyViolation(
                "dataset contains minors but has no ethics review_reference — "
                "children's data requires documented review",
                "dataset.json",
            )
        )
    # "name" at these exact paths is the DATASET/taxonomy name — a title,
    # not a person. Everything else spelled "name" stays forbidden.
    violations.extend(
        _scan(
            "dataset.json",
            workspace.manifest_raw(),
            allowed_paths=frozenset({"name", "taxonomy.name"}),
        )
    )

    for clip_id in workspace.clip_ids():
        metadata_path = workspace.metadata_path(clip_id)
        if metadata_path.is_file():
            violations.extend(
                _scan(f"metadata/{clip_id}", json.loads(metadata_path.read_text("utf-8")))
            )
        annotation_path = workspace.annotation_path(clip_id)
        if annotation_path.is_file():
            raw = json.loads(annotation_path.read_text("utf-8"))
            violations.extend(_scan(f"annotations/{clip_id}", raw.get("attributes", {})))
            violations.extend(_scan_labels(f"annotations/{clip_id}", raw))
    return PrivacyReport(tuple(violations))


def _scan(
    where: str,
    payload: Any,
    path: str = "",
    allowed_paths: frozenset[str] = frozenset(),
) -> list[PrivacyViolation]:
    """Recursive key + value scan of any JSON-shaped structure."""
    violations: list[PrivacyViolation] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else str(key)
            bare = str(key).lower().removeprefix("attr_")
            forbidden = bare in FORBIDDEN_KEYS or bare.endswith("_name")
            if forbidden and key_path not in allowed_paths:
                violations.append(
                    PrivacyViolation(
                        f"identity-bearing key '{key}' is forbidden", f"{where}:{key_path}"
                    )
                )
            violations.extend(_scan(where, value, key_path, allowed_paths))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            violations.extend(_scan(where, item, f"{path}[{index}]", allowed_paths))
    elif isinstance(payload, str):
        if _EMAIL.search(payload):
            violations.append(
                PrivacyViolation(f"email address in value '{payload}'", f"{where}:{path}")
            )
        elif _PHONE.search(payload):
            violations.append(
                PrivacyViolation(f"phone number in value '{payload}'", f"{where}:{path}")
            )
        elif _GPS.search(payload):
            violations.append(
                PrivacyViolation(f"GPS coordinates in value '{payload}'", f"{where}:{path}")
            )
    return violations


def _scan_labels(where: str, raw: dict[str, Any]) -> list[PrivacyViolation]:
    """No face/identity labels — not even ones a converter smuggled in."""
    violations: list[PrivacyViolation] = []
    labels: set[str] = set()
    for frame in raw.get("frames", ()):
        for box in frame.get("boxes", ()):
            labels.add(str(box.get("label", "")).lower())
    for event in raw.get("events", ()):
        labels.add(str(event.get("label", "")).lower())
    for label in sorted(labels):
        if any(term in label for term in FORBIDDEN_LABEL_TERMS):
            violations.append(PrivacyViolation(f"identity label '{label}' is forbidden", where))
    return violations
