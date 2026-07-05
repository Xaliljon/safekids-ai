"""SafetyIncident domain: evidence rules and human-review invariants."""

from uuid import uuid4

import pytest
from event_fixtures import make_candidate, timestamp

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEventType
from guardian_edge.domain.incident import (
    IncidentReview,
    IncidentStatus,
    SafetyIncident,
    Severity,
)


def make_incident(track_id: object = None, **overrides: object) -> SafetyIncident:
    track_id = track_id or uuid4()
    event = make_candidate(0.7, step=0, track_id=track_id)
    kwargs: dict[str, object] = {
        "incident_id": uuid4(),
        "incident_type": CandidateEventType.POTENTIAL_FALL,
        "camera_id": "cam-1",
        "track_id": event.track.track_id,
        "track_display_id": 1,
        "severity": Severity.MEDIUM,
        "risk_confidence": 0.7,
        "opened_at": event.observed_at,
        "last_event_at": event.observed_at,
        "correlation_id": event.correlation_id,
        "events": (event,),
        "summary": "test incident",
    }
    kwargs.update(overrides)
    return SafetyIncident(**kwargs)  # type: ignore[arg-type]


def test_incidents_are_born_pending_review() -> None:
    incident = make_incident()
    assert incident.status is IncidentStatus.PENDING_REVIEW
    assert incident.review is None


def test_incident_without_evidence_cannot_exist() -> None:
    with pytest.raises(VisionConfigurationError, match="without evidence"):
        make_incident(events=())


def test_evidence_must_match_camera_and_track() -> None:
    foreign = make_candidate(0.7, step=1, camera_id="cam-2")
    with pytest.raises(VisionConfigurationError, match="own camera and track"):
        make_incident(events=(make_candidate(0.7), foreign))


def test_resolution_requires_an_identified_reviewer() -> None:
    incident = make_incident()
    with pytest.raises(VisionConfigurationError, match="identified reviewer"):
        incident.confirmed(reviewer="  ", decided_at=timestamp(10))


def test_confirm_and_dismiss_record_the_review() -> None:
    incident = make_incident()
    confirmed = incident.confirmed("director-anna", timestamp(10), note="checked the room")
    assert confirmed.status is IncidentStatus.CONFIRMED
    assert confirmed.review is not None
    assert confirmed.review.reviewer == "director-anna"
    dismissed = make_incident().dismissed("director-anna", timestamp(11))
    assert dismissed.status is IncidentStatus.DISMISSED


def test_double_resolution_is_impossible() -> None:
    resolved = make_incident().confirmed("director-anna", timestamp(10))
    with pytest.raises(VisionConfigurationError, match="already resolved"):
        resolved.dismissed("someone-else", timestamp(11))


def test_resolved_incident_accepts_no_new_evidence() -> None:
    track_id = uuid4()
    incident = make_incident(track_id=track_id)
    resolved = incident.confirmed("director-anna", timestamp(10))
    extra = make_candidate(0.8, step=5, track_id=incident.track_id)
    with pytest.raises(VisionConfigurationError, match="resolved incident"):
        resolved.with_event(extra, 0.9, Severity.HIGH)


def test_review_consistency_is_enforced_at_construction() -> None:
    with pytest.raises(VisionConfigurationError, match="review must be present"):
        make_incident(status=IncidentStatus.CONFIRMED)  # resolved but no review
    with pytest.raises(VisionConfigurationError, match="review must be present"):
        make_incident(
            review=IncidentReview(reviewer="anna", decided_at=timestamp(1))
        )  # pending but reviewed


def test_severity_ranks_order() -> None:
    assert Severity.LOW.rank < Severity.MEDIUM.rank < Severity.HIGH.rank < Severity.CRITICAL.rank
