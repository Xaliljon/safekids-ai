"""Reserved notification channel interfaces (ADR-0014 §channel abstraction).

Each is an abstract base a future sprint implements behind the same
NotificationChannel port the engine already drives — adding a transport
never touches the engine. None of these are implemented today, by design:
every remote transport has its own credentials, failure modes, and privacy
review, and earns its own sprint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from guardian_edge.domain.notification import Notification


class WebhookChannel(ABC):
    """HTTP POST of the payload to configured endpoints (on-premises
    integrations). Requires: endpoint allowlisting, TLS, timeouts."""

    name = "webhook"

    @abstractmethod
    def send(self, notification: Notification) -> None: ...


class TelegramChannel(ABC):
    """Telegram bot delivery. Requires: bot credentials in secure storage,
    per-recipient consent, and a privacy review (payload leaves premises)."""

    name = "telegram"

    @abstractmethod
    def send(self, notification: Notification) -> None: ...


class SmsChannel(ABC):
    """SMS gateway delivery for no-smartphone fallback. Requires: provider
    contract, cost controls, strict payload minimization."""

    name = "sms"

    @abstractmethod
    def send(self, notification: Notification) -> None: ...


class EmailChannel(ABC):
    """Email delivery for digests and non-urgent notices. Requires: SMTP
    credentials in secure storage; never for time-critical alerts."""

    name = "email"

    @abstractmethod
    def send(self, notification: Notification) -> None: ...
