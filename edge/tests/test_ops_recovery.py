"""Auto-recovery watchdog and configuration backup/restore."""

from __future__ import annotations

import threading
import zipfile
from pathlib import Path

import pytest

from guardian_edge.ops.backup import BackupError, create_backup, restore_backup
from guardian_edge.ops.paths import GuardianHome
from guardian_edge.ops.watchdog import ServiceWatchdog, SupervisedService, thread_alive


class FlakyService:
    """Health/restart double: unhealthy until restarted `fail_times` times."""

    def __init__(self, name: str = "svc", fail_times: int = 1) -> None:
        self.name = name
        self._fail_remaining = fail_times
        self.restarts = 0

    def is_healthy(self) -> bool:
        return self._fail_remaining <= 0

    def restart(self) -> None:
        self.restarts += 1
        self._fail_remaining -= 1

    def supervised(self) -> SupervisedService:
        return SupervisedService(self.name, self.is_healthy, self.restart)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestServiceWatchdog:
    def test_restarts_unhealthy_service(self) -> None:
        service = FlakyService(fail_times=1)
        watchdog = ServiceWatchdog([service.supervised()])
        watchdog.check_once()
        assert service.restarts == 1
        watchdog.check_once()  # healthy again — no further restart
        assert service.restarts == 1
        assert watchdog.warnings() == {}

    def test_crash_loop_raises_warning_but_keeps_retrying(self) -> None:
        clock = FakeClock()
        service = FlakyService(fail_times=100)
        watchdog = ServiceWatchdog(
            [service.supervised()],
            max_restarts_in_window=3,
            window_seconds=300.0,
            clock=clock,
        )
        for _ in range(5):
            watchdog.check_once()
            clock.now += 10
        assert service.restarts == 5  # never gives up
        assert "keeps failing" in watchdog.warnings()[service.name]

    def test_warning_clears_after_recovery(self) -> None:
        clock = FakeClock()
        service = FlakyService(fail_times=5)
        watchdog = ServiceWatchdog([service.supervised()], max_restarts_in_window=2, clock=clock)
        for _ in range(5):
            watchdog.check_once()
        assert watchdog.warnings()  # warned while crash-looping
        watchdog.check_once()  # healthy now
        assert watchdog.warnings() == {}

    def test_failing_restart_is_a_warning_not_a_crash(self) -> None:
        def bad_restart() -> None:
            raise RuntimeError("cannot restart")

        watchdog = ServiceWatchdog([SupervisedService("svc", lambda: False, bad_restart)])
        watchdog.check_once()  # must not raise
        assert "restart FAILED" in watchdog.warnings()["svc"]

    def test_crashing_health_probe_counts_as_unhealthy(self) -> None:
        def broken_probe() -> bool:
            raise RuntimeError("probe exploded")

        service = FlakyService()
        watchdog = ServiceWatchdog([SupervisedService("svc", broken_probe, service.restart)])
        watchdog.check_once()
        assert service.restarts == 1

    def test_stats_report_checks_and_restarts(self) -> None:
        service = FlakyService(fail_times=2)
        watchdog = ServiceWatchdog([service.supervised()])
        watchdog.check_once()
        watchdog.check_once()
        stats = watchdog.stats()
        assert stats.checks == 2
        assert stats.restarts == {"svc": 2}

    def test_thread_alive_probe(self) -> None:
        stop = threading.Event()
        worker = threading.Thread(target=stop.wait, name="probe-target", daemon=True)
        worker.start()
        try:
            assert thread_alive("probe-target")()
            assert not thread_alive("no-such-thread")()
        finally:
            stop.set()
            worker.join(timeout=5)


class TestBackupRestore:
    @pytest.fixture()
    def home(self, tmp_path: Path) -> GuardianHome:
        home = GuardianHome(root=tmp_path / "box").ensure()
        home.cameras_file.write_text("cameras:\n  - id: room-1\n", encoding="utf-8")
        (home.data_dir / "trusted_devices.json").write_text('{"devices": []}', encoding="utf-8")
        return home

    def test_roundtrip_restores_configuration(self, home: GuardianHome, tmp_path: Path) -> None:
        archive = tmp_path / "backup.zip"
        manifest = create_backup(home, archive, "2026-07-06T00:00:00+00:00")
        assert set(manifest["files"]) == {"config/cameras.yaml", "data/trusted_devices.json"}

        fresh = GuardianHome(root=tmp_path / "reimaged").ensure()
        restored = restore_backup(archive, fresh)
        assert set(restored) == set(manifest["files"])
        assert fresh.cameras_file.read_text(encoding="utf-8") == "cameras:\n  - id: room-1\n"

    def test_backup_excludes_models_logs_and_data(self, home: GuardianHome, tmp_path: Path) -> None:
        (home.models_dir / "model.onnx").write_bytes(b"weights")
        (home.logs_dir / "system.log").write_text("log line", encoding="utf-8")
        (home.outbox_dir / "notifications.jsonl").write_text("{}", encoding="utf-8")
        archive = tmp_path / "backup.zip"
        create_backup(home, archive, "2026-07-06T00:00:00+00:00")
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert not any("models" in n or "logs" in n or "outbox" in n for n in names)

    def test_restore_ignores_paths_outside_the_allowlist(
        self, home: GuardianHome, tmp_path: Path
    ) -> None:
        archive = tmp_path / "hostile.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("backup-manifest.json", '{"files": ["config/cameras.yaml"]}')
            zf.writestr("config/cameras.yaml", "cameras: []\n")
            zf.writestr("../../etc/evil", "pwned")
            zf.writestr("models/backdoor.onnx", "weights")
        fresh = GuardianHome(root=tmp_path / "victim").ensure()
        restored = restore_backup(archive, fresh)
        assert restored == ["config/cameras.yaml"]
        assert not (fresh.models_dir / "backdoor.onnx").exists()
        assert not (tmp_path / "etc" / "evil").exists()

    def test_restore_rejects_non_backup_archives(self, home: GuardianHome, tmp_path: Path) -> None:
        archive = tmp_path / "random.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("whatever.txt", "not a backup")
        with pytest.raises(BackupError, match="not a Guardian backup"):
            restore_backup(archive, home)

    def test_restore_rejects_missing_archive(self, home: GuardianHome, tmp_path: Path) -> None:
        with pytest.raises(BackupError, match="not found"):
            restore_backup(tmp_path / "missing.zip", home)

    def test_backup_of_a_fresh_box_is_valid_and_empty(self, tmp_path: Path) -> None:
        fresh = GuardianHome(root=tmp_path / "fresh").ensure()
        archive = tmp_path / "empty.zip"
        manifest = create_backup(fresh, archive, "2026-07-06T00:00:00+00:00")
        assert manifest["files"] == []
        assert restore_backup(archive, fresh) == []
