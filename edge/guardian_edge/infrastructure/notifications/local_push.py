"""Local-first push channel (ADR-0014).

The on-box delivery hub: every notification is durably appended (with
fsync) to a local JSONL outbox, then fanned out best-effort to in-process
subscribers. "Delivered" means the notification is durably on the box —
the charter's local-first requirement: alerting must not depend on
internet, cloud, or even the phone being reachable this instant.

The device API (future sprint) is the transport to directors' phones: it
subscribes for live pushes and serves the outbox for catch-up after
reconnects. Nothing here knows about phones, Flutter, or backends.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from guardian_edge.domain.errors import ChannelDeliveryError
from guardian_edge.domain.notification import Notification

logger = logging.getLogger(__name__)

OUTBOX_FILE_NAME = "notifications.jsonl"

Subscriber = Callable[[dict[str, Any]], None]


class LocalPushChannel:
    """NotificationChannel writing a durable local outbox + live fan-out."""

    def __init__(self, spool_dir: Path) -> None:
        self._spool_dir = spool_dir
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []

    @property
    def name(self) -> str:
        return "local-push"

    def subscribe(self, subscriber: Subscriber) -> None:
        """Register a live payload consumer (the device API attaches here)."""
        with self._lock:
            self._subscribers.append(subscriber)

    def send(self, notification: Notification) -> None:
        """Durably spool the payload, then fan out to subscribers.

        Raises ChannelDeliveryError when the spool write fails — that is a
        delivery failure and the engine will retry. Subscriber errors are
        logged, never fatal: durability is the delivery guarantee, live
        push is best-effort on top.
        """
        payload = notification.to_payload()
        line = json.dumps(payload, sort_keys=True)
        try:
            self._spool_dir.mkdir(parents=True, exist_ok=True)
            with (
                self._lock,
                (self._spool_dir / OUTBOX_FILE_NAME).open("a", encoding="utf-8") as handle,
            ):
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ChannelDeliveryError(f"outbox write failed: {exc}") from exc
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(payload)
            except Exception:
                logger.exception(
                    "local-push subscriber raised for notification %s; live push skipped",
                    payload["notification_id"],
                )
