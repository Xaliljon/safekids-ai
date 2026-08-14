"""System diagnostics: exercise every subsystem and report (ADR-0016).

Each check runs the *real* component against synthetic input through its
public API. The report is machine-readable and carries recommendations an
operator can act on without a developer.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

import guardian_edge
from guardian_edge.domain.detection import BoundingBox, Detection, DetectionResult, ModelDescriptor
from guardian_edge.domain.errors import GuardianEdgeError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.infrastructure.zones.config import load_zones
from guardian_edge.ops.camera_probe import probe_camera
from guardian_edge.ops.clock import ClockTrust
from guardian_edge.ops.paths import GuardianHome

_PROBE_FRAMES = 15
_TRACK_FRAMES = 10


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    ok: bool
    detail: str
    problem: str | None = None
    recommendation: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    created_utc: str
    system_version: str
    model_version: str | None
    checks: list[DiagnosticCheck] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        return [check.problem for check in self.checks if check.problem]

    @property
    def recommendations(self) -> list[str]:
        return [check.recommendation for check in self.checks if check.recommendation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_utc": self.created_utc,
            "system_version": self.system_version,
            "model_version": self.model_version,
            "ok": all(check.ok for check in self.checks),
            "checks": [asdict(check) for check in self.checks],
            "problems": self.problems,
            "recommendations": self.recommendations,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def run_diagnostics(
    home: GuardianHome,
    created_utc: str,
    device_api_port: int = 8787,
    probe_cameras: bool = True,
) -> DiagnosticReport:
    checks: list[DiagnosticCheck] = []
    model_version: str | None = None

    checks.append(_check_cameras(home) if probe_cameras else _skip("cameras", "probe disabled"))
    ai_check, model_version = _check_ai(home)
    checks.append(ai_check)
    checks.append(_check_tracking())
    checks.append(_check_notifications(home))
    checks.append(_check_device_api(device_api_port))
    checks.append(_check_clock(home))

    return DiagnosticReport(
        created_utc=created_utc,
        system_version=guardian_edge.__version__,
        model_version=model_version,
        checks=checks,
    )


def _skip(name: str, detail: str) -> DiagnosticCheck:
    return DiagnosticCheck(name=name, ok=True, detail=f"skipped: {detail}")


def _check_cameras(home: GuardianHome) -> DiagnosticCheck:
    from guardian_edge.infrastructure.camera.config import load_cameras
    from guardian_edge.infrastructure.camera.rtsp_stream import OpenCvRtspStreamFactory

    if not home.cameras_file.is_file():
        return DiagnosticCheck(
            name="cameras",
            ok=False,
            detail="no camera configuration",
            problem="no cameras are configured",
            recommendation="run: guardianctl wizard",
        )
    try:
        cameras = load_cameras(home.cameras_file)
    except GuardianEdgeError as exc:
        return DiagnosticCheck(
            name="cameras",
            ok=False,
            detail=str(exc),
            problem="camera configuration is invalid",
            recommendation="fix config/cameras.yaml or re-run the wizard",
        )
    factory = OpenCvRtspStreamFactory()
    failures = []
    details = []
    for camera in cameras:
        result = probe_camera(factory, camera, frames=_PROBE_FRAMES)
        if result.ok:
            details.append(
                f"{camera.camera_id}: {result.width}x{result.height} @ {result.measured_fps} fps"
            )
        else:
            failures.append(f"{camera.camera_id}: {result.error}")
    ok = not failures
    return DiagnosticCheck(
        name="cameras",
        ok=ok,
        detail="; ".join(details + failures) or "no cameras configured",
        problem=None if ok else f"{len(failures)} camera(s) unreachable",
        recommendation=None if ok else "check camera power, cabling and RTSP credentials",
    )


def _check_ai(home: GuardianHome) -> tuple[DiagnosticCheck, str | None]:
    from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry
    from guardian_edge.infrastructure.vision.yolox import create_yolox_detector

    try:
        detector = create_yolox_detector(FileSystemModelRegistry(home.models_dir))
    except GuardianEdgeError as exc:
        return (
            DiagnosticCheck(
                name="ai",
                ok=False,
                detail=str(exc),
                problem="detection model unavailable",
                recommendation="re-run the installer (model install step)",
            ),
            None,
        )
    try:
        frame = _synthetic_frame(0)
        result = detector.detect(frame)
        version = f"{result.model.name} v{result.model.version}"
        return (
            DiagnosticCheck(
                name="ai", ok=True, detail=f"{version}, inference {result.inference_ms:.1f} ms"
            ),
            version,
        )
    finally:
        detector.close()


def _check_tracking() -> DiagnosticCheck:
    from guardian_edge.infrastructure.tracking.bytetrack import ByteTrackConfig, ByteTracker

    tracker = ByteTracker(ByteTrackConfig(confirm_after=2))
    confirmed = 0
    for step in range(_TRACK_FRAMES):
        result = tracker.update(_synthetic_detections(step))
        confirmed = len(result.confirmed())
    ok = confirmed == 1
    return DiagnosticCheck(
        name="tracking",
        ok=ok,
        detail=f"synthetic sequence produced {confirmed} confirmed track(s)",
        problem=None if ok else "tracker failed to confirm a synthetic track",
        recommendation=None if ok else "collect logs/tracking.log and contact support",
    )


def _check_notifications(home: GuardianHome) -> DiagnosticCheck:
    import tempfile

    from guardian_edge.application.notifications.engine import NotificationEngine
    from guardian_edge.infrastructure.notifications.local_push import LocalPushChannel

    with tempfile.TemporaryDirectory(dir=str(home.data_dir), prefix="diag-") as spool:
        channel = LocalPushChannel(Path(spool))
        engine = NotificationEngine(channel)
        engine.start()
        try:
            engine(_synthetic_incident())
            deadline = 50
            while engine.metrics().delivered < 1 and deadline > 0:
                time.sleep(0.05)
                deadline -= 1
            delivered = engine.metrics().delivered == 1
        finally:
            engine.stop()
    return DiagnosticCheck(
        name="notifications",
        ok=delivered,
        detail="synthetic incident delivered to the local outbox"
        if delivered
        else "delivery did not complete",
        problem=None if delivered else "notification delivery failing",
        recommendation=None if delivered else "check disk space and logs/notifications.log",
    )


def _check_clock(home: GuardianHome) -> DiagnosticCheck:
    """Is local wall-clock time trustworthy? (ADR-0018 §8)

    Only zone schedules depend on this, and they fail safe — an untrusted
    clock enforces every zone regardless of hours. So this reports a real
    problem without ever being the reason a child goes unwatched, and the
    box is only *degraded* when a zone actually declares hours.
    """
    status = ClockTrust(home.data_dir).status()
    scheduled = _scheduled_zone_count(home)
    if status.trusted:
        return DiagnosticCheck(name="clock", ok=True, detail=status.reason)
    if scheduled == 0:
        return DiagnosticCheck(
            name="clock",
            ok=True,
            detail=f"{status.reason} — no zone declares hours, so nothing depends on it",
        )
    return DiagnosticCheck(
        name="clock",
        ok=False,
        detail=f"{status.reason}; {scheduled} scheduled zone(s) are enforced around the clock",
        problem="the box cannot trust its local time",
        recommendation=(
            "set the timezone and let the box reach an NTP server, then re-run "
            "diagnose; until then scheduled safe areas alert outside their hours"
        ),
    )


def _scheduled_zone_count(home: GuardianHome) -> int:
    if not home.zones_file.is_file():
        return 0
    try:
        return sum(1 for zone in load_zones(home.zones_file) if zone.active_windows)
    except GuardianEdgeError:
        return 0  # the zone check itself reports a malformed file


def _check_device_api(port: int) -> DiagnosticCheck:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return DiagnosticCheck(name="device_api", ok=True, detail=f"listening on :{port}")
    except OSError:
        return DiagnosticCheck(
            name="device_api",
            ok=False,
            detail=f"nothing listening on :{port}",
            problem="device API is not running",
            recommendation="restart the box service (see PILOT_GUIDE.md, Restart Procedure)",
        )


# ------------------------------------------------------- synthetic inputs


def _synthetic_frame(sequence: int) -> Frame:
    return Frame(
        camera_id="diagnostics",
        sequence=sequence,
        captured_at=datetime.now(tz=timezone.utc),
        width=640,
        height=480,
        data=np.zeros((480, 640, 3), dtype=np.uint8),
    )


def _synthetic_detections(step: int) -> DetectionResult:
    frame = _synthetic_frame(step)
    detection = Detection(
        detection_id=uuid4(),
        frame_id=frame.frame_id,
        camera_id=frame.camera_id,
        captured_at=frame.captured_at,
        correlation_id=frame.correlation_id,
        label="person",
        confidence=0.9,
        box=BoundingBox(x=0.4 + step * 0.01, y=0.4, width=0.2, height=0.3),
    )
    return DetectionResult(
        camera_id=frame.camera_id,
        frame_id=frame.frame_id,
        frame_sequence=step,
        captured_at=frame.captured_at,
        correlation_id=frame.correlation_id,
        detections=(detection,),
        model=ModelDescriptor(name="diagnostics", version="1.0.0"),
        inference_ms=0.0,
    )


def _synthetic_incident() -> SafetyIncident:
    from guardian_edge.domain.event import CandidateEvent, CandidateEventType, EventSignal
    from guardian_edge.domain.incident import Severity
    from guardian_edge.domain.track import Track, TrackState

    frame = _synthetic_frame(1)
    detection = _synthetic_detections(1).detections[0]
    track = Track(
        track_id=uuid4(),
        display_id=1,
        camera_id=frame.camera_id,
        state=TrackState.CONFIRMED,
        label="person",
        confidence=0.9,
        box=detection.box,
        last_detection=detection,
        hits=3,
        age_frames=3,
        frames_since_update=0,
        first_seen_at=frame.captured_at,
        last_seen_at=frame.captured_at,
    )
    event = CandidateEvent(
        event_id=uuid4(),
        event_type=CandidateEventType.POTENTIAL_FALL,
        camera_id=frame.camera_id,
        observed_at=frame.captured_at,
        frame_id=detection.frame_id,
        correlation_id=detection.correlation_id,
        confidence=0.9,
        track=track,
        signals=(EventSignal("diagnostics", 1.0, "synthetic check"),),
    )
    return SafetyIncident(
        incident_id=uuid4(),
        incident_type=CandidateEventType.POTENTIAL_FALL,
        camera_id=frame.camera_id,
        track_id=track.track_id,
        track_display_id=1,
        severity=Severity.CRITICAL,
        risk_confidence=0.9,
        opened_at=frame.captured_at,
        last_event_at=frame.captured_at + timedelta(seconds=1),
        correlation_id=detection.correlation_id,
        events=(event,),
        summary="diagnostics synthetic incident on track #1",
    )
