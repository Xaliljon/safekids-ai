"""System health collector, health HTTP server, performance monitor."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from guardian_edge.ops.monitoring import (
    HealthServer,
    PerformanceMonitor,
    SystemHealthCollector,
    host_metrics,
)


class TestHostMetrics:
    def test_reports_cpu_memory_disk_uptime(self, tmp_path: Path) -> None:
        metrics = host_metrics(tmp_path)
        assert metrics["uptime_seconds"] >= 0
        assert 0 <= metrics["memory_percent"] <= 100
        assert 0 <= metrics["disk_percent"] <= 100
        assert metrics["disk_free_gb"] > 0
        assert "cpu_percent" in metrics and "temperature_c" in metrics


class TestSystemHealthCollector:
    def test_aggregates_component_statuses(self, tmp_path: Path) -> None:
        collector = SystemHealthCollector(
            providers={
                "cameras": lambda: {"status": "ok"},
                "notifications": lambda: {"status": "ok", "queue": 0},
            },
            disk_path=tmp_path,
            version="0.2.0",
        )
        snapshot = collector.snapshot()
        assert snapshot["status"] == "ok"
        assert snapshot["version"] == "0.2.0"
        assert snapshot["components"]["notifications"]["queue"] == 0
        assert "host" in snapshot

    def test_degraded_component_degrades_overall_status(self, tmp_path: Path) -> None:
        collector = SystemHealthCollector(
            providers={"cameras": lambda: {"status": "degraded"}}, disk_path=tmp_path
        )
        assert collector.snapshot()["status"] == "degraded"

    def test_error_component_wins_over_degraded(self, tmp_path: Path) -> None:
        collector = SystemHealthCollector(
            providers={
                "cameras": lambda: {"status": "degraded"},
                "inference": lambda: {"status": "error"},
            },
            disk_path=tmp_path,
        )
        assert collector.snapshot()["status"] == "error"

    def test_watchdog_warnings_surface_as_warning_status(self, tmp_path: Path) -> None:
        collector = SystemHealthCollector(
            providers={"cameras": lambda: {"status": "ok"}},
            warnings=lambda: {"vision-pipeline": "keeps failing"},
            disk_path=tmp_path,
        )
        snapshot = collector.snapshot()
        assert snapshot["status"] == "warning"
        assert snapshot["warnings"]["vision-pipeline"] == "keeps failing"

    def test_crashing_provider_becomes_error_never_raises(self, tmp_path: Path) -> None:
        def broken() -> dict[str, str]:
            raise RuntimeError("component exploded")

        collector = SystemHealthCollector(providers={"risk": broken}, disk_path=tmp_path)
        snapshot = collector.snapshot()
        assert snapshot["components"]["risk"]["status"] == "error"
        assert snapshot["status"] == "error"


class TestHealthServer:
    def test_serves_health_and_metrics_json(self, tmp_path: Path) -> None:
        collector = SystemHealthCollector(
            providers={"cameras": lambda: {"status": "ok"}}, disk_path=tmp_path, version="0.2.0"
        )
        server = HealthServer(collector, lambda: {"inference_fps": 12.5}, port=0)
        server.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.port}/health", timeout=5) as response:
                health = json.loads(response.read())
            assert health["status"] == "ok"
            assert health["components"]["cameras"]["status"] == "ok"
            with urlopen(f"http://127.0.0.1:{server.port}/metrics", timeout=5) as response:
                metrics = json.loads(response.read())
            assert metrics["inference_fps"] == 12.5
        finally:
            server.stop()

    def test_unknown_path_is_404(self, tmp_path: Path) -> None:
        server = HealthServer(
            SystemHealthCollector(providers={}, disk_path=tmp_path), lambda: {}, port=0
        )
        server.start()
        try:
            import urllib.error

            try:
                urlopen(f"http://127.0.0.1:{server.port}/nope", timeout=5)
                raise AssertionError("expected HTTP 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
        finally:
            server.stop()


class TestPerformanceMonitor:
    def test_sample_includes_gauges_and_host_metrics(self, tmp_path: Path) -> None:
        monitor = PerformanceMonitor(
            gauges={"inference_fps": lambda: 14.2, "tracking_latency_ms": lambda: None},
            disk_path=tmp_path,
        )
        sample = monitor.sample_once()
        assert sample["inference_fps"] == 14.2
        assert sample["tracking_latency_ms"] is None
        assert "memory_percent" in sample

    def test_crashing_gauge_records_none(self, tmp_path: Path) -> None:
        def broken() -> float:
            raise RuntimeError("gauge exploded")

        monitor = PerformanceMonitor(gauges={"fps": broken}, disk_path=tmp_path)
        assert monitor.sample_once()["fps"] is None

    def test_history_is_bounded(self, tmp_path: Path) -> None:
        monitor = PerformanceMonitor(gauges={}, disk_path=tmp_path, history=3)
        for _ in range(5):
            monitor.sample_once()
        export_path = tmp_path / "metrics.json"
        assert monitor.export(export_path) == 3

    def test_export_writes_machine_readable_history(self, tmp_path: Path) -> None:
        monitor = PerformanceMonitor(gauges={"fps": lambda: 9.9}, disk_path=tmp_path)
        monitor.sample_once()
        export_path = tmp_path / "reports" / "metrics.json"
        count = monitor.export(export_path)
        saved = json.loads(export_path.read_text(encoding="utf-8"))
        assert count == 1
        assert saved["samples"][0]["fps"] == 9.9

    def test_latest_samples_lazily_when_empty(self, tmp_path: Path) -> None:
        monitor = PerformanceMonitor(gauges={"fps": lambda: 1.0}, disk_path=tmp_path)
        assert monitor.latest()["fps"] == 1.0
