"""Notification domain: lifecycle, attempts, policy, payload hygiene."""

from datetime import timedelta
from uuid import uuid4

import pytest
from event_fixtures import make_safety_incident, timestamp

from guardian_edge.domain.errors import (
    IllegalTransitionError,
    NotificationError,
    VisionConfigurationError,
)
from guardian_edge.domain.incident import Severity
from guardian_edge.domain.notification import (
    DeliveryAttempt,
    Notification,
    NotificationAction,
    NotificationPolicy,
    NotificationPriority,
    NotificationStatus,
)


def make_notification() -> Notification:
    return Notification.for_incident(
        make_safety_incident(),
        priority=NotificationPriority.IMMEDIATE,
        channel="local-push",
        notification_id=uuid4(),
        created_at=timestamp(1),
    )


def attempt(number: int = 1, succeeded: bool = True, error: str = "") -> DeliveryAttempt:
    return DeliveryAttempt(
        number=number,
        channel="local-push",
        started_at=timestamp(2),
        finished_at=timestamp(2) + timedelta(milliseconds=5),
        succeeded=succeeded,
        error=error,
    )


class TestLifecycle:
    def test_happy_path(self) -> None:
        notification = make_notification()
        assert notification.status is NotificationStatus.PENDING
        delivered = notification.queued().sending().delivered(attempt())
        assert delivered.status is NotificationStatus.DELIVERED
        assert len(delivered.attempts) == 1

    def test_retry_loop(self) -> None:
        sending = make_notification().queued().sending()
        retrying = sending.retrying(attempt(succeeded=False, error="boom"))
        assert retrying.status is NotificationStatus.RETRYING
        delivered = retrying.sending().delivered(attempt(number=2))
        assert delivered.status is NotificationStatus.DELIVERED
        assert [a.succeeded for a in delivered.attempts] == [False, True]

    def test_permanent_failure(self) -> None:
        failed = (
            make_notification().queued().sending().failed(attempt(succeeded=False, error="dead"))
        )
        assert failed.status is NotificationStatus.FAILED

    @pytest.mark.parametrize(
        "build",
        [
            lambda n: n.sending(),  # PENDING -> SENDING skips QUEUED
            lambda n: n.delivered(attempt()),  # PENDING -> DELIVERED
            lambda n: n.queued().queued(),  # QUEUED -> QUEUED
            lambda n: n.queued().delivered(attempt()),  # QUEUED -> DELIVERED
            lambda n: n.queued().sending().delivered(attempt()).queued(),  # terminal
            lambda n: n.queued().sending().failed(attempt(succeeded=False)).sending(),
        ],
    )
    def test_illegal_transitions_are_impossible(self, build) -> None:  # noqa: ANN001
        with pytest.raises(IllegalTransitionError):
            build(make_notification())

    def test_status_attempt_consistency(self) -> None:
        sending = make_notification().queued().sending()
        with pytest.raises(NotificationError, match="successful attempt"):
            sending.delivered(attempt(succeeded=False))
        with pytest.raises(NotificationError, match="failed attempt"):
            sending.retrying(attempt(succeeded=True))

    def test_attempt_numbering_is_enforced(self) -> None:
        sending = make_notification().queued().sending()
        with pytest.raises(NotificationError, match="out of order"):
            sending.delivered(attempt(number=3))


class TestDeliveryAttempt:
    def test_rejects_inconsistent_attempts(self) -> None:
        with pytest.raises(NotificationError):
            attempt(number=0)
        with pytest.raises(NotificationError):
            attempt(succeeded=True, error="but there is an error")
        with pytest.raises(NotificationError):
            DeliveryAttempt(
                number=1,
                channel="x",
                started_at=timestamp(3),
                finished_at=timestamp(2),
                succeeded=True,
            )


class TestPolicy:
    def test_defaults_match_the_spec(self) -> None:
        policy = NotificationPolicy()
        assert policy.action_for(Severity.CRITICAL) is NotificationAction.NOTIFY_IMMEDIATE
        assert policy.action_for(Severity.HIGH) is NotificationAction.NOTIFY_IMMEDIATE
        assert policy.action_for(Severity.MEDIUM) is NotificationAction.NOTIFY
        assert policy.action_for(Severity.LOW) is NotificationAction.IGNORE

    def test_medium_is_configurable(self) -> None:
        actions = {
            Severity.CRITICAL: NotificationAction.NOTIFY_IMMEDIATE,
            Severity.HIGH: NotificationAction.NOTIFY_IMMEDIATE,
            Severity.MEDIUM: NotificationAction.IGNORE,
            Severity.LOW: NotificationAction.IGNORE,
        }
        assert NotificationPolicy(actions).action_for(Severity.MEDIUM) is (
            NotificationAction.IGNORE
        )

    def test_policy_must_cover_every_severity(self) -> None:
        with pytest.raises(VisionConfigurationError, match="missing"):
            NotificationPolicy({Severity.CRITICAL: NotificationAction.NOTIFY_IMMEDIATE})


class TestPayload:
    def test_payload_contains_exactly_the_contract_fields(self) -> None:
        payload = make_notification().to_payload()
        assert set(payload) == {
            "notification_id",
            "incident_id",
            "camera_id",
            "track_id",
            "track_display_id",
            "correlation_id",
            "type",
            "severity",
            "confidence",
            "incident_status",
            "timestamp",
            "created_at",
            "summary",
            "event_count",
            "priority",
        }
        assert payload["severity"] == "medium"
        assert payload["confidence"] == 0.7

    def test_payload_carries_no_media_and_no_pii(self) -> None:
        payload = make_notification().to_payload()
        forbidden_fragments = ("image", "video", "clip", "frame_data", "name", "face")
        for key in payload:
            assert not any(fragment in key.lower() for fragment in forbidden_fragments)
        # The summary references people only by track number.
        assert "track #" in payload["summary"]
