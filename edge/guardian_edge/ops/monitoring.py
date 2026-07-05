"""Health and performance monitoring (ADR-0016).

SystemHealthCollector assembles a machine-readable snapshot from component
providers (each a plain callable returning a dict — composition, never
introspection) plus host metrics via psutil. HealthServer exposes it as
JSON on localhost-adjacent LAN. PerformanceMonitor samples continuously
and exports metric history.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import psutil

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_PORT = 8790
StatusProvider = Callable[[], dict[str, Any]]

_START_MONO = time.monotonic()


def host_metrics(disk_path: Path) -> dict[str, Any]:
    """CPU, RAM, disk, temperature, uptime — never raises."""
    metrics: dict[str, Any] = {"uptime_seconds": round(time.monotonic() - _START_MONO, 1)}
    try:
        metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        metrics["memory_percent"] = memory.percent
        metrics["memory_used_mb"] = round(memory.used / (1 << 20))
        usage = shutil.disk_usage(disk_path)
        metrics["disk_percent"] = round(100 * usage.used / usage.total, 1)
        metrics["disk_free_gb"] = round(usage.free / (1 << 30), 2)
        metrics["temperature_c"] = _temperature()
    except Exception:
        logger.exception("host metric collection failed; partial metrics returned")
    return metrics


def _temperature() -> float | None:
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is None:
        return None  # not supported on this platform (e.g. macOS dev machines)
    try:
        readings = sensors()
    except Exception:
        return None
    for entries in readings.values():
        for entry in entries:
            if entry.current:
                return round(float(entry.current), 1)
    return None


class SystemHealthCollector:
    """Aggregates component + host health into one machine-readable dict."""

    def __init__(
        self,
        providers: Mapping[str, StatusProvider],
        warnings: Callable[[], dict[str, str]] | None = None,
        disk_path: Path = Path("/"),
        version: str = "",
    ) -> None:
        self._providers = dict(providers)
        self._warnings = warnings or (lambda: {})
        self._disk_path = disk_path
        self._version = version

    def snapshot(self) -> dict[str, Any]:
        components: dict[str, Any] = {}
        for name, provider in self._providers.items():
            try:
                components[name] = provider()
            except Exception as exc:
                components[name] = {"status": "error", "detail": str(exc)}
        warnings = self._warnings()
        statuses = [c.get("status") for c in components.values()]
        overall = "ok"
        if warnings or "error" in statuses:
            overall = "error" if "error" in statuses else "warning"
        elif "degraded" in statuses:
            overall = "degraded"
        return {
            "status": overall,
            "version": self._version,
            "components": components,
            "host": host_metrics(self._disk_path),
            "warnings": warnings,
        }


class HealthServer:
    """GET /health and GET /metrics as JSON (machine-readable reports)."""

    def __init__(
        self,
        collector: SystemHealthCollector,
        metrics_provider: Callable[[], dict[str, Any]],
        host: str = "0.0.0.0",  # noqa: S104 - reachable on the LAN like the device API (ADR-0016)
        port: int = DEFAULT_HEALTH_PORT,
    ) -> None:
        self._collector = collector
        self._metrics_provider = metrics_provider
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        if self._server is not None:
            return
        collector, metrics_provider = self._collector, self._metrics_provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                if self.path.startswith("/health"):
                    body = collector.snapshot()
                elif self.path.startswith("/metrics"):
                    body = metrics_provider()
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                payload = json.dumps(body).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="health-server", daemon=True
        )
        self._thread.start()
        logger.info("health server up on :%d (/health, /metrics)", self._port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class PerformanceMonitor:
    """Periodic sampling of host + pipeline metrics with bounded history."""

    def __init__(
        self,
        gauges: Mapping[str, Callable[[], float | None]],
        disk_path: Path = Path("/"),
        interval_seconds: float = 15.0,
        history: int = 5760,  # 24h at 15s
    ) -> None:
        self._gauges = dict(gauges)
        self._disk_path = disk_path
        self._interval = interval_seconds
        self._samples: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample_once(self) -> dict[str, Any]:
        sample = host_metrics(self._disk_path)
        for name, gauge in self._gauges.items():
            try:
                sample[name] = gauge()
            except Exception:
                sample[name] = None
        with self._lock:
            self._samples.append(sample)
        return sample

    def latest(self) -> dict[str, Any]:
        with self._lock:
            if self._samples:
                return dict(self._samples[-1])
        return self.sample_once()

    def export(self, path: Path) -> int:
        """Write the collected history as JSON; returns sample count."""
        with self._lock:
            samples = list(self._samples)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"samples": samples}, indent=2), encoding="utf-8")
        return len(samples)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="performance-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:
                logger.exception("performance sampling failed; monitor continues")
            self._stop.wait(self._interval)
