"""Zone config loading: strict, or a safe area quietly becomes wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.zone import Weekday
from guardian_edge.infrastructure.zones.config import load_zones

VALID = """
zones:
  - id: play-area
    camera_id: classroom-1-cam-1
    name: "Classroom 1 — play area"
    polygon: [[0.1, 0.3], [0.7, 0.3], [0.7, 0.9], [0.1, 0.9]]
    calibrated_at: "2026-08-14T09:30:00+05:00"
    calibrated_resolution: [1920, 1080]
  - id: nap-area
    camera_id: classroom-1-cam-1
    polygon: [[0.2, 0.4], [0.6, 0.4], [0.6, 0.9], [0.2, 0.9]]
    active_windows:
      - days: weekdays
        from: "13:00"
        to: "15:00"
"""


def one_zone(
    polygon: str = "[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]", window: str | None = None
) -> str:
    """A minimal single-zone document with one part deliberately varied."""
    text = f"zones:\n  - id: z\n    camera_id: c\n    polygon: {polygon}\n"
    if window is not None:
        text += f"    active_windows: [{window}]\n"
    return text


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "zones.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoading:
    def test_loads_geometry_schedules_and_calibration(self, tmp_path: Path) -> None:
        zones = load_zones(write(tmp_path, VALID))

        assert [zone.zone_id for zone in zones] == ["play-area", "nap-area"]
        play, nap = zones
        assert len(play.polygon) == 4
        assert play.calibrated_width == 1920
        assert play.active_windows == ()
        assert nap.name == "nap-area", "the id stands in when no name is given"
        assert nap.active_windows[0].days == frozenset(
            {
                Weekday.MONDAY,
                Weekday.TUESDAY,
                Weekday.WEDNESDAY,
                Weekday.THURSDAY,
                Weekday.FRIDAY,
            }
        )
        assert nap.active_windows[0].start_minute == 13 * 60

    def test_an_empty_file_is_no_zones_not_an_error(self, tmp_path: Path) -> None:
        assert load_zones(write(tmp_path, "")) == []

    @pytest.mark.parametrize(
        "days,expected",
        [
            ("daily", 7),
            ("weekend", 2),
            (["mon", "wed"], 2),
            (["monday", "tuesday"], 2),
        ],
    )
    def test_day_vocabularies(self, tmp_path: Path, days: object, expected: int) -> None:
        text = f"""
zones:
  - id: z
    camera_id: c
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
    active_windows:
      - days: {days}
        from: "09:00"
        to: "12:00"
"""
        zones = load_zones(write(tmp_path, text))
        assert len(zones[0].active_windows[0].days) == expected

    def test_an_overnight_window_is_accepted(self, tmp_path: Path) -> None:
        text = """
zones:
  - id: z
    camera_id: c
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
    active_windows:
      - days: daily
        from: "22:00"
        to: "06:00"
"""
        window = load_zones(write(tmp_path, text))[0].active_windows[0]
        assert window.length_minutes == 8 * 60


class TestRefusals:
    """A malformed zone must fail loudly. A safe area that quietly lost a
    vertex still looks like a safe area until a child is missed."""

    @pytest.mark.parametrize(
        "polygon,expected",
        [
            ("[[0.1, 0.1], [0.9, 0.1]]", "at least 3 vertices"),
            ("[[1.4, 0.1], [0.9, 0.1], [0.9, 0.9]]", "out of frame"),
            ("[[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]", "encloses nothing"),
            ("'not a list'", "must be a list"),
            ("[[0.1], [0.9, 0.1], [0.9, 0.9]]", r"must be \[x, y\]"),
        ],
    )
    def test_malformed_geometry_is_refused(
        self, tmp_path: Path, polygon: str, expected: str
    ) -> None:
        with pytest.raises(VisionConfigurationError, match=expected):
            load_zones(write(tmp_path, one_zone(polygon=polygon)))

    @pytest.mark.parametrize(
        "days,start,end,expected",
        [
            ("funday", "09:00", "12:00", "unknown day"),
            ("daily", "25:00", "12:00", "not a real time"),
            ("daily", "9am", "12:00", "must look like HH:MM"),
            ("daily", "09:00", "09:00", "zero-length"),
            ("[]", "09:00", "12:00", "at least one day"),
        ],
    )
    def test_malformed_schedules_are_refused(
        self, tmp_path: Path, days: str, start: str, end: str, expected: str
    ) -> None:
        text = one_zone(window=f'{{days: {days}, from: "{start}", to: "{end}"}}')
        with pytest.raises(VisionConfigurationError, match=expected):
            load_zones(write(tmp_path, text))

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("cameras: []", "needs a top-level 'zones' list"),
            ("zones:\n  - id: z\n", "missing key"),
            ("zones:\n  - not-a-mapping", "must be a mapping"),
        ],
    )
    def test_malformed_documents_are_refused(
        self, tmp_path: Path, text: str, expected: str
    ) -> None:
        with pytest.raises(VisionConfigurationError, match=expected):
            load_zones(write(tmp_path, text))

    def test_duplicate_zone_ids_are_refused(self, tmp_path: Path) -> None:
        text = """
zones:
  - id: same
    camera_id: c
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
  - id: same
    camera_id: c
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
"""
        with pytest.raises(VisionConfigurationError, match="duplicates zone id"):
            load_zones(write(tmp_path, text))

    def test_a_missing_file_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(VisionConfigurationError, match="cannot read zone config"):
            load_zones(tmp_path / "absent.yaml")

    def test_broken_yaml_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(VisionConfigurationError, match="not valid YAML"):
            load_zones(write(tmp_path, "zones: [\n  - id: ["))


class TestShippedExample:
    def test_the_example_config_actually_loads(self) -> None:
        """The file operators are told to copy must be valid, always."""
        example = Path(__file__).resolve().parents[1] / "config" / "zones.example.yaml"

        zones = load_zones(example)

        assert len(zones) == 3
        by_id = {zone.zone_id: zone for zone in zones}
        assert by_id["classroom-1-play-area"].active_windows == (), "documents an always-on zone"
        assert len(by_id["classroom-1-nap-area"].active_windows) == 1, "documents a schedule"
        assert len(by_id["playground-fenced-area"].active_windows) == 2, (
            "documents that a zone may have several windows in a day"
        )
