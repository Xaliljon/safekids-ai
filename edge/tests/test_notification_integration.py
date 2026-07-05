"""End-to-end: SafetyIncident -> NotificationEngine -> LocalPushChannel -> Delivered.

Plus the full seven-layer chain: tracking results -> EventEngine ->
RiskEngine -> NotificationEngine -> durable outbox on disk.
"""

import json
from pathlib import Path
from uuid import uuid4

from camera_fakes import wait_until
from event_fixtures import fall_trajectory, make_safety_incident, make_tracking_result

from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import PotentialFallDetector
from guardian_edge.application.notifications.engine import NotificationEngine
from guardian_edge.application.notifications.retry import RetryStrategy
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.domain.incident import Severity
from guardian_edge.domain.notification import Notification, NotificationStatus
from guardian_edge.infrastructure.notifications.local_push import (
    OUTBOX_FILE_NAME,
    LocalPushChannel,
)

FAST_RETRY = RetryStrategy((0.01, 0.02))


def test_deliverable_incident_to_delivered_local_push(tmp_path: Path) -> None:
    """The sprint deliverable, literally."""
    channel = LocalPushChannel(tmp_path)
    observed: list[Notification] = []
    engine = NotificationEngine(channel, retry=FAST_RETRY, listener=observed.append)
    engine.start()
    try:
        incident = make_safety_incident(severity=Severity.CRITICAL, confidence=0.9)
        engine(incident)
        assert wait_until(lambda: any(n.status is NotificationStatus.DELIVERED for n in observed))
    finally:
        engine.stop()
    delivered = [n for n in observed if n.status is NotificationStatus.DELIVERED][0]
    assert delivered.incident_id == incident.incident_id
    lines = (tmp_path / OUTBOX_FILE_NAME).read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["incident_id"] == str(incident.incident_id)
    assert payload["correlation_id"] == str(incident.correlation_id)
    assert payload["severity"] == "critical"


def test_full_chain_from_tracking_to_outbox(tmp_path: Path) -> None:
    """tracks -> candidates -> incident -> notification -> durable outbox."""
    channel = LocalPushChannel(tmp_path)
    live_payloads: list[dict] = []
    channel.subscribe(live_payloads.append)

    notification_engine = NotificationEngine(channel, retry=FAST_RETRY)
    risk_engine = RiskEngine(notification_engine)
    event_engine = EventEngine([PotentialFallDetector()], risk_engine)

    notification_engine.start()
    try:
        track_id = uuid4()
        for step, box in enumerate(fall_trajectory()):
            event_engine(make_tracking_result(box, step, track_id=track_id))
        assert wait_until(lambda: notification_engine.metrics().delivered == 1)
    finally:
        notification_engine.stop()

    payload = json.loads((tmp_path / OUTBOX_FILE_NAME).read_text(encoding="utf-8").splitlines()[0])
    assert payload["type"] == "safety_incident"
    assert payload["severity"] == "medium"
    assert payload["incident_status"] == "pending_review"
    assert "track #" in payload["summary"], "humans get track numbers, never identities"
    assert live_payloads and live_payloads[0] == payload, "live push matches the outbox"
    incident = risk_engine.open_incidents()[0]
    assert payload["incident_id"] == str(incident.incident_id)
    assert payload["correlation_id"] == str(incident.correlation_id), (
        "the ADR-0007 chain survives to the wire payload"
    )
