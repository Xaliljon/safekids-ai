"""Clock trust: may the box believe what time it is? (ADR-0018 §6-8)

Schedules put the clock in the safety path. A zone that stops being
enforced because the box misread the hour is a silently unwatched child,
so this module answers one question — *is local wall-clock time
trustworthy* — and the schedule may only ever act on a confident "yes".

The framing that matters: **drift is not the risk.** An uncompensated
crystal runs at most ~50 ppm (4.32 s/day), so a month offline costs about
two minutes against windows measured in hours. Distrusting a long-offline
box would disable safe-area enforcement over an error far too small to
move a boundary. The faults that *do* move a boundary are categorical:

    never synchronized | time ran backwards | no local timezone

Anything else is trusted, carrying an explicit error bound that widens
window edges rather than switching schedules off.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CRYSTAL_DRIFT_PPM = 50.0
"""Worst-case uncompensated crystal drift. Deliberately pessimistic: the
bound must never understate how wrong the clock could be."""

STATE_FILE_NAME = "clock.json"

_SYSTEMD_SYNCHRONIZED = Path("/run/systemd/timesync/synchronized")
"""systemd-timesyncd touches this once it has synchronized. ADR-0016 already
makes systemd a platform assumption; a daemon-specific text format would
not survive an image change, and an unreadable interface degrades to
untrusted, which enforces."""

_SYSTEMD_CLOCK_STATE = Path("/var/lib/systemd/timesync/clock")
"""Persisted across reboots by systemd, so a box that synchronized once
still counts as "has been set" after a power cut."""


@dataclass(frozen=True, slots=True)
class ClockStatus:
    """What the box may conclude about its own clock."""

    trusted: bool
    reason: str
    """Always populated — a status without a reason explains nothing."""

    last_synchronized_at: datetime | None = None
    error_bound_seconds: float = 0.0
    """How wrong local time could be, given time since synchronization.
    Only meaningful when ``trusted``; an untrusted clock has no bound,
    it has a fault."""

    timezone_name: str | None = None

    @property
    def error_bound_minutes(self) -> float:
        return self.error_bound_seconds / 60.0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ok" if self.trusted else "degraded",
            "trusted": self.trusted,
            "reason": self.reason,
            "timezone": self.timezone_name,
            "last_synchronized_at": (
                self.last_synchronized_at.isoformat() if self.last_synchronized_at else None
            ),
            "error_bound_seconds": round(self.error_bound_seconds, 1),
        }


class ClockTrust:
    """Evaluates clock trust and maintains the backwards-travel high-water mark.

    The mark is written atomically (temp file + rename — the ADR-0009
    pattern) so a power cut mid-write leaves the old mark or the new one,
    never a torn file. A torn mark would be indistinguishable from a reset
    clock and would enforce every zone forever.
    """

    def __init__(
        self,
        state_dir: Path,
        synchronized_marker: Path = _SYSTEMD_SYNCHRONIZED,
        clock_state_file: Path = _SYSTEMD_CLOCK_STATE,
        drift_ppm: float = CRYSTAL_DRIFT_PPM,
    ) -> None:
        self._state_file = state_dir / STATE_FILE_NAME
        self._synchronized_marker = synchronized_marker
        self._clock_state_file = clock_state_file
        self._drift_ppm = drift_ppm

    # ------------------------------------------------------------- reading

    def status(self, now: datetime | None = None) -> ClockStatus:
        """Evaluate trust. Never raises: a failure here must not stop the box."""
        moment = now or datetime.now(tz=timezone.utc)
        zone_name = local_timezone_name()
        if zone_name is None:
            return ClockStatus(
                trusted=False,
                reason=(
                    "no local timezone is configured — a wall-clock schedule "
                    "cannot be evaluated without one"
                ),
            )

        high_water = self._read_high_water()
        if high_water is not None and moment < high_water:
            behind = (high_water - moment).total_seconds()
            return ClockStatus(
                trusted=False,
                reason=(
                    f"the clock is {behind / 3600:.1f}h behind the last time this box "
                    "recorded — it was reset, whatever it now reads"
                ),
                timezone_name=zone_name,
            )

        synchronized_at = self._last_synchronized_at()
        if synchronized_at is None:
            return ClockStatus(
                trusted=False,
                reason=(
                    "this box has never synchronized its clock with an external source; "
                    "a cold boot without a real-time clock starts at the system epoch"
                ),
                timezone_name=zone_name,
            )

        elapsed = max((moment - synchronized_at).total_seconds(), 0.0)
        return ClockStatus(
            trusted=True,
            reason=(
                f"synchronized {elapsed / 86400:.1f} days ago; local time may be off "
                f"by up to {elapsed * self._drift_ppm / 1e6 / 60:.1f} min"
            ),
            last_synchronized_at=synchronized_at,
            error_bound_seconds=elapsed * self._drift_ppm / 1e6,
            timezone_name=zone_name,
        )

    # ------------------------------------------------------------- writing

    def record(self, now: datetime | None = None) -> None:
        """Advance the high-water mark. Called periodically by the runtime.

        Only ever moves forward: recording a time earlier than the mark
        would erase the very evidence that the clock went backwards.
        """
        moment = now or datetime.now(tz=timezone.utc)
        existing = self._read_high_water()
        if existing is not None and moment <= existing:
            return
        payload = json.dumps({"high_water": moment.isoformat()}, indent=2)
        temp = self._state_file.with_suffix(".json.tmp")
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self._state_file)
        except OSError:
            logger.exception("could not record the clock high-water mark; box continues")
            temp.unlink(missing_ok=True)

    # ------------------------------------------------------------ internals

    def _read_high_water(self) -> datetime | None:
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            return _parse_utc(raw["high_water"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _last_synchronized_at(self) -> datetime | None:
        """When an external source last set this clock, as far as we can tell.

        Both paths are filesystem timestamps written by systemd; the marker
        proves synchronization happened, the persisted state survives a
        reboot. The later of the two is the most recent trustworthy moment.
        """
        candidates = [
            _modified_at(path)
            for path in (self._synchronized_marker, self._clock_state_file)
            if path.exists()
        ]
        known = [moment for moment in candidates if moment is not None]
        return max(known) if known else None


def _modified_at(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def local_timezone_name() -> str | None:
    """The box's configured local zone, or None when it has none.

    A box left at UTC by default is indistinguishable from a box genuinely
    in UTC, so this trusts an explicit /etc/timezone or TZ over the libc
    fallback: guessing here would silently misplace every window.
    """
    if name := os.environ.get("TZ"):
        return name
    for path in (Path("/etc/timezone"),):
        try:
            if text := path.read_text(encoding="utf-8").strip():
                return text
        except OSError:
            continue
    link = Path("/etc/localtime")
    try:
        if link.is_symlink():
            target = os.readlink(link)
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return None


ClockStatusProvider = Callable[[], ClockStatus]
"""How a detector asks about the clock without owning one (a port, so tests
state the clock instead of simulating an operating system)."""
