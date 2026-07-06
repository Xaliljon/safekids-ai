"""Review workflow: annotations never become production immediately.

    IMPORTED -> ANNOTATED -> REVIEWED -> APPROVED -> PUBLISHED

Transitions are strictly forward, one step at a time, and every step is
recorded with who did it, when, and their notes — the audit trail docs/04
demands. Publication (the registry) refuses anything not APPROVED.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from guardian_ai.acquisition.errors import WorkflowError

REVIEW_FILE = "metadata/review.json"


class ReviewState(str, Enum):
    IMPORTED = "imported"
    ANNOTATED = "annotated"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    PUBLISHED = "published"


_ORDER = list(ReviewState)


class ReviewWorkflow:
    """The review ledger of one dataset workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self._path = workspace_root / REVIEW_FILE

    def state(self) -> ReviewState | None:
        record = self._read()
        return ReviewState(record["state"]) if record else None

    def history(self) -> list[dict[str, Any]]:
        record = self._read()
        return list(record["history"]) if record else []

    def record(self, state: ReviewState, by: str, notes: str = "") -> None:
        """Record a transition. Forward-only, single steps, named actors."""
        if not by.strip():
            raise WorkflowError("every review transition needs a named actor")
        current = self.state()
        if current is None:
            if state is not ReviewState.IMPORTED:
                raise WorkflowError(
                    f"a new workspace starts at '{ReviewState.IMPORTED.value}', not '{state.value}'"
                )
        else:
            expected = _ORDER[_ORDER.index(current) + 1] if current is not _ORDER[-1] else None
            if state is not expected:
                raise WorkflowError(
                    f"illegal transition {current.value} -> {state.value}"
                    + (f" (next allowed: {expected.value})" if expected else " (already final)")
                )
        record = self._read() or {"state": state.value, "history": []}
        record["state"] = state.value
        record["history"].append(
            {
                "state": state.value,
                "by": by.strip(),
                "utc": datetime.now(tz=timezone.utc).isoformat(),
                "notes": notes,
            }
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temp.replace(self._path)

    def require(self, state: ReviewState, action: str) -> None:
        current = self.state()
        if current is not state:
            raise WorkflowError(
                f"{action} requires review state '{state.value}', "
                f"workspace is '{current.value if current else 'uninitialized'}'"
            )

    def approval(self) -> dict[str, Any]:
        """The approval entry (reviewer name, time, notes) — or refuse."""
        for entry in reversed(self.history()):
            if entry["state"] == ReviewState.APPROVED.value:
                return dict(entry)
        raise WorkflowError("no approval recorded in the review history")

    def _read(self) -> dict[str, Any] | None:
        if not self._path.is_file():
            return None
        try:
            return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"corrupt review record at {self._path}: {exc}") from exc
