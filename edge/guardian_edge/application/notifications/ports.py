"""Ports (interfaces) of the notification engine."""

from __future__ import annotations

from typing import Protocol

from guardian_edge.domain.notification import Notification


class NotificationChannel(Protocol):
    """A delivery transport. Implementations must be synchronous and bounded
    in time; the engine owns queueing and retries, channels own one send."""

    @property
    def name(self) -> str:
        """Channel identifier recorded on every delivery attempt."""
        ...

    def send(self, notification: Notification) -> None:
        """Deliver one notification.

        Raises ChannelDeliveryError (or any exception — the engine isolates
        and retries) when delivery fails.
        """
        ...


class NotificationListener(Protocol):
    """Observes every lifecycle transition (tests, device API, metrics UIs).

    A listener that raises loses that observation only.
    """

    def __call__(self, notification: Notification) -> None: ...
