"""Safe-area zones: where safety ends, and when (ADR-0018).

A Zone is a polygon in normalized image coordinates (ADR-0006 §2) owned by
one camera, optionally limited to hours of the week. It is a *declaration*
a human made about a room — the domain's job is to hold it exactly and to
answer two questions without interpretation: is this point inside, and does
this zone exist at this moment.

Pure geometry and calendar arithmetic. Nothing here knows about tracks,
detectors, or alerts; a zone that decided anything would be a policy hiding
in a value object.

Known simplification (ADR-0018 Consequences): distances are normalized
units, so a horizontal margin and a vertical one are not the same physical
distance on a non-square frame. This is deliberate, of the same family as
the ground-proximity proxy in ADR-0012, and retired by the same future
work — real floor calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, unique
from math import hypot

from guardian_edge.domain.errors import VisionConfigurationError

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


@unique
class Weekday(IntEnum):
    """Matches ``datetime.weekday()`` so no translation table is needed."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True, slots=True)
class ZonePoint:
    """One polygon vertex in normalized image coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
            raise VisionConfigurationError(f"zone vertex out of frame: ({self.x}, {self.y})")


@dataclass(frozen=True, slots=True)
class ScheduleWindow:
    """Hours of the week during which a zone exists.

    Times are local wall clock, in minutes of day. ``start`` after ``end``
    means the window wraps past midnight — the same rule the mobile app's
    quiet hours already use, so operators meet one time model in this
    product, not two.
    """

    days: frozenset[Weekday]
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        if not self.days:
            raise VisionConfigurationError("a schedule window must name at least one day")
        for name, value in (("start", self.start_minute), ("end", self.end_minute)):
            if not (0 <= value < MINUTES_PER_DAY):
                raise VisionConfigurationError(f"{name} minute out of range: {value}")
        if self.start_minute == self.end_minute:
            raise VisionConfigurationError(
                "a zero-length window is never active; omit it, or say what it should cover"
            )

    @property
    def length_minutes(self) -> int:
        """Duration, counting a wrap past midnight as continuing."""
        return (self.end_minute - self.start_minute) % MINUTES_PER_DAY

    def _starts(self) -> tuple[int, ...]:
        """Week-minute at which this window opens on each of its days."""
        return tuple(int(day) * MINUTES_PER_DAY + self.start_minute for day in sorted(self.days))

    def contains(self, moment: datetime, margin_minutes: float = 0.0) -> bool:
        """Is ``moment`` (local wall clock) inside this window?

        ``margin_minutes`` widens both edges. It exists for one caller: a
        stale clock's error bound (ADR-0018 §7), which must make a zone
        active *earlier* and *later* than declared, never narrower.
        """
        if margin_minutes < 0:
            raise VisionConfigurationError("margin must not be negative — it may only widen")
        span = self.length_minutes + 2 * margin_minutes
        if span >= MINUTES_PER_WEEK:
            return True  # the widened window covers the whole week
        now = float(moment.weekday() * MINUTES_PER_DAY + moment.hour * 60 + moment.minute)
        now += moment.second / 60.0 + moment.microsecond / 60_000_000.0
        for start in self._starts():
            if (now - (start - margin_minutes)) % MINUTES_PER_WEEK < span:
                return True
        return False

    def describe(self) -> str:
        """Human-readable form for decision explanations (docs/04)."""
        days = "/".join(day.name[:3].title() for day in sorted(self.days))
        return f"{days} {_hhmm(self.start_minute)}–{_hhmm(self.end_minute)}"


@dataclass(frozen=True, slots=True)
class Zone:
    """A safe area on one camera: a child outside it is what we look for.

    V1 declares safe zones only (ADR-0018 §3). A zone with no
    ``active_windows`` exists at every moment.
    """

    zone_id: str
    camera_id: str
    name: str
    polygon: tuple[ZonePoint, ...]
    active_windows: tuple[ScheduleWindow, ...] = ()
    calibrated_at: datetime | None = None
    calibrated_width: int | None = None
    calibrated_height: int | None = None
    """Stream resolution the polygon was drawn against. Diagnostics compares
    it to the live stream: a changed resolution means the zone was drawn on
    a different picture than the one being watched (ADR-0018 Consequences)."""

    def __post_init__(self) -> None:
        if not self.zone_id.strip():
            raise VisionConfigurationError("zone_id must not be empty")
        if not self.camera_id.strip():
            raise VisionConfigurationError(f"zone '{self.zone_id}': camera_id must not be empty")
        if len(self.polygon) < 3:
            raise VisionConfigurationError(
                f"zone '{self.zone_id}': a polygon needs at least 3 vertices, "
                f"got {len(self.polygon)}"
            )
        if _area(self.polygon) == 0.0:
            raise VisionConfigurationError(
                f"zone '{self.zone_id}': vertices are collinear — this encloses nothing, "
                "and an empty safe area would put every child outside it"
            )

    # ------------------------------------------------------------ geometry

    def contains(self, x: float, y: float) -> bool:
        """Is the point inside the polygon? (ray casting, boundary counts as in)"""
        inside = False
        count = len(self.polygon)
        for index in range(count):
            a = self.polygon[index]
            b = self.polygon[(index + 1) % count]
            if _on_segment(x, y, a, b):
                return True  # exactly on the edge: never call that "outside"
            if (a.y > y) != (b.y > y):
                crossing_x = a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)
                if x < crossing_x:
                    inside = not inside
        return inside

    def distance_to_boundary(self, x: float, y: float) -> float:
        """Shortest distance from the point to the polygon's edge.

        Unsigned: the caller knows the side from :meth:`contains`. Used both
        as the hysteresis gate and as the "how far out" signal.
        """
        count = len(self.polygon)
        return min(
            _distance_to_segment(x, y, self.polygon[i], self.polygon[(i + 1) % count])
            for i in range(count)
        )

    # ------------------------------------------------------------ calendar

    def is_active_at(self, local_moment: datetime, margin_minutes: float = 0.0) -> bool:
        """Does this zone exist at this local wall-clock moment?

        A zone without windows always exists. Otherwise any one window is
        enough. ``margin_minutes`` only ever widens (ADR-0018 §7).
        """
        if not self.active_windows:
            return True
        return any(window.contains(local_moment, margin_minutes) for window in self.active_windows)

    def describe_schedule(self) -> str:
        """Why a zone was or was not active, in words a director can read."""
        if not self.active_windows:
            return "always"
        return ", ".join(window.describe() for window in self.active_windows)


# ------------------------------------------------------------------ helpers


def _hhmm(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _area(polygon: tuple[ZonePoint, ...]) -> float:
    """Twice the absolute shoelace area — zero when every vertex is collinear."""
    total = 0.0
    count = len(polygon)
    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        total += a.x * b.y - b.x * a.y
    return abs(total)


def _distance_to_segment(x: float, y: float, a: ZonePoint, b: ZonePoint) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return hypot(x - a.x, y - a.y)
    t = max(0.0, min(1.0, ((x - a.x) * dx + (y - a.y) * dy) / length_squared))
    return hypot(x - (a.x + t * dx), y - (a.y + t * dy))


def _on_segment(x: float, y: float, a: ZonePoint, b: ZonePoint, tolerance: float = 1e-9) -> bool:
    return _distance_to_segment(x, y, a, b) <= tolerance
