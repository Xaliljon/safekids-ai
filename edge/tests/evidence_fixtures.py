"""Shared builders for the evidence platform tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from guardian_edge.domain.frame import Frame
from guardian_edge.domain.incident import Severity

BASE = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_frame(
    sequence: int,
    camera_id: str = "cam-1",
    at: datetime | None = None,
    width: int = 64,
    height: int = 48,
) -> Frame:
    """A tiny real image (sequence number encoded in pixel intensity)."""
    data = np.full((height, width, 3), fill_value=sequence % 255, dtype=np.uint8)
    return Frame(
        camera_id=camera_id,
        sequence=sequence,
        captured_at=at or (BASE + timedelta(seconds=sequence * 0.1)),
        width=width,
        height=height,
        data=data,
    )


def make_incident(
    camera_id: str = "cam-1",
    opened_at: datetime | None = None,
    severity: Severity = Severity.HIGH,
    incident_id=None,
):  # noqa: ANN201 - test builder
    from event_fixtures import make_safety_incident

    incident = make_safety_incident(severity=severity, camera_id=camera_id)
    if opened_at is None and incident_id is None:
        return incident
    from dataclasses import replace

    changes = {}
    if opened_at is not None:
        changes["opened_at"] = opened_at
        changes["last_event_at"] = opened_at
    if incident_id is not None:
        changes["incident_id"] = incident_id
    return replace(incident, **changes)


class FrozenClock:
    """datetime stand-in whose now() the test controls."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self, tz=None):  # noqa: ANN001, ANN201 - datetime protocol
        return self.at.astimezone(tz) if tz else self.at

    def advance(self, seconds: float) -> None:
        self.at = self.at + timedelta(seconds=seconds)
