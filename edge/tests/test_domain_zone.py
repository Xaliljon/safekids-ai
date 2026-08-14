"""Safe-area zone domain: geometry, schedules, and what it refuses (ADR-0018)."""

from __future__ import annotations

from datetime import datetime

import pytest

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.zone import (
    MINUTES_PER_WEEK,
    ScheduleWindow,
    Weekday,
    Zone,
    ZonePoint,
)

WEEKDAYS = frozenset({Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY})


def square(size: float = 0.5, origin: float = 0.2) -> tuple[ZonePoint, ...]:
    return (
        ZonePoint(origin, origin),
        ZonePoint(origin + size, origin),
        ZonePoint(origin + size, origin + size),
        ZonePoint(origin, origin + size),
    )


def make_zone(**overrides: object) -> Zone:
    fields: dict[str, object] = {
        "zone_id": "play-area",
        "camera_id": "cam-1",
        "name": "Play area",
        "polygon": square(),
    }
    fields.update(overrides)
    return Zone(**fields)  # type: ignore[arg-type]


def local(day: str, hour: int, minute: int = 0) -> datetime:
    """A local wall-clock moment in the week of 2026-08-10 (a Monday)."""
    offsets = {"mon": 10, "tue": 11, "wed": 12, "thu": 13, "fri": 14, "sat": 15, "sun": 16}
    return datetime(2026, 8, offsets[day], hour, minute)


class TestGeometry:
    def test_a_point_inside_the_polygon_is_inside(self) -> None:
        assert make_zone().contains(0.45, 0.45)

    @pytest.mark.parametrize("point", [(0.1, 0.45), (0.8, 0.45), (0.45, 0.1), (0.45, 0.8)])
    def test_points_beyond_each_edge_are_outside(self, point: tuple[float, float]) -> None:
        assert not make_zone().contains(*point)

    def test_a_point_exactly_on_the_edge_counts_as_inside(self) -> None:
        # A child standing on the line is not "out of the safe area": the
        # boundary belongs to the zone, and the hysteresis margin (not this
        # test) is what stops oscillation.
        assert make_zone().contains(0.2, 0.45)

    def test_distance_to_boundary_measures_how_far_out(self) -> None:
        zone = make_zone()  # square from 0.2 to 0.7
        assert zone.distance_to_boundary(0.8, 0.45) == pytest.approx(0.1)
        assert zone.distance_to_boundary(0.7, 0.45) == pytest.approx(0.0)

    def test_a_concave_polygon_is_handled(self) -> None:
        # L-shaped rooms are the reason rectangles were rejected (ADR-0018).
        zone = make_zone(
            polygon=(
                ZonePoint(0.1, 0.1),
                ZonePoint(0.9, 0.1),
                ZonePoint(0.9, 0.4),
                ZonePoint(0.4, 0.4),
                ZonePoint(0.4, 0.9),
                ZonePoint(0.1, 0.9),
            )
        )
        assert zone.contains(0.2, 0.8), "inside the tall arm of the L"
        assert not zone.contains(0.8, 0.8), "the notch is outside the zone"


class TestZoneValidation:
    def test_a_vertex_outside_the_frame_is_refused(self) -> None:
        with pytest.raises(VisionConfigurationError, match="out of frame"):
            ZonePoint(1.4, 0.5)

    def test_fewer_than_three_vertices_is_not_a_polygon(self) -> None:
        with pytest.raises(VisionConfigurationError, match="at least 3 vertices"):
            make_zone(polygon=(ZonePoint(0.1, 0.1), ZonePoint(0.5, 0.5)))

    def test_collinear_vertices_are_refused(self) -> None:
        # This encloses nothing, so every child would be "outside" it —
        # a silent way to alert on everyone, forever.
        with pytest.raises(VisionConfigurationError, match="encloses nothing"):
            make_zone(polygon=(ZonePoint(0.1, 0.1), ZonePoint(0.3, 0.3), ZonePoint(0.5, 0.5)))

    def test_identity_must_be_present(self) -> None:
        with pytest.raises(VisionConfigurationError, match="zone_id"):
            make_zone(zone_id="  ")
        with pytest.raises(VisionConfigurationError, match="camera_id"):
            make_zone(camera_id="")


class TestScheduleWindow:
    def test_a_plain_window_contains_its_own_hours(self) -> None:
        window = ScheduleWindow(days=WEEKDAYS, start_minute=13 * 60, end_minute=15 * 60)
        assert window.contains(local("mon", 14))
        assert not window.contains(local("mon", 12, 59))
        assert not window.contains(local("mon", 15, 1))

    def test_a_window_applies_only_to_its_days(self) -> None:
        window = ScheduleWindow(days=WEEKDAYS, start_minute=13 * 60, end_minute=15 * 60)
        assert window.contains(local("wed", 14))
        assert not window.contains(local("thu", 14)), "Thursday was not declared"

    def test_a_window_wraps_past_midnight(self) -> None:
        night = ScheduleWindow(
            days=frozenset({Weekday.MONDAY}), start_minute=22 * 60, end_minute=6 * 60
        )
        assert night.contains(local("mon", 23))
        assert night.contains(local("tue", 5)), "the window opened on Monday and runs on"
        assert not night.contains(local("tue", 7))

    def test_the_margin_widens_both_edges_never_narrows(self) -> None:
        window = ScheduleWindow(days=WEEKDAYS, start_minute=13 * 60, end_minute=15 * 60)
        assert not window.contains(local("mon", 12, 56))
        assert window.contains(local("mon", 12, 56), margin_minutes=5.0)
        assert window.contains(local("mon", 15, 4), margin_minutes=5.0)
        assert window.contains(local("mon", 14), margin_minutes=5.0), "still active inside"

    def test_a_margin_wider_than_the_week_is_always_active(self) -> None:
        window = ScheduleWindow(days=WEEKDAYS, start_minute=13 * 60, end_minute=15 * 60)
        assert window.contains(local("sun", 3), margin_minutes=MINUTES_PER_WEEK)

    def test_a_negative_margin_is_refused(self) -> None:
        # The margin exists for one caller, a stale clock, and that caller
        # may only ever widen. Narrowing would suppress a real exit.
        window = ScheduleWindow(days=WEEKDAYS, start_minute=13 * 60, end_minute=15 * 60)
        with pytest.raises(VisionConfigurationError, match="may only widen"):
            window.contains(local("mon", 14), margin_minutes=-1.0)

    def test_a_zero_length_window_is_refused(self) -> None:
        with pytest.raises(VisionConfigurationError, match="zero-length"):
            ScheduleWindow(days=WEEKDAYS, start_minute=600, end_minute=600)

    def test_a_window_without_days_is_refused(self) -> None:
        with pytest.raises(VisionConfigurationError, match="at least one day"):
            ScheduleWindow(days=frozenset(), start_minute=600, end_minute=700)

    def test_it_describes_itself_for_explanations(self) -> None:
        window = ScheduleWindow(
            days=frozenset({Weekday.MONDAY, Weekday.FRIDAY}),
            start_minute=13 * 60,
            end_minute=15 * 60 + 30,
        )
        assert window.describe() == "Mon/Fri 13:00–15:30"


class TestZoneSchedule:
    def test_a_zone_without_windows_always_exists(self) -> None:
        zone = make_zone()
        assert zone.is_active_at(local("sun", 3))
        assert zone.describe_schedule() == "always"

    def test_any_one_window_is_enough(self) -> None:
        zone = make_zone(
            active_windows=(
                ScheduleWindow(days=WEEKDAYS, start_minute=9 * 60, end_minute=12 * 60),
                ScheduleWindow(days=WEEKDAYS, start_minute=16 * 60, end_minute=18 * 60),
            )
        )
        assert zone.is_active_at(local("mon", 10))
        assert zone.is_active_at(local("mon", 17))
        assert not zone.is_active_at(local("mon", 14)), "the gap between windows"

    def test_the_schedule_reads_back_in_words(self) -> None:
        zone = make_zone(
            active_windows=(
                ScheduleWindow(
                    days=frozenset({Weekday.MONDAY}), start_minute=13 * 60, end_minute=15 * 60
                ),
            )
        )
        assert "Mon 13:00–15:00" in zone.describe_schedule()
