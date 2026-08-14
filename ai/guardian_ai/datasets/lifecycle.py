"""Dataset version lifecycle — the tombstone that outranks immutability.

ADR-0010 makes a published version immutable so a training run can be
reproduced exactly. ADR-0005 decides what happens when that collides with a
guardian withdrawing consent for their child: consent wins.

Withdrawal does not edit the version. Editing it would break the checksums
that make it auditable in the first place, and erase the record of what a
model was actually trained on. It writes a *tombstone* beside the manifest
instead. The manifest keeps answering "what was this dataset"; the tombstone
answers "may it still be used", and the registry reads the second before
honouring the first.

Immutability survives as a historical fact and is revoked as a licence to
use — which is ADR-0005 §4 in one sentence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from guardian_ai.datasets.errors import DatasetValidationError

TOMBSTONE_NAME = "tombstone.json"


class DatasetLifecycle(Enum):
    """Whether a published version may still be used for training."""

    ACTIVE = "active"
    """Publishable, loadable, trainable. The absence of a tombstone."""

    WITHDRAWN = "withdrawn"
    """Consent was withdrawn (ADR-0005 §4). The manifest stays for audit;
    the registry refuses to load it for training, and any experiment naming
    it is blocked from promotion."""

    EXPIRED = "expired"
    """The retention period named in the ethics review elapsed
    (ADR-0005 §7). Same refusal, different clock."""


@dataclass(frozen=True, slots=True)
class Tombstone:
    """Why a version stopped being usable, and who says so.

    A withdrawal record is itself an audit artifact: it is what a director —
    or a regulator — is shown when they ask what happened after a parent
    asked. An anonymous one answers nothing, so ``reason`` and
    ``recorded_by`` are both required.
    """

    lifecycle: DatasetLifecycle
    reason: str
    recorded_utc: str
    recorded_by: str
    superseded_by: str | None = None
    """Version published in its place, when withdrawal produced one."""

    def __post_init__(self) -> None:
        if self.lifecycle is DatasetLifecycle.ACTIVE:
            raise DatasetValidationError(
                "a tombstone cannot record ACTIVE — an active version is one "
                "with no tombstone at all"
            )
        if not self.reason.strip():
            raise DatasetValidationError("tombstone reason must not be empty")
        if not self.recorded_by.strip():
            raise DatasetValidationError(
                "tombstone recorded_by must name a person — an unattributed "
                "withdrawal record cannot answer who acted on the request"
            )
        if not self.recorded_utc.strip():
            raise DatasetValidationError("tombstone recorded_utc must not be empty")


def load_tombstone(version_dir: Path) -> Tombstone | None:
    """Read the tombstone beside a version's manifest; None when active."""
    path = version_dir / TOMBSTONE_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"cannot read tombstone '{path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise DatasetValidationError(f"tombstone '{path}' must be a JSON object")
    try:
        lifecycle = DatasetLifecycle(str(raw["lifecycle"]))
    except (KeyError, ValueError) as exc:
        raise DatasetValidationError(f"tombstone '{path}' has no valid lifecycle: {exc}") from exc
    try:
        return Tombstone(
            lifecycle=lifecycle,
            reason=str(raw["reason"]),
            recorded_utc=str(raw["recorded_utc"]),
            recorded_by=str(raw["recorded_by"]),
            superseded_by=(
                str(raw["superseded_by"]) if raw.get("superseded_by") is not None else None
            ),
        )
    except KeyError as exc:
        raise DatasetValidationError(f"tombstone '{path}' is missing {exc}") from exc


def save_tombstone(version_dir: Path, tombstone: Tombstone) -> None:
    """Write a tombstone beside the manifest. Never overwrites an existing
    one — a recorded withdrawal is evidence, not a mutable field."""
    path = version_dir / TOMBSTONE_NAME
    if path.exists():
        raise DatasetValidationError(
            f"version at '{version_dir}' is already tombstoned — a withdrawal "
            f"record is an audit artifact and is never rewritten"
        )
    payload: dict[str, Any] = {
        "lifecycle": tombstone.lifecycle.value,
        "reason": tombstone.reason,
        "recorded_utc": tombstone.recorded_utc,
        "recorded_by": tombstone.recorded_by,
        "superseded_by": tombstone.superseded_by,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
