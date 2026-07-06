"""RiskDebugRecorder: the debug trail, counters and replayable timelines."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from event_fixtures import fall_trajectory, make_safety_incident, make_tracking_result

from guardian_edge.application.debugging.recorder import RiskDebugRecorder
from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.ops.logging_setup import configure_logging


@pytest.fixture()
def recorder(tmp_path: Path) -> RiskDebugRecorder:
    return RiskDebugRecorder(tmp_path / "reports")


def run_full_chain(recorder: RiskDebugRecorder) -> list:
    """The real chain: trajectory -> event engine -> risk engine -> recorder."""
    incidents: list = []

    def on_incident(incident) -> None:  # noqa: ANN001 - fixture chain
        incidents.append(incident)
        recorder.on_incident(incident)

    risk = RiskEngine(on_incident, observer=recorder.on_risk_decision)
    engine = EventEngine(
        [PotentialFallDetector(observer=recorder.on_evaluation)],
        risk,
        evaluation_observer=recorder.on_evaluation,
    )
    track_id = uuid4()
    for step, box in enumerate(fall_trajectory()):
        engine(make_tracking_result(box, step, track_id=track_id))
    return incidents


class TestDebugLog:
    def test_risk_debug_log_receives_every_decision(
        self, recorder: RiskDebugRecorder, tmp_path: Path
    ) -> None:
        configure_logging(tmp_path / "logs", console=False)
        try:
            run_full_chain(recorder)
        finally:
            configure_logging(tmp_path / "logs", console=False)
        debug_log = tmp_path / "logs" / "risk-debug.log"
        assert debug_log.is_file(), "guardian/logs/risk-debug.log exists"
        lines = [
            json.loads(line)
            for line in debug_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) >= 30, "one line per decision, per frame"
        messages = [line["message"] for line in lines]
        assert any("REJECTED: track history too short" in message for message in messages)
        assert any("REJECTED: downward velocity too low" in message for message in messages)
        assert any("CANDIDATE:" in message for message in messages)
        assert any("INCIDENT_OPENED" in message for message in messages)
        # signal breakdown appears exactly as the spec asks
        breakdown = next(message for message in messages if "final_confidence" in message)
        for field in ("velocity=", "aspect_ratio=", "ground_contact=", "stillness="):
            assert field in breakdown
        # identity chain in every track line
        track_line = next(message for message in messages if message.startswith("track #"))
        for field in ("frame=", "corr=", "cam-1"):
            assert field in track_line

    def test_debug_lines_do_not_flood_system_log(
        self, recorder: RiskDebugRecorder, tmp_path: Path
    ) -> None:
        configure_logging(tmp_path / "logs", console=False)
        try:
            run_full_chain(recorder)
        finally:
            configure_logging(tmp_path / "logs", console=False)
        system_log = (tmp_path / "logs" / "system.log").read_text(encoding="utf-8")
        assert "REJECTED: downward velocity too low" not in system_log


class TestCounters:
    def test_funnel_counters(self, recorder: RiskDebugRecorder) -> None:
        recorder.on_detections(3)
        recorder.on_detections(2)
        incidents = run_full_chain(recorder)
        counters = recorder.counters()
        assert counters["detections"] == 5
        assert counters["track_evaluations"] == len(fall_trajectory())
        assert counters["candidates"] >= 1
        assert counters["risk_outcomes"].get("incident_opened", 0) == len(incidents) >= 1
        assert "downward velocity too low" in counters["rejections"]
        assert "track history too short" in counters["rejections"]

    def test_rejection_reasons_group_without_numbers(self, recorder: RiskDebugRecorder) -> None:
        run_full_chain(recorder)
        for reason in recorder.counters()["rejections"]:
            assert "(" not in reason, "counters group by cause, not by numbers"


class TestTimelineExport:
    def test_timeline_contains_everything_to_replay(
        self, recorder: RiskDebugRecorder, tmp_path: Path
    ) -> None:
        incidents = run_full_chain(recorder)
        incident = incidents[0]
        timeline_path = tmp_path / "reports" / str(incident.incident_id) / "timeline.json"
        assert timeline_path.is_file()
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        # incident + risk + review state
        assert timeline["incident"]["incident_id"] == str(incident.incident_id)
        assert timeline["incident"]["risk_confidence"] == incident.risk_confidence
        assert timeline["incident"]["severity"] == incident.severity.value
        # frames, detections, track, signals (ADR-0007 chain)
        event = timeline["incident"]["events"][0]
        for key in ("frame_id", "correlation_id", "detection_id", "track_display_id", "box"):
            assert event[key], key
        assert {signal["name"] for signal in event["signals"]} == {
            "downward_velocity",
            "aspect_ratio_flip",
            "ground_proximity",
            "stillness",
        }
        # per-frame decisions leading up to the incident
        assert timeline["track_evaluations"], "the decision history is present"
        assert any(entry["outcome"] == "candidate" for entry in timeline["track_evaluations"])
        assert all(entry["reason"] for entry in timeline["track_evaluations"])
        # the risk decision that created it
        assert timeline["risk_decisions"][0]["outcome"] == "incident_opened"

    def test_notification_payload_joins_the_timeline(
        self, recorder: RiskDebugRecorder, tmp_path: Path
    ) -> None:
        incident = make_safety_incident(0.9)
        recorder.on_incident(incident)
        recorder.on_notification({"incident_id": str(incident.incident_id), "severity": "critical"})
        timeline = json.loads(
            (tmp_path / "reports" / str(incident.incident_id) / "timeline.json").read_text(
                encoding="utf-8"
            )
        )
        assert timeline["notification"]["severity"] == "critical"

    def test_garbage_notification_is_ignored(self, recorder: RiskDebugRecorder) -> None:
        recorder.on_notification({"incident_id": "not-a-uuid"})
        recorder.on_notification({})  # must not raise

    def test_export_failure_never_breaks_the_box(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        blocked = tmp_path / "blocked"
        blocked.write_text("a file where a directory must be", encoding="utf-8")
        recorder = RiskDebugRecorder(blocked)  # reports dir is a file -> IO errors
        with caplog.at_level(logging.ERROR):
            recorder.on_incident(make_safety_incident(0.9))  # must not raise
        assert any("timeline export failed" in record.message for record in caplog.records)
