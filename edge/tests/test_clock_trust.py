"""Clock trust: the three categorical faults, and the bound (ADR-0018 §6-8)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from guardian_edge.ops.clock import CRYSTAL_DRIFT_PPM, ClockStatus, ClockTrust

NOW = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _configured_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests are about the other two faults; give them a timezone."""
    monkeypatch.setenv("TZ", "Asia/Tashkent")


def synchronized_marker(tmp_path: Path, when: datetime) -> Path:
    marker = tmp_path / "synchronized"
    marker.touch()
    os.utime(marker, (when.timestamp(), when.timestamp()))
    return marker


def make_trust(tmp_path: Path, synchronized_at: datetime | None = NOW) -> ClockTrust:
    marker = (
        synchronized_marker(tmp_path, synchronized_at)
        if synchronized_at is not None
        else tmp_path / "never-synchronized"
    )
    return ClockTrust(
        tmp_path,
        synchronized_marker=marker,
        clock_state_file=tmp_path / "absent-clock-state",
    )


class TestCategoricalFaults:
    def test_a_box_that_never_synchronized_is_not_trusted(self, tmp_path: Path) -> None:
        status = make_trust(tmp_path, synchronized_at=None).status(NOW)
        assert not status.trusted
        assert "never synchronized" in status.reason

    def test_a_clock_that_ran_backwards_is_not_trusted(self, tmp_path: Path) -> None:
        trust = make_trust(tmp_path)
        trust.record(NOW)

        status = trust.status(NOW - timedelta(hours=6))

        assert not status.trusted
        assert "behind the last time this box recorded" in status.reason

    def test_a_box_without_a_timezone_is_not_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TZ", raising=False)
        monkeypatch.setattr("guardian_edge.ops.clock._local_timezone_name", lambda: None)

        status = make_trust(tmp_path).status(NOW)

        assert not status.trusted
        assert "timezone" in status.reason


class TestStalenessIsNotAFault:
    def test_a_freshly_synchronized_clock_is_trusted_with_a_tiny_bound(
        self, tmp_path: Path
    ) -> None:
        status = make_trust(tmp_path).status(NOW)
        assert status.trusted
        assert status.error_bound_seconds == pytest.approx(0.0, abs=1.0)

    def test_a_month_offline_is_still_trusted(self, tmp_path: Path) -> None:
        # The whole point of ADR-0018 §6: drift is not the risk. A month
        # costs ~2 minutes against windows measured in hours, and
        # distrusting that would disable safe-area enforcement for nothing.
        status = make_trust(tmp_path, synchronized_at=NOW - timedelta(days=30)).status(NOW)

        assert status.trusted
        assert status.error_bound_minutes == pytest.approx(2.16, abs=0.05)

    def test_the_bound_matches_the_declared_drift(self, tmp_path: Path) -> None:
        elapsed = timedelta(days=70)
        status = make_trust(tmp_path, synchronized_at=NOW - elapsed).status(NOW)

        expected = elapsed.total_seconds() * CRYSTAL_DRIFT_PPM / 1e6
        assert status.error_bound_seconds == pytest.approx(expected)
        assert status.error_bound_minutes == pytest.approx(
            5.04, abs=0.05
        ), "the ADR's worked example: 70 days offline widens each edge by ~5 minutes"


class TestHighWaterMark:
    def test_the_mark_only_moves_forward(self, tmp_path: Path) -> None:
        trust = make_trust(tmp_path)
        trust.record(NOW)
        trust.record(NOW - timedelta(days=1))  # a reset clock must not erase the evidence

        assert not trust.status(NOW - timedelta(days=1)).trusted

    def test_the_mark_survives_a_new_instance(self, tmp_path: Path) -> None:
        make_trust(tmp_path).record(NOW)
        assert not make_trust(tmp_path).status(NOW - timedelta(hours=2)).trusted

    def test_a_corrupt_mark_does_not_crash_the_box(self, tmp_path: Path) -> None:
        (tmp_path / "clock.json").write_text("{not json", encoding="utf-8")
        # Unreadable is treated as absent: the other two faults still apply,
        # and a parse error must never take the runtime down.
        assert make_trust(tmp_path).status(NOW).trusted

    def test_an_unwritable_state_dir_is_survivable(self, tmp_path: Path) -> None:
        trust = ClockTrust(tmp_path / "nested" / "denied")
        trust.record(NOW)  # must not raise


class TestReporting:
    def test_status_serializes_for_health(self, tmp_path: Path) -> None:
        payload = make_trust(tmp_path).status(NOW).to_dict()
        assert payload["status"] == "ok"
        assert payload["trusted"] is True
        assert payload["timezone"] == "Asia/Tashkent"
        assert payload["reason"]

    def test_an_untrusted_clock_reports_degraded_with_a_reason(self) -> None:
        payload = ClockStatus(trusted=False, reason="no timezone").to_dict()
        assert payload["status"] == "degraded"
        assert payload["reason"] == "no timezone"
