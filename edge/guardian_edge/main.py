"""Guardian Edge Box — the production entrypoint (ADR-0016).

Wires the frozen engines into one supervised runtime:

    cameras -> vision pipeline (YOLOX + ByteTrack) -> event engine
      -> risk engine -> notification engine -> local push + device API
    + health server, performance monitor, service watchdog

Usage:
    GUARDIAN_HOME=~/guardian uv run python -m guardian_edge.main

Everything composes through existing public APIs; no engine is modified.
Process-level recovery belongs to systemd (deploy/guardian-edge.service);
this supervisor owns in-process recovery via the watchdog.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import guardian_edge
from guardian_edge.api.pairing import PairingManager
from guardian_edge.api.server import DeviceApiServer
from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.debugging.recorder import RiskDebugRecorder
from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.application.events.ports import CandidateDetector
from guardian_edge.application.events.zone import ZoneExitDetector
from guardian_edge.application.evidence.recorder import EvidenceRecorder
from guardian_edge.application.evidence.retention import EvidenceRetentionService
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.domain.track import TrackingResult
from guardian_edge.domain.zone import Zone
from guardian_edge.infrastructure.camera.config import load_cameras
from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.rings import FrameRingBuffer, TrackRingBuffer
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel
from guardian_edge.infrastructure.tracking.bytetrack import ByteTracker
from guardian_edge.infrastructure.vision.yolox import create_yolox_detector
from guardian_edge.infrastructure.zones.config import load_zones
from guardian_edge.ops.clock import ClockTrust
from guardian_edge.ops.logging_setup import configure_logging
from guardian_edge.ops.monitoring import HealthServer, PerformanceMonitor, SystemHealthCollector
from guardian_edge.ops.paths import GuardianHome
from guardian_edge.ops.watchdog import ServiceWatchdog, SupervisedService, thread_alive

logger = logging.getLogger(__name__)


class _TrackingLatencyGauge:
    """Composes over the TrackConsumer seam to observe tracking latency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_ms: float | None = None

    def observe(self, result: TrackingResult) -> None:
        with self._lock:
            self._last_ms = result.tracking_ms

    def value(self) -> float | None:
        with self._lock:
            return self._last_ms


@dataclass
class Runtime:
    """Everything the box runs, with one start/stop."""

    camera_service: CameraService
    pipeline: VisionPipeline
    notification_engine: NotificationEngine
    device_api: DeviceApiServer
    health_server: HealthServer
    monitor: PerformanceMonitor
    watchdog: ServiceWatchdog
    risk_engine: RiskEngine
    frame_ring: FrameRingBuffer
    evidence_recorder: EvidenceRecorder
    evidence_retention: EvidenceRetentionService

    def start(self) -> None:
        self.frame_ring.start()
        self.evidence_recorder.start()
        self.evidence_retention.start()
        self.notification_engine.start()
        self.pipeline.start()
        self.camera_service.start()
        self.device_api.start()
        self.health_server.start()
        self.monitor.start()
        self.watchdog.start()
        logger.info("guardian edge %s running", guardian_edge.__version__)

    def stop(self) -> None:
        self.watchdog.stop()
        self.monitor.stop()
        self.health_server.stop()
        self.device_api.stop()
        self.camera_service.stop()
        self.pipeline.stop()
        self.notification_engine.stop()
        self.evidence_retention.stop()
        self.evidence_recorder.stop()
        self.frame_ring.stop()
        logger.info("guardian edge stopped cleanly")


def build_runtime(
    home: GuardianHome,
    api_port: int = 8787,
    ws_port: int = 8788,
    health_port: int = 8790,
    model_name: str = "yolox-tiny",
) -> Runtime:
    """Compose the full box from a Guardian home directory."""
    home.ensure()

    detector = create_yolox_detector(
        FileSystemModelRegistry(home.models_dir), model_name=model_name
    )
    tracking_gauge = _TrackingLatencyGauge()
    channel = LocalPushChannel(home.outbox_dir)
    notification_engine = NotificationEngine(channel)

    # Explainable risk debugging (Sprint 10.1): every decision leaves a
    # trail in logs/risk-debug.log and every incident a replayable
    # reports/<incident-id>/timeline.json. Observation only.
    debug_recorder = RiskDebugRecorder(home.reports_dir)
    channel.subscribe(debug_recorder.on_notification)

    # Evidence platform (ADR-0017): rings + recorder attach through the
    # existing consumer seams; no frozen engine knows evidence exists.
    frame_ring = FrameRingBuffer()
    track_ring = TrackRingBuffer()
    evidence_store = FileSystemEvidenceStore(
        home.evidence_dir, EvidenceVault(home.evidence_key_file)
    )
    evidence_recorder = EvidenceRecorder(frame_ring, track_ring, evidence_store)
    evidence_retention = EvidenceRetentionService(evidence_store)

    def on_incident(incident: SafetyIncident) -> None:
        notification_engine(incident)  # alert first — evidence never delays it
        evidence_recorder.on_incident(incident)
        debug_recorder.on_incident(incident)

    risk_engine = RiskEngine(on_incident, observer=debug_recorder.on_risk_decision)

    # Safe-area zones (ADR-0018). The clock is in the safety path now: a
    # schedule may only ever suppress, so ClockTrust decides whether the
    # zone detector may honour hours at all.
    clock = ClockTrust(home.data_dir)
    clock.record()
    detectors: list[CandidateDetector] = [
        PotentialFallDetector(observer=debug_recorder.on_evaluation)
    ]
    zones = load_zones(home.zones_file) if home.zones_file.is_file() else []
    if zones:
        detectors.append(
            ZoneExitDetector(
                zones,
                clock.status,
                observer=debug_recorder.on_evaluation,
                local_zone=_configured_zone(clock),
            )
        )
        logger.info("watching %d safe-area zone(s)", len(zones))
    else:
        logger.info("no safe-area zones configured — zone-exit detection is off")

    event_engine = EventEngine(
        detectors,
        risk_engine,
        evaluation_observer=debug_recorder.on_evaluation,
    )

    def on_tracking(result: TrackingResult) -> None:
        tracking_gauge.observe(result)
        track_ring.on_tracking(result)
        event_engine(result)

    pipeline = VisionPipeline(
        detector=detector,
        detection_consumer=lambda result: debug_recorder.on_detections(len(result.detections)),
        tracker=ByteTracker(),
        track_consumer=on_tracking,
    )

    def on_frame(frame: Frame) -> None:
        frame_ring.on_frame(frame)  # constant-time enqueue, never blocks
        pipeline.on_frame(frame)

    camera_service = CameraService(
        stream_factory=OpenCvRtspStreamFactory(),
        frame_consumer=on_frame,
    )
    camera_count = 0
    if home.cameras_file.is_file():
        for camera in load_cameras(home.cameras_file):
            camera_service.add_camera(camera)
            camera_count += 1
    if camera_count == 0:
        logger.warning("no cameras configured — run 'guardianctl wizard' to add cameras")

    pairing = PairingManager(home.data_dir)
    device_api = DeviceApiServer(
        risk_engine=risk_engine,
        push_channel=channel,
        outbox_dir=home.outbox_dir,
        pairing=pairing,
        api_port=api_port,
        ws_port=ws_port,
        evidence_store=evidence_store,
    )

    watchdog = ServiceWatchdog(
        [
            SupervisedService(
                "vision-pipeline", thread_alive("vision-pipeline"), _restart(pipeline)
            ),
            SupervisedService(
                "notification-engine",
                thread_alive("notification-engine"),
                _restart(notification_engine),
            ),
            SupervisedService("health-server", thread_alive("health-server"), lambda: None),
            SupervisedService(
                "evidence-recorder",
                thread_alive("evidence-recorder"),
                _restart(evidence_recorder),
            ),
            SupervisedService(
                "evidence-frame-ring",
                thread_alive("evidence-frame-ring"),
                _restart(frame_ring),
            ),
        ]
    )

    def pipeline_fps() -> float | None:
        stats = pipeline.stats()
        return round(sum(s.frames_per_second for s in stats.values()), 2) if stats else None

    collector = SystemHealthCollector(
        providers={
            "cameras": lambda: _camera_status(camera_service),
            "inference": lambda: _pipeline_status(pipeline),
            "tracking": lambda: {"status": "ok", "last_latency_ms": tracking_gauge.value()},
            "risk": lambda: _risk_status(risk_engine),
            "notifications": lambda: _notification_status(notification_engine),
            "evidence": lambda: {
                **evidence_recorder.stats(),
                "buffer": frame_ring.stats(),
            },
            "events": lambda: {"status": "ok", **_event_status(event_engine)},
            "clock": lambda: _clock_status(clock, zones),
            "zones": lambda: _zone_status(zones, clock),
            "debug": debug_recorder.counters,
        },
        warnings=watchdog.warnings,
        disk_path=home.root,
        version=guardian_edge.__version__,
    )
    monitor = PerformanceMonitor(
        gauges={
            "inference_fps": pipeline_fps,
            "tracking_latency_ms": tracking_gauge.value,
            "notification_mean_delivery_ms": (
                lambda: notification_engine.metrics().mean_time_to_delivered_ms
            ),
        },
        disk_path=home.root,
    )
    health_server = HealthServer(collector, monitor.latest, port=health_port)

    return Runtime(
        camera_service=camera_service,
        pipeline=pipeline,
        notification_engine=notification_engine,
        device_api=device_api,
        health_server=health_server,
        monitor=monitor,
        watchdog=watchdog,
        risk_engine=risk_engine,
        frame_ring=frame_ring,
        evidence_recorder=evidence_recorder,
        evidence_retention=evidence_retention,
    )


def _restart(service: Any) -> Callable[[], None]:
    def restart() -> None:
        service.stop()
        service.start()

    return restart


def _camera_status(camera_service: CameraService) -> dict[str, Any]:
    report = camera_service.health_report()
    if not report:
        return {"status": "degraded", "detail": "no cameras configured"}
    unhealthy = [cid for cid, health in report.items() if health.status.value == "unhealthy"]
    return {
        "status": "error" if unhealthy else "ok",
        "cameras": {cid: health.status.value for cid, health in report.items()},
        "fps": {cid: health.frames_per_second for cid, health in report.items()},
    }


def _pipeline_status(pipeline: VisionPipeline) -> dict[str, Any]:
    stats = pipeline.stats()
    return {
        "status": "ok",
        "cameras": {
            cid: {
                "fps": s.frames_per_second,
                "processed": s.frames_processed,
                "dropped": s.frames_dropped,
                "detector_errors": s.detector_errors,
                "tracker_errors": s.tracker_errors,
            }
            for cid, s in stats.items()
        },
    }


def _event_status(event_engine: EventEngine) -> dict[str, Any]:
    stats = event_engine.stats()
    return {
        "frames_observed": stats.frames_observed,
        "tracks_evaluated": stats.tracks_evaluated,
        "events_emitted": dict(stats.events_emitted),
        "detector_errors": stats.detector_errors,
    }


def _clock_status(clock: ClockTrust, zones: list[Zone]) -> dict[str, Any]:
    """Clock trust, degraded only when something actually depends on it.

    The same rule `guardianctl diagnose` applies: an untrusted clock on a
    box whose zones declare no hours changes nothing, and a box that
    reports degraded forever is a box whose health nobody reads. Found by
    running the demo on a Mac, where there is no systemd timesync
    interface, so provenance is unknowable and every box said degraded.
    """
    status = clock.status()
    payload = status.to_dict()
    if status.trusted or not any(zone.active_windows for zone in zones):
        payload["status"] = "ok"
    return payload


def _configured_zone(clock: ClockTrust) -> tzinfo | None:
    """The box's declared timezone, resolved once at startup.

    The clock reports which zone the operator configured; using it here is
    what makes that provenance real rather than decorative. An unresolvable
    name falls back to the system zone — and the clock has already reported
    the box as untrusted, which enforces every schedule anyway.
    """
    name = clock.status().timezone_name
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("configured timezone '%s' is not in the tz database", name)
        return None


def _zone_status(zones: list[Zone], clock: ClockTrust) -> dict[str, Any]:
    """Which safe areas exist, and whether their hours are being honoured."""
    if not zones:
        return {"status": "ok", "configured": 0}
    status = clock.status()
    scheduled = [zone for zone in zones if zone.active_windows]
    return {
        # An untrusted clock does not break zone detection — it enforces
        # every schedule around the clock. That is a degraded box, not a
        # healthy one, and only the operator can fix the cause.
        "status": "ok" if status.trusted or not scheduled else "degraded",
        "configured": len(zones),
        "scheduled": len(scheduled),
        "schedules_enforced_ignoring_hours": bool(scheduled) and not status.trusted,
        "cameras": sorted({zone.camera_id for zone in zones}),
    }


def _risk_status(risk_engine: RiskEngine) -> dict[str, Any]:
    stats = risk_engine.stats()
    return {
        # Dropped candidates mean a detector is running that no policy covers
        # — the box looks healthy while producing no alerts for that event
        # type. That is a degraded box, and it must say so.
        "status": "degraded" if stats.ignored_no_policy else "ok",
        "open_incidents": stats.open_incidents,
        "opened_total": stats.incidents_opened,
        "candidates_received": stats.candidates_received,
        "suppressed_low_confidence": stats.suppressed_low_confidence,
        "suppressed_after_dismissal": stats.suppressed_after_dismissal,
        "ignored_no_policy": stats.ignored_no_policy,
        "events_correlated": stats.events_correlated,
        "escalations": stats.escalations,
    }


def _notification_status(engine: NotificationEngine) -> dict[str, Any]:
    metrics = engine.metrics()
    status = "ok" if metrics.failed_permanently == 0 else "degraded"
    return {
        "status": status,
        "delivered": metrics.delivered,
        "failed": metrics.failed_permanently,
        "queue": metrics.queue_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=None, help="Guardian home (default: $GUARDIAN_HOME)")
    args = parser.parse_args(argv)
    home = (
        GuardianHome.from_env()
        if args.home is None
        else GuardianHome(root=Path(args.home).expanduser())
    )
    home.ensure()
    configure_logging(home.logs_dir)
    try:
        runtime = build_runtime(home)
    except GuardianEdgeError as exc:
        logger.error("startup failed: %s — run 'guardianctl diagnose' for details", exc)
        return 1
    runtime.start()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    runtime.monitor.export(home.reports_dir / "metrics-latest.json")
    runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
