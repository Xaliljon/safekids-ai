"""Per-model activation state (active/previous version pointers).

Stored as ``state.json`` inside each model's directory and always written
atomically (temp file + rename): a crash mid-write leaves either the old
state or the new state, never a torn file — the property OTA rollback
depends on (ADR-0009).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from guardian_edge.domain.errors import ModelRegistryError

STATE_FILE_NAME = "state.json"


@dataclass(frozen=True, slots=True)
class ModelState:
    """Which version serves, and which one rollback returns to."""

    active: str | None = None
    previous: str | None = None


def read_state(model_dir: Path) -> ModelState:
    """State for one model; empty state when never activated."""
    path = model_dir / STATE_FILE_NAME
    if not path.is_file():
        return ModelState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"corrupt model state '{path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelRegistryError(f"corrupt model state '{path}': expected an object")
    active = raw.get("active")
    previous = raw.get("previous")
    return ModelState(
        active=str(active) if active is not None else None,
        previous=str(previous) if previous is not None else None,
    )


def write_state(model_dir: Path, state: ModelState) -> None:
    """Atomically persist state (write temp, rename over)."""
    path = model_dir / STATE_FILE_NAME
    temporary = path.with_name(STATE_FILE_NAME + ".tmp")
    temporary.write_text(
        json.dumps({"active": state.active, "previous": state.previous}),
        encoding="utf-8",
    )
    temporary.replace(path)
