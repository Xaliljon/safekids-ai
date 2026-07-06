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
from pathlib import Path
from typing import Any

import guardian_edge
from guardian_edge.api.pairing import PairingManager
from guardian_edge.api.server import DeviceApiServer
from guardian_edge.application.camera_service import CameraService
from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.application.evidence.recorder import EvidenceRecorder
from guardian_edge.application.evidence.retention import EvidenceRetentionService
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.vision.pipeline import VisionPipeline
from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.domain.track import TrackingResult
from guardian_edge.infrastructure.camera.config import load_cameras
from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory
from guardian_edge.infrastructure.evidence.crypto import EvidenceVault
from guardian_edge.infrastructure.evidence.rings import FrameRingBuffer, TrackRingBuffer
from guardian_edge.infrastructure.evidence.store import FileSystemEvidenceStore
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel
from guardian_edge.infrastructure.tracking.bytetrack import ByteTracker
from guardian_edge.infrastructure.vision.yolox import create_yolox_detector
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

    risk_engine = RiskEngine(on_incident)
    event_engine = EventEngine([PotentialFallDetector()], risk_engine)

    def on_tracking(result: TrackingResult) -> None:
        tracking_gauge.observe(result)
        track_ring.on_tracking(result)
        event_engine(result)

    pipeline = VisionPipeline(
        detector=detector,
        detection_consumer=lambda result: None,
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
            "risk": lambda: {"status": "ok", **_risk_status(risk_engine)},
            "notifications": lambda: _notification_status(notification_engine),
            "evidence": lambda: {
                **evidence_recorder.stats(),
                "buffer": frame_ring.stats(),
            },
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


def _risk_status(risk_engine: RiskEngine) -> dict[str, Any]:
    stats = risk_engine.stats()
    return {"open_incidents": stats.open_incidents, "opened_total": stats.incidents_opened}


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
