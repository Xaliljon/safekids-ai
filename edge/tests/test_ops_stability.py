"""Pilot stability: recovery from real failure modes + accelerated 24h soak.

The 24-hour requirement is verified by simulation: a fake clock drives the
watchdog through a full day of supervision cycles with injected failures,
and real components (camera service, notification engine) are exercised
through genuine disconnects and backlog bursts at real speed but compressed
duration. A wall-clock field soak is what the pilot itself provides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from camera_fakes import ScriptedStreamFactory, make_camera, wait_until
from event_fixtures import make_safety_incident

from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.retry import RetryPolicy
from guardian_edge.domain.errors import CameraConnectionError
from guardian_edge.domain.incident import Severity
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel
from guardian_edge.ops.watchdog import ServiceWatchdog, SupervisedService

pytestmark = pytest.mark.stress


class TestCameraDisconnectRecovery:
    def test_frames_keep_flowing_after_repeated_disconnects(self) -> None:
        received: list[object] = []
        factory = ScriptedStreamFactory(
            scripts=[
                ["frame", "frame", CameraConnectionError("cam-1: link dropped")],
                ["frame", CameraConnectionError("cam-1: link dropped again")],
            ]
        )
        service = CameraService(stream_factory=factory, frame_consumer=received.append)
        service.add_camera(make_camera())
        service.start()
        try:
            assert wait_until(lambda: len(received) >= 20, timeout=10.0)
            assert factory.open_calls >= 3  # reconnected after each disconnect
        finally:
            service.stop()

    def test_network_interruption_then_recovery(self) -> None:
        received: list[object] = []
        factory = ScriptedStreamFactory(fail_first=5)  # network down: connects fail
        service = CameraService(
            stream_factory=factory,
            frame_consumer=received.append,
            # accelerated backoff: the simulated outage lasts ~0.5s, not 30s
            retry_policy=RetryPolicy(
                initial_delay_seconds=0.05, multiplier=1.5, max_delay_seconds=0.2
            ),
        )
        service.add_camera(make_camera())
        service.start()
        try:
            assert wait_until(lambda: len(received) >= 5, timeout=15.0)
        finally:
            service.stop()


class TestNotificationBacklog:
    def test_burst_of_incidents_all_reach_the_outbox(self, tmp_path: Path) -> None:
        engine = NotificationEngine(LocalPushChannel(tmp_path))
        engine.start()
        try:
            for step in range(200):
                engine(make_safety_incident(severity=Severity.CRITICAL, step=step))
            assert wait_until(lambda: engine.metrics().delivered == 200, timeout=30.0), (
                f"delivered only {engine.metrics().delivered}/200"
            )
            assert engine.metrics().failed_permanently == 0
        finally:
            engine.stop()


class FlakyEveryN:
    """Service that dies every ``every`` health checks; restart heals it."""

    def __init__(self, every: int) -> None:
        self._every = every
        self._checks = 0
        self._healthy = True
        self.restarts = 0

    def is_healthy(self) -> bool:
        self._checks += 1
        if self._checks % self._every == 0:
            self._healthy = False
        return self._healthy

    def restart(self) -> None:
        self.restarts += 1
        self._healthy = True


class TestTwentyFourHourSimulation:
    def test_simulated_day_of_supervision_with_injected_failures(self) -> None:
        """24h at one supervision pass per 5s = 17_280 passes, simulated clock."""
        now = {"t": 0.0}
        vision = FlakyEveryN(every=1000)  # a crash roughly every 83 minutes
        notifications = FlakyEveryN(every=4000)
        stable = FlakyEveryN(every=10**9)  # never fails
        watchdog = ServiceWatchdog(
            [
                SupervisedService("vision", vision.is_healthy, vision.restart),
                SupervisedService("notifications", notifications.is_healthy, notifications.restart),
                SupervisedService("device-api", stable.is_healthy, stable.restart),
            ],
            max_restarts_in_window=3,
            window_seconds=300.0,
            clock=lambda: now["t"],
        )
        passes = 24 * 60 * 60 // 5
        for _ in range(passes):
            watchdog.check_once()
            now["t"] += 5.0

        stats = watchdog.stats()
        assert stats.checks == passes
        assert stats.restarts["vision"] == vision.restarts > 0
        assert stats.restarts["notifications"] == notifications.restarts > 0
        assert "device-api" not in stats.restarts
        # isolated failures, restarts spread out: no lingering crash-loop warning
        assert watchdog.warnings() == {}

    def test_simulated_crash_loop_warns_but_survives_the_day(self) -> None:
        now = {"t": 0.0}
        always_dead = SupervisedService("broken", lambda: False, lambda: None)
        watchdog = ServiceWatchdog(
            [always_dead],
            max_restarts_in_window=3,
            window_seconds=300.0,
            clock=lambda: now["t"],
        )
        passes = 24 * 60 * 60 // 5
        for _ in range(passes):
            watchdog.check_once()
            now["t"] += 5.0
        stats = watchdog.stats()
        assert stats.checks == passes  # never stopped supervising
        assert stats.restarts["broken"] == passes  # never gave up either
        assert "keeps failing" in watchdog.warnings()["broken"]
