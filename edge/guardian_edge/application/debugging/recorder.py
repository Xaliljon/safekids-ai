"""RiskDebugRecorder: every decision logged, every incident replayable.

The recorder is the single sink for decision explanations:

- every TrackEvaluation and RiskDecision becomes one readable line in
  ``logs/risk-debug.log`` (rotated JSON-lines like every subsystem log),
- recent evaluations are kept per track so an incident can be replayed,
- every incident gets ``reports/<incident-id>/timeline.json`` — frames,
  detections, track, signals, decisions, risk and the notification —
  everything needed to understand WHY, after the fact,
- counters feed ``guardianctl debug``'s pipeline funnel.

Explanation only: the recorder observes; it never talks back to a single
engine.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from guardian_edge.application.debugging.explain import RiskDecision, TrackEvaluation
from guardian_edge.domain.incident import SafetyIncident

logger = logging.getLogger(__name__)  # -> logs/risk-debug.log (ops mapping)

_RING_SIZE = 240  # ~24s of decisions per track at 10 fps
TIMELINE_FILE = "timeline.json"


class RiskDebugRecorder:
    """Observer for fall/event/risk decisions; writes the debug trail."""

    def __init__(self, reports_dir: Path, ring_size: int = _RING_SIZE) -> None:
        self._reports_dir = reports_dir
        self._ring_size = ring_size
        self._lock = threading.Lock()
        self._evaluations: dict[UUID, deque[TrackEvaluation]] = {}
        self._risk_decisions: dict[UUID, list[RiskDecision]] = {}  # by incident
        self._incidents: dict[UUID, SafetyIncident] = {}
        self._notifications: dict[UUID, dict[str, Any]] = {}  # by incident
        self._detections = 0
        self._counters: dict[str, int] = {}
        self._rejections: dict[str, int] = {}
        self._risk_outcomes: dict[str, int] = {}

    # -------------------------------------------------------- observers

    def on_detections(self, count: int) -> None:
        """DetectionConsumer-side counter (wired in the supervisor)."""
        with self._lock:
            self._detections += count

    def on_evaluation(self, evaluation: TrackEvaluation) -> None:
        """TrackEvaluationObserver: one decision about one track, one frame."""
        with self._lock:
            ring = self._evaluations.setdefault(evaluation.track_id, deque(maxlen=self._ring_size))
            ring.append(evaluation)
            self._counters["evaluations"] = self._counters.get("evaluations", 0) + 1
            if evaluation.outcome == "candidate":
                self._counters["candidates"] = self._counters.get("candidates", 0) + 1
            else:
                key = _reason_key(evaluation.reason)
                self._rejections[key] = self._rejections.get(key, 0) + 1
        logger.info("%s", _format_evaluation(evaluation))

    def on_risk_decision(self, decision: RiskDecision) -> None:
        """RiskDecisionObserver: what the risk engine did with a candidate."""
        with self._lock:
            self._risk_outcomes[decision.outcome] = self._risk_outcomes.get(decision.outcome, 0) + 1
            if decision.incident_id is not None:
                self._risk_decisions.setdefault(decision.incident_id, []).append(decision)
        logger.info("%s", _format_risk(decision))
        if decision.incident_id is not None:
            self._export_timeline(decision.incident_id)

    def on_incident(self, incident: SafetyIncident) -> None:
        """IncidentConsumer seam: keep the snapshot for the timeline."""
        with self._lock:
            self._incidents[incident.incident_id] = incident
        self._export_timeline(incident.incident_id)

    def on_notification(self, payload: dict[str, Any]) -> None:
        """LocalPushChannel subscriber: the delivered notification payload."""
        raw = payload.get("incident_id")
        try:
            incident_id = UUID(str(raw))
        except (ValueError, TypeError):
            return
        with self._lock:
            self._notifications[incident_id] = payload
        self._export_timeline(incident_id)

    # ---------------------------------------------------------- queries

    def counters(self) -> dict[str, Any]:
        """The pipeline funnel numbers for guardianctl debug."""
        with self._lock:
            return {
                "status": "ok",
                "detections": self._detections,
                "track_evaluations": self._counters.get("evaluations", 0),
                "candidates": self._counters.get("candidates", 0),
                "rejections": dict(sorted(self._rejections.items())),
                "risk_outcomes": dict(sorted(self._risk_outcomes.items())),
                "timelines_exported": len(self._incidents),
            }

    def evaluations_for(self, track_id: UUID) -> list[TrackEvaluation]:
        with self._lock:
            return list(self._evaluations.get(track_id, ()))

    # -------------------------------------------------- timeline export

    def _export_timeline(self, incident_id: UUID) -> None:
        """Write reports/<incident-id>/timeline.json — replayable decision."""
        try:
            with self._lock:
                incident = self._incidents.get(incident_id)
                if incident is None:
                    return  # snapshot not seen yet; the next hook writes it
                decisions = list(self._risk_decisions.get(incident_id, ()))
                evaluations = list(self._evaluations.get(incident.track_id, ()))
                notification = self._notifications.get(incident_id)
            timeline = {
                "exported_at": datetime.now(tz=timezone.utc).isoformat(),
                "incident": _incident_dict(incident),
                "track_evaluations": [entry.to_dict() for entry in evaluations],
                "risk_decisions": [entry.to_dict() for entry in decisions],
                "notification": notification,
            }
            folder = self._reports_dir / str(incident_id)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / TIMELINE_FILE
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
            temp.replace(target)
        except Exception:  # noqa: BLE001 - the debug trail must never break the box
            logger.exception("timeline export failed for incident %s", incident_id)


# ------------------------------------------------------------ formatting


def _reason_key(reason: str) -> str:
    """Group reasons for counters: strip the numbers, keep the cause."""
    return reason.split(" (", 1)[0]


def _format_evaluation(evaluation: TrackEvaluation) -> str:
    parts = [
        f"track #{evaluation.display_id} ({evaluation.state}, {evaluation.label}) "
        f"{evaluation.camera_id} frame={evaluation.frame_id} "
        f"corr={evaluation.correlation_id}"
    ]
    motion = evaluation.motion
    if motion.vertical_velocity is not None or motion.peak_downward_velocity is not None:
        parts.append(
            "motion "
            f"v_vertical={_num(motion.vertical_velocity)}/s "
            f"v_horizontal={_num(motion.horizontal_velocity)}/s "
            f"peak_down={_num(motion.peak_downward_velocity)}/s "
            f"delta={_num(motion.movement_delta)}"
        )
    signals = evaluation.signals
    if signals.confidence is not None:
        parts.append(
            "signals "
            f"velocity={_num(signals.velocity_score)} "
            f"aspect_ratio={_num(signals.aspect_ratio_score)} "
            f"ground_contact={_num(signals.ground_score)} "
            f"stillness={_num(signals.stillness_score)} "
            f"final_confidence={_num(signals.confidence)}"
        )
    parts.append(
        f"CANDIDATE: {evaluation.reason}"
        if evaluation.outcome == "candidate"
        else f"REJECTED: {evaluation.reason}"
    )
    return " | ".join(parts)


def _format_risk(decision: RiskDecision) -> str:
    header = (
        f"risk {decision.camera_id} track #{decision.display_id} "
        f"{decision.event_type} candidate_confidence={decision.candidate_confidence:.2f}"
    )
    return f"{header} | {decision.outcome.upper()}: {decision.reason}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _incident_dict(incident: SafetyIncident) -> dict[str, Any]:
    """Everything needed to replay the decision (ADR-0007 identity intact)."""
    return {
        "incident_id": str(incident.incident_id),
        "type": incident.incident_type.value,
        "camera_id": incident.camera_id,
        "track_id": str(incident.track_id),
        "track_display_id": incident.track_display_id,
        "severity": incident.severity.value,
        "risk_confidence": incident.risk_confidence,
        "status": incident.status.value,
        "opened_at": incident.opened_at.isoformat(),
        "last_event_at": incident.last_event_at.isoformat(),
        "correlation_id": str(incident.correlation_id),
        "summary": incident.summary,
        "events": [
            {
                "event_id": str(event.event_id),
                "observed_at": event.observed_at.isoformat(),
                "confidence": event.confidence,
                "frame_id": str(event.frame_id),
                "correlation_id": str(event.correlation_id),
                "detection_id": str(event.track.last_detection.detection_id),
                "track_display_id": event.track.display_id,
                "box": {
                    "x": event.track.box.x,
                    "y": event.track.box.y,
                    "width": event.track.box.width,
                    "height": event.track.box.height,
                },
                "signals": [
                    {"name": signal.name, "score": signal.score, "detail": signal.detail}
                    for signal in event.signals
                ],
            }
            for event in incident.events
        ],
        "review": (
            {
                "reviewer": incident.review.reviewer,
                "decided_at": incident.review.decided_at.isoformat(),
                "note": incident.review.note,
            }
            if incident.review is not None
            else None
        ),
    }
