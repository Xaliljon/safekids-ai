"""GuardianHome layout, structured logging, install checks, camera probe."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from camera_fakes import ScriptedStreamFactory, make_camera

from guardian_edge.domain.errors import CameraConnectionError
from guardian_edge.ops.camera_probe import probe_camera
from guardian_edge.ops.install_check import installation_report, validate_environment
from guardian_edge.ops.logging_setup import SUBSYSTEM_LOGS, SYSTEM_LOG, configure_logging
from guardian_edge.ops.paths import GUARDIAN_HOME_ENV, GuardianHome


class TestGuardianHome:
    def test_from_env_reads_variable(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv(GUARDIAN_HOME_ENV, str(tmp_path / "box"))
        assert GuardianHome.from_env().root == tmp_path / "box"

    def test_from_env_defaults_to_home_guardian(self, monkeypatch) -> None:
        monkeypatch.delenv(GUARDIAN_HOME_ENV, raising=False)
        assert GuardianHome.from_env().root == Path.home() / "guardian"

    def test_ensure_creates_the_whole_tree_idempotently(self, tmp_path: Path) -> None:
        home = GuardianHome(root=tmp_path / "box").ensure().ensure()
        for path in (
            home.config_dir,
            home.models_dir,
            home.data_dir,
            home.outbox_dir,
            home.logs_dir,
            home.backups_dir,
            home.reports_dir,
        ):
            assert path.is_dir()
        assert home.cameras_file == home.config_dir / "cameras.yaml"


class TestStructuredLogging:
    def test_subsystems_route_to_their_own_json_files(self, tmp_path: Path) -> None:
        configure_logging(tmp_path, console=False)
        try:
            logging.getLogger("guardian_edge.infrastructure.tracking").warning("track lost")
            logging.getLogger("guardian_edge.api.server").info("client paired")
            logging.getLogger("some.other.module").info("hello")

            tracking = (tmp_path / "tracking.log").read_text(encoding="utf-8")
            entry = json.loads(tracking.strip().splitlines()[-1])
            assert entry["message"] == "track lost"
            assert entry["level"] == "WARNING"
            assert "ts" in entry

            device_api = (tmp_path / "device_api.log").read_text(encoding="utf-8")
            assert "client paired" in device_api
            # everything propagates to system.log for the complete picture
            system = (tmp_path / SYSTEM_LOG).read_text(encoding="utf-8")
            assert "track lost" in system and "hello" in system
        finally:
            configure_logging(tmp_path, console=False)  # reset handlers cleanly

    def test_reconfiguration_does_not_duplicate_handlers(self, tmp_path: Path) -> None:
        configure_logging(tmp_path, console=False)
        configure_logging(tmp_path, console=False)
        logging.getLogger("guardian_edge.application.risk").error("incident opened")
        lines = (tmp_path / "risk.log").read_text(encoding="utf-8").strip().splitlines()
        assert len([line for line in lines if "incident opened" in line]) == 1

    def test_every_required_subsystem_has_a_log_file(self) -> None:
        files = set(SUBSYSTEM_LOGS.values())
        assert {
            "vision.log",
            "tracking.log",
            "risk.log",
            "notifications.log",
            "device_api.log",
            "installer.log",
        } <= files


class TestInstallCheck:
    def test_dev_environment_passes_and_report_is_written(self, tmp_path: Path) -> None:
        results = validate_environment(tmp_path / "box")
        assert {r.name for r in results} == {
            "python_version",
            "dependencies",
            "disk_space",
            "memory",
            "network",
            "home_writable",
        }
        report_path = tmp_path / "reports" / "install-report.json"
        report = installation_report(results, report_path, "2026-07-06T00:00:00+00:00")
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        assert saved == report
        assert saved["created_utc"] == "2026-07-06T00:00:00+00:00"
        assert saved["guardian_edge_version"]
        assert all(check["ok"] for check in saved["checks"]), saved["checks"]
        assert saved["ok"] is True

    def test_unwritable_home_fails_the_check(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.mkdir(mode=0o500)
        results = {r.name: r for r in validate_environment(blocked / "guardian")}
        assert results["home_writable"].ok is False


class TestCameraProbe:
    def test_probe_measures_resolution_and_fps(self) -> None:
        result = probe_camera(ScriptedStreamFactory(), make_camera(), frames=5)
        assert result.ok
        assert result.frames_read == 5
        assert (result.width, result.height) == (2, 2)
        assert result.measured_fps is not None and result.measured_fps > 0

    def test_probe_reports_connection_failure(self) -> None:
        result = probe_camera(ScriptedStreamFactory(fail_first=1), make_camera(), frames=5)
        assert not result.ok
        assert result.frames_read == 0
        assert "simulated connect failure" in (result.error or "")

    def test_probe_closes_the_stream(self) -> None:
        factory = ScriptedStreamFactory()
        probe_camera(factory, make_camera(), frames=3)
        assert factory.streams[0].closed.is_set()

    def test_mid_stream_error_still_reports_what_was_measured(self) -> None:
        factory = ScriptedStreamFactory(
            scripts=[["frame", "frame", CameraConnectionError("cam-1: dropped")]]
        )
        result = probe_camera(factory, make_camera(), frames=10)
        assert result.ok  # partial read is still a working camera
        assert result.frames_read == 2
