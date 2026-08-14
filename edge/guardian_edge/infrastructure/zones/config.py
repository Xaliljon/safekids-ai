"""Safe-area zone configuration loading (YAML, ADR-0018 §12).

Zones live in their own file, not in ``cameras.yaml``: different lifecycle,
different author. Camera config holds credential references and is written
once by an integrator; zones and their hours are redrawn whenever furniture
or the daily routine moves, so the editor that touches them never opens the
file that references secrets.

Loading is strict. A malformed zone is refused loudly rather than silently
narrowed — a safe area that quietly lost a vertex still looks like a safe
area, and nobody finds out until a child is missed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.zone import ScheduleWindow, Weekday, Zone, ZonePoint

_DAY_NAMES = {
    "mon": Weekday.MONDAY,
    "tue": Weekday.TUESDAY,
    "wed": Weekday.WEDNESDAY,
    "thu": Weekday.THURSDAY,
    "fri": Weekday.FRIDAY,
    "sat": Weekday.SATURDAY,
    "sun": Weekday.SUNDAY,
}
_DAY_GROUPS = {
    "weekdays": frozenset(
        {
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
        }
    ),
    "weekend": frozenset({Weekday.SATURDAY, Weekday.SUNDAY}),
    "daily": frozenset(Weekday),
}


def load_zones(path: Path) -> list[Zone]:
    """Load and validate every zone from a YAML config file.

    Raises VisionConfigurationError on unreadable files, malformed YAML,
    missing keys, duplicate zone ids, or invalid geometry and schedules.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VisionConfigurationError(f"cannot read zone config '{path}': {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise VisionConfigurationError(f"zone config '{path}' is not valid YAML: {exc}") from exc

    if raw is None:
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("zones"), list):
        raise VisionConfigurationError(f"zone config '{path}' needs a top-level 'zones' list")

    zones: list[Zone] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw["zones"]):
        context = f"zone config '{path}': zones[{index}]"
        if not isinstance(entry, dict):
            raise VisionConfigurationError(f"{context} must be a mapping")
        zone = _parse_zone(entry, context=context)
        if zone.zone_id in seen:
            raise VisionConfigurationError(f"{context} duplicates zone id '{zone.zone_id}'")
        seen.add(zone.zone_id)
        zones.append(zone)
    return zones


def _parse_zone(entry: dict[str, Any], context: str) -> Zone:
    try:
        zone_id = str(entry["id"])
        camera_id = str(entry["camera_id"])
        polygon_raw = entry["polygon"]
    except KeyError as exc:
        raise VisionConfigurationError(f"{context} is missing key {exc}") from exc

    if not isinstance(polygon_raw, list):
        raise VisionConfigurationError(f"{context}: 'polygon' must be a list of [x, y] pairs")
    polygon = tuple(_parse_point(point, context=context) for point in polygon_raw)

    windows_raw = entry.get("active_windows", [])
    if not isinstance(windows_raw, list):
        raise VisionConfigurationError(f"{context}: 'active_windows' must be a list")
    windows = tuple(_parse_window(window, context=context) for window in windows_raw)

    calibrated = entry.get("calibrated_at")
    try:
        calibrated_at = datetime.fromisoformat(str(calibrated)) if calibrated else None
    except ValueError as exc:
        raise VisionConfigurationError(f"{context}: malformed 'calibrated_at': {exc}") from exc

    resolution = entry.get("calibrated_resolution")
    width, height = _parse_resolution(resolution, context=context)

    try:
        return Zone(
            zone_id=zone_id,
            camera_id=camera_id,
            name=str(entry.get("name", zone_id)),
            polygon=polygon,
            active_windows=windows,
            calibrated_at=calibrated_at,
            calibrated_width=width,
            calibrated_height=height,
        )
    except VisionConfigurationError as exc:
        raise VisionConfigurationError(f"{context}: {exc}") from exc


def _parse_point(raw: Any, context: str) -> ZonePoint:
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise VisionConfigurationError(
            f"{context}: each polygon vertex must be [x, y], got {raw!r}"
        )
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError) as exc:
        raise VisionConfigurationError(f"{context}: non-numeric vertex {raw!r}") from exc
    try:
        return ZonePoint(x=x, y=y)
    except VisionConfigurationError as exc:
        raise VisionConfigurationError(f"{context}: {exc}") from exc


def _parse_window(raw: Any, context: str) -> ScheduleWindow:
    if not isinstance(raw, dict):
        raise VisionConfigurationError(f"{context}: each active window must be a mapping")
    try:
        days = _parse_days(raw["days"], context=context)
        start = _parse_hhmm(raw["from"], field="from", context=context)
        end = _parse_hhmm(raw["to"], field="to", context=context)
    except KeyError as exc:
        raise VisionConfigurationError(f"{context}: window is missing key {exc}") from exc
    try:
        return ScheduleWindow(days=days, start_minute=start, end_minute=end)
    except VisionConfigurationError as exc:
        raise VisionConfigurationError(f"{context}: {exc}") from exc


def _parse_days(raw: Any, context: str) -> frozenset[Weekday]:
    names = [raw] if isinstance(raw, str) else raw
    if not isinstance(names, list) or not names:
        raise VisionConfigurationError(f"{context}: 'days' must name at least one day")
    days: set[Weekday] = set()
    for name in names:
        key = str(name).strip().lower()
        if key in _DAY_GROUPS:
            days |= _DAY_GROUPS[key]
        elif key[:3] in _DAY_NAMES:
            days.add(_DAY_NAMES[key[:3]])
        else:
            raise VisionConfigurationError(
                f"{context}: unknown day '{name}' — use mon..sun, weekdays, weekend, or daily"
            )
    return frozenset(days)


def _parse_hhmm(raw: Any, field: str, context: str) -> int:
    text = str(raw).strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise VisionConfigurationError(f"{context}: '{field}' must look like HH:MM, got '{text}'")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise VisionConfigurationError(f"{context}: non-numeric '{field}': '{text}'") from exc
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise VisionConfigurationError(f"{context}: '{field}' is not a real time: '{text}'")
    return hours * 60 + minutes


def _parse_resolution(raw: Any, context: str) -> tuple[int | None, int | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise VisionConfigurationError(
            f"{context}: 'calibrated_resolution' must be [width, height]"
        )
    try:
        return int(raw[0]), int(raw[1])
    except (TypeError, ValueError) as exc:
        raise VisionConfigurationError(f"{context}: non-numeric calibrated_resolution") from exc
