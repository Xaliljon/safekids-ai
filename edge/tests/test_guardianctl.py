"""guardianctl: the operator CLI end to end (no interactive prompts)."""

from __future__ import annotations

import json
import socket
import zipfile
from pathlib import Path

import pytest
import yaml

from guardian_edge import cli


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    return tmp_path / "box"


def run(home: Path, *argv: str) -> int:
    return cli.main(["--home", str(home), *argv])


class TestVersionAndCheck:
    def test_version_prints_package_version(self, home: Path, capsys) -> None:
        assert run(home, "version") == 0
        assert "guardian-edge 0." in capsys.readouterr().out

    def test_check_passes_on_dev_machine_and_writes_report(self, home: Path, capsys) -> None:
        assert run(home, "check") == 0
        assert "environment ready" in capsys.readouterr().out
        report = json.loads((home / "reports" / "install-report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True

    def test_no_command_prints_help(self, home: Path, capsys) -> None:
        assert cli.main(["--home", str(home)]) == 2
        assert "guardianctl" in capsys.readouterr().out


class TestCameraCommands:
    def test_add_camera_no_test_saves_config(self, home: Path, capsys) -> None:
        code = run(
            home,
            "add-camera",
            "--id",
            "room-1",
            "--name",
            "Room 1",
            "--url",
            "rtsp://192.0.2.10:554/stream",
            "--location",
            "east wing",
            "--no-test",
        )
        assert code == 0
        saved = yaml.safe_load((home / "config" / "cameras.yaml").read_text(encoding="utf-8"))
        assert saved["cameras"] == [
            {
                "id": "room-1",
                "name": "Room 1",
                "rtsp_url": "rtsp://192.0.2.10:554/stream",
                "location": "east wing",
            }
        ]

    def test_add_camera_rejects_duplicate_id(self, home: Path, capsys) -> None:
        run(home, "add-camera", "--id", "room-1", "--name", "A", "--url", "rtsp://x", "--no-test")
        code = run(
            home, "add-camera", "--id", "room-1", "--name", "B", "--url", "rtsp://y", "--no-test"
        )
        assert code == 1
        assert "already exists" in capsys.readouterr().err

    def test_add_camera_probes_and_rejects_dead_camera(
        self, home: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(cli, "_probe_camera_object", lambda camera: False)
        code = run(home, "add-camera", "--id", "room-1", "--name", "A", "--url", "rtsp://x")
        assert code == 1
        assert not (home / "config" / "cameras.yaml").exists()

    def test_test_camera_reports_probe_result(self, home: Path, monkeypatch, capsys) -> None:
        run(home, "add-camera", "--id", "room-1", "--name", "A", "--url", "rtsp://x", "--no-test")
        monkeypatch.setattr(cli, "_probe_camera_object", lambda camera: True)
        assert run(home, "test-camera", "room-1") == 0
        assert run(home, "test-camera", "no-such-camera") == 1

    def test_wizard_discovers_then_exits_without_adding(
        self, home: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(cli, "_discover", lambda: [])
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        assert run(home, "wizard") == 0
        assert "wizard finished" in capsys.readouterr().out

    def test_wizard_adds_camera_after_successful_probe(
        self, home: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(cli, "_discover", lambda: [])
        monkeypatch.setattr(cli, "_probe_entry", lambda entry: True)
        answers = iter(["y", "room-1", "Room 1", "rtsp://192.0.2.10/stream", "east", "n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        assert run(home, "wizard") == 0
        saved = yaml.safe_load((home / "config" / "cameras.yaml").read_text(encoding="utf-8"))
        assert saved["cameras"][0]["id"] == "room-1"


class TestDiagnoseHealthMetrics:
    def test_diagnose_writes_report_and_fails_on_fresh_box(self, home: Path, capsys) -> None:
        code = run(home, "diagnose", "--no-cameras")
        assert code == 1  # fresh box: no model, no device API
        out = capsys.readouterr().out
        assert "diagnostics found problems" in out
        assert (home / "reports" / "diagnostics-report.json").is_file()

    def test_health_unreachable_when_box_is_down(self, home: Path, capsys) -> None:
        with socket.create_server(("127.0.0.1", 0)) as listener:
            unused_port = listener.getsockname()[1]
        assert run(home, "health", "--port", str(unused_port)) == 1
        assert "unreachable" in capsys.readouterr().err

    def test_health_renders_running_box(self, home: Path, monkeypatch, capsys) -> None:
        payload = {
            "status": "ok",
            "version": "0.2.0",
            "host": {"cpu_percent": 10, "memory_percent": 40},
            "components": {"cameras": {"status": "ok"}},
            "warnings": {},
        }
        monkeypatch.setattr(cli, "_http_json", lambda url: payload)
        assert run(home, "health") == 0
        out = capsys.readouterr().out
        assert "status: ok" in out and "cameras" in out

    def test_metrics_export_writes_file(self, home: Path, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cli, "_http_json", lambda url: {"samples": [{"fps": 12.0}]})
        target = tmp_path / "exported.json"
        assert run(home, "metrics", "--export", str(target)) == 0
        assert json.loads(target.read_text(encoding="utf-8"))["samples"][0]["fps"] == 12.0


class TestBackupRestoreCommands:
    def test_backup_then_restore_roundtrip(self, home: Path, tmp_path: Path, capsys) -> None:
        run(home, "add-camera", "--id", "room-1", "--name", "A", "--url", "rtsp://x", "--no-test")
        archive = tmp_path / "backup.zip"
        assert run(home, "backup", str(archive)) == 0

        second_box = tmp_path / "second-box"
        assert cli.main(["--home", str(second_box), "restore", str(archive)]) == 0
        saved = yaml.safe_load((second_box / "config" / "cameras.yaml").read_text(encoding="utf-8"))
        assert saved["cameras"][0]["id"] == "room-1"

    def test_restore_rejects_garbage_archive(self, home: Path, tmp_path: Path, capsys) -> None:
        garbage = tmp_path / "garbage.zip"
        with zipfile.ZipFile(garbage, "w") as zf:
            zf.writestr("junk.txt", "junk")
        assert run(home, "restore", str(garbage)) == 1
        assert "not a Guardian backup" in capsys.readouterr().err
