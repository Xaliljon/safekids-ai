"""LocalPushChannel: durable outbox + best-effort live fan-out."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from event_fixtures import make_safety_incident, timestamp

from guardian_edge.domain.errors import ChannelDeliveryError
from guardian_edge.domain.notification import Notification, NotificationPriority
from guardian_edge.infrastructure.notifications.local_push import (
    OUTBOX_FILE_NAME,
    LocalPushChannel,
)


def make_notification() -> Notification:
    return Notification.for_incident(
        make_safety_incident(),
        priority=NotificationPriority.IMMEDIATE,
        channel="local-push",
        notification_id=uuid4(),
        created_at=timestamp(1),
    )


def test_send_appends_durable_jsonl_lines(tmp_path: Path) -> None:
    channel = LocalPushChannel(tmp_path / "spool")
    first, second = make_notification(), make_notification()
    channel.send(first)
    channel.send(second)
    lines = (tmp_path / "spool" / OUTBOX_FILE_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["notification_id"] == str(first.notification_id)
    assert payload["severity"] == "medium"
    assert payload["summary"].startswith("1 corroborating")


def test_subscribers_receive_the_payload(tmp_path: Path) -> None:
    channel = LocalPushChannel(tmp_path)
    received: list[dict[str, Any]] = []
    channel.subscribe(received.append)
    notification = make_notification()
    channel.send(notification)
    assert len(received) == 1
    assert received[0]["incident_id"] == str(notification.incident_id)


def test_subscriber_failure_never_fails_delivery(tmp_path: Path) -> None:
    channel = LocalPushChannel(tmp_path)
    received: list[dict[str, Any]] = []

    def broken(payload: dict[str, Any]) -> None:
        raise RuntimeError("subscriber bug")

    channel.subscribe(broken)
    channel.subscribe(received.append)
    channel.send(make_notification())  # must not raise
    assert len(received) == 1, "later subscribers still receive after one breaks"
    assert (tmp_path / OUTBOX_FILE_NAME).exists(), "durability is unaffected"


def test_unwritable_spool_is_a_delivery_failure(tmp_path: Path) -> None:
    blocker = tmp_path / "spool"
    blocker.write_text("a file where the spool directory should be", encoding="utf-8")
    channel = LocalPushChannel(blocker)
    with pytest.raises(ChannelDeliveryError, match="outbox write failed"):
        channel.send(make_notification())
