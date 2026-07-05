"""Service watchdog: auto-recovery inside the process (ADR-0016).

Each supervised service exposes two callables — is_healthy and restart —
so recovery composes over public APIs and never reaches into internals.
A crashing service is restarted; a service that keeps dying raises a
health warning but the watchdog keeps trying: the system must continue
operating whenever possible. Process-level recovery (the whole runtime
dying) belongs to systemd (deploy/guardian-edge.service) — layered
recovery, each layer simple.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SupervisedService:
    name: str
    is_healthy: Callable[[], bool]
    restart: Callable[[], None]


@dataclass(frozen=True, slots=True)
class WatchdogStats:
    checks: int
    restarts: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, str] = field(default_factory=dict)


class ServiceWatchdog:
    """Periodically checks services and restarts the unhealthy ones."""

    def __init__(
        self,
        services: list[SupervisedService],
        check_interval_seconds: float = 5.0,
        max_restarts_in_window: int = 3,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._services = list(services)
        self._interval = check_interval_seconds
        self._max_restarts = max_restarts_in_window
        self._window = window_seconds
        self._clock = clock

        self._lock = threading.Lock()
        self._restart_times: dict[str, deque[float]] = {s.name: deque() for s in services}
        self._restart_totals: dict[str, int] = {}
        self._warnings: dict[str, str] = {}
        self._checks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_once(self) -> None:
        """One supervision pass; public for tests and diagnostics."""
        with self._lock:
            self._checks += 1
        for service in self._services:
            try:
                healthy = service.is_healthy()
            except Exception:
                healthy = False
            if healthy:
                with self._lock:
                    self._warnings.pop(service.name, None)
                continue
            self._recover(service)

    def warnings(self) -> dict[str, str]:
        with self._lock:
            return dict(self._warnings)

    def stats(self) -> WatchdogStats:
        with self._lock:
            return WatchdogStats(
                checks=self._checks,
                restarts=dict(self._restart_totals),
                warnings=dict(self._warnings),
            )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="service-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    # ---------------------------------------------------------- internals

    def _recover(self, service: SupervisedService) -> None:
        now = self._clock()
        with self._lock:
            times = self._restart_times[service.name]
            while times and now - times[0] > self._window:
                times.popleft()
            exhausted = len(times) >= self._max_restarts
        if exhausted:
            with self._lock:
                self._warnings[service.name] = (
                    f"{service.name} keeps failing "
                    f"(>{self._max_restarts} restarts in {self._window:.0f}s); still retrying"
                )
            logger.error("watchdog: %s", self._warnings[service.name])
        logger.warning("watchdog: %s unhealthy; restarting", service.name)
        try:
            service.restart()
            with self._lock:
                times.append(now)
                self._restart_totals[service.name] = self._restart_totals.get(service.name, 0) + 1
        except Exception:
            with self._lock:
                self._warnings[service.name] = f"{service.name} restart FAILED; will retry"
            logger.exception("watchdog: restart of %s failed", service.name)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                logger.exception("watchdog pass failed; watchdog continues")
            self._stop.wait(self._interval)


def thread_alive(thread_name: str) -> Callable[[], bool]:
    """Health probe: a named worker thread exists and is alive."""

    def probe() -> bool:
        return any(
            thread.name == thread_name and thread.is_alive() for thread in threading.enumerate()
        )

    return probe
