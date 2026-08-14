"""Diagnostics: every subsystem exercised, problems become recommendations."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from guardian_edge.ops.diagnostics import run_diagnostics
from guardian_edge.ops.paths import GuardianHome

CREATED = "2026-07-06T00:00:00+00:00"


@pytest.fixture()
def home(tmp_path: Path) -> GuardianHome:
    return GuardianHome(root=tmp_path / "box").ensure()


def check(report, name: str):  # noqa: ANN001, ANN201 - test helper
    return next(c for c in report.checks if c.name == name)


class TestRunDiagnostics:
    def test_report_carries_versions_and_timestamp(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED, probe_cameras=False)
        assert report.created_utc == CREATED
        assert report.system_version
        assert {c.name for c in report.checks} == {
            "cameras",
            "ai",
            "tracking",
            "notifications",
            "device_api",
            "clock",
        }

    def test_missing_cameras_yields_wizard_recommendation(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED)
        cameras = check(report, "cameras")
        assert not cameras.ok
        assert "wizard" in (cameras.recommendation or "")

    def test_missing_model_yields_installer_recommendation(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED, probe_cameras=False)
        ai = check(report, "ai")
        assert not ai.ok
        assert "installer" in (ai.recommendation or "")
        assert report.model_version is None

    def test_tracking_check_passes_on_synthetic_sequence(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED, probe_cameras=False)
        assert check(report, "tracking").ok

    def test_notification_check_delivers_synthetic_incident(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED, probe_cameras=False)
        assert check(report, "notifications").ok
        # the synthetic incident never pollutes the real outbox
        assert list(home.outbox_dir.iterdir()) == []

    def test_device_api_check_connects_to_listening_port(self, home: GuardianHome) -> None:
        with socket.create_server(("127.0.0.1", 0)) as listener:
            port = listener.getsockname()[1]
            report = run_diagnostics(
                home, created_utc=CREATED, device_api_port=port, probe_cameras=False
            )
        assert check(report, "device_api").ok

    def test_device_api_check_fails_with_restart_recommendation(self, home: GuardianHome) -> None:
        with socket.create_server(("127.0.0.1", 0)) as listener:
            unused_port = listener.getsockname()[1]
        report = run_diagnostics(
            home, created_utc=CREATED, device_api_port=unused_port, probe_cameras=False
        )
        device_api = check(report, "device_api")
        assert not device_api.ok
        assert "restart" in (device_api.recommendation or "").lower()

    def test_problems_and_recommendations_pair_up(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED)
        assert len(report.problems) == len(report.recommendations)
        assert report.problems  # fresh box: no cameras, no model, no API

    def test_save_writes_machine_readable_report(self, home: GuardianHome) -> None:
        report = run_diagnostics(home, created_utc=CREATED, probe_cameras=False)
        path = home.reports_dir / "diagnostics-report.json"
        report.save(path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["created_utc"] == CREATED
        assert saved["ok"] is False
        assert any(c["name"] == "tracking" and c["ok"] for c in saved["checks"])


class TestClockCheck:
    """A clock fault only matters if some zone declares hours — and even
    then it fails safe, so this reports it without ever being the reason a
    child goes unwatched (ADR-0018 §8)."""

    SCHEDULED_ZONE = """
zones:
  - id: nap
    camera_id: cam-1
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
    active_windows:
      - days: daily
        from: "13:00"
        to: "15:00"
"""

    ALWAYS_ON_ZONE = """
zones:
  - id: play
    camera_id: cam-1
    polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]
"""

    @pytest.fixture()
    def untrusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("guardian_edge.ops.clock.local_timezone_name", lambda: None)

    def test_an_untrusted_clock_with_scheduled_zones_is_a_problem(
        self, home: GuardianHome, untrusted: None
    ) -> None:
        home.zones_file.write_text(self.SCHEDULED_ZONE, encoding="utf-8")

        clock = check(run_diagnostics(home, created_utc=CREATED, probe_cameras=False), "clock")

        assert not clock.ok
        assert "cannot trust its local time" in (clock.problem or "")
        assert "1 scheduled zone(s)" in clock.detail
        assert clock.recommendation

    def test_an_untrusted_clock_with_no_scheduled_zones_is_not_a_problem(
        self, home: GuardianHome, untrusted: None
    ) -> None:
        home.zones_file.write_text(self.ALWAYS_ON_ZONE, encoding="utf-8")

        clock = check(run_diagnostics(home, created_utc=CREATED, probe_cameras=False), "clock")

        assert clock.ok, "nothing depends on the hour, so nothing is wrong"
        assert "nothing depends on it" in clock.detail

    def test_a_malformed_zone_file_does_not_break_the_clock_check(
        self, home: GuardianHome, untrusted: None
    ) -> None:
        home.zones_file.write_text("zones: [{id: broken}]", encoding="utf-8")

        clock = check(run_diagnostics(home, created_utc=CREATED, probe_cameras=False), "clock")

        assert clock.ok, "the zone config has its own error path; this one must not crash"
