"""Risk engine: policies, correlation, suppression, human review, chain."""

from uuid import uuid4

import pytest
from event_fixtures import fall_trajectory, make_candidate, make_tracking_result, timestamp

from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.risk.policy import RiskPolicy, RiskPolicySet
from guardian_edge.domain.errors import UnknownIncidentError, VisionConfigurationError
from guardian_edge.domain.event import CandidateEventType
from guardian_edge.domain.incident import IncidentStatus, SafetyIncident, Severity

FALL = CandidateEventType.POTENTIAL_FALL


def make_engine(
    incidents: list[SafetyIncident],
    policy: RiskPolicy | None = None,
) -> RiskEngine:
    policy = policy or RiskPolicy(event_type=FALL)
    return RiskEngine(incidents.append, RiskPolicySet({FALL: policy}))


class TestOpeningAndSuppression:
    def test_qualifying_candidate_opens_a_pending_incident(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        engine(make_candidate(0.70))
        assert len(incidents) == 1
        incident = incidents[0]
        assert incident.status is IncidentStatus.PENDING_REVIEW
        assert incident.severity is Severity.MEDIUM
        assert incident.risk_confidence == pytest.approx(0.70)
        assert "awaiting human review" in incident.summary
        assert engine.stats().incidents_opened == 1

    def test_low_confidence_candidates_are_suppressed(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        engine(make_candidate(0.55))  # below min_event_confidence 0.6
        assert incidents == []
        assert engine.stats().suppressed_low_confidence == 1

    def test_corroboration_requirement_delays_opening(self) -> None:
        incidents: list[SafetyIncident] = []
        policy = RiskPolicy(event_type=FALL, min_events_to_open=2)
        engine = make_engine(incidents, policy)
        track_id = uuid4()
        engine(make_candidate(0.70, step=0, track_id=track_id))
        assert incidents == [], "one weak candidate must not open an incident"
        engine(make_candidate(0.70, step=10, track_id=track_id))
        assert len(incidents) == 1
        assert len(incidents[0].events) == 2
        # noisy-or of two 0.70 candidates: 1 - 0.3^2 = 0.91 -> CRITICAL
        assert incidents[0].risk_confidence == pytest.approx(0.91)
        assert incidents[0].severity is Severity.CRITICAL

    def test_fast_path_opens_immediately_despite_corroboration_rule(self) -> None:
        incidents: list[SafetyIncident] = []
        policy = RiskPolicy(event_type=FALL, min_events_to_open=3)
        engine = make_engine(incidents, policy)
        engine(make_candidate(0.90))
        assert len(incidents) == 1
        assert incidents[0].severity is Severity.CRITICAL

    def test_corroboration_window_expires(self) -> None:
        incidents: list[SafetyIncident] = []
        policy = RiskPolicy(event_type=FALL, min_events_to_open=2, aggregation_window_seconds=5.0)
        engine = make_engine(incidents, policy)
        track_id = uuid4()
        engine(make_candidate(0.70, step=0, track_id=track_id))
        engine(make_candidate(0.70, step=100, track_id=track_id))  # 10s later
        assert incidents == [], "stale candidates must not corroborate"

    def test_unknown_event_type_is_ignored(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = RiskEngine(incidents.append, RiskPolicySet({}))
        engine(make_candidate(0.9))
        assert incidents == []
        assert engine.stats().ignored_no_policy == 1


class TestCorrelation:
    def test_new_evidence_attaches_to_the_open_incident(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        track_id = uuid4()
        engine(make_candidate(0.70, step=0, track_id=track_id))
        engine(make_candidate(0.70, step=50, track_id=track_id))
        assert len(incidents) == 2, "two snapshots emitted"
        assert incidents[0].incident_id == incidents[1].incident_id, "same incident"
        assert len(incidents[1].events) == 2
        assert engine.stats().incidents_opened == 1
        assert engine.stats().events_correlated == 1

    def test_correlation_escalates_severity(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        track_id = uuid4()
        engine(make_candidate(0.70, step=0, track_id=track_id))  # MEDIUM
        engine(make_candidate(0.70, step=50, track_id=track_id))  # noisy-or 0.91
        assert incidents[1].severity is Severity.CRITICAL
        assert engine.stats().escalations == 1

    def test_separate_tracks_get_separate_incidents(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        engine(make_candidate(0.70, step=0, track_id=uuid4(), display_id=1))
        engine(make_candidate(0.70, step=1, track_id=uuid4(), display_id=2))
        assert len({incident.incident_id for incident in incidents}) == 2

    def test_correlation_id_anchors_to_the_first_event(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        track_id = uuid4()
        first = make_candidate(0.70, step=0, track_id=track_id)
        engine(first)
        engine(make_candidate(0.70, step=50, track_id=track_id))
        assert incidents[1].correlation_id == first.correlation_id


class TestHumanReview:
    def test_confirm_resolves_and_removes_from_open_set(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        engine(make_candidate(0.70))
        resolved = engine.confirm(
            incidents[0].incident_id, reviewer="director-anna", decided_at=timestamp(20)
        )
        assert resolved.status is IncidentStatus.CONFIRMED
        assert engine.open_incidents() == ()
        assert incidents[-1].status is IncidentStatus.CONFIRMED, "consumers see the resolution"
        assert engine.stats().confirmed == 1

    def test_dismissal_suppresses_the_track_for_a_while(self) -> None:
        incidents: list[SafetyIncident] = []
        policy = RiskPolicy(event_type=FALL, dismissal_suppression_seconds=60.0)
        engine = make_engine(incidents, policy)
        track_id = uuid4()
        engine(make_candidate(0.70, step=0, track_id=track_id))
        engine.dismiss(incidents[0].incident_id, reviewer="director-anna", decided_at=timestamp(10))
        engine(make_candidate(0.70, step=20, track_id=track_id))  # 1s after dismissal
        assert engine.stats().suppressed_after_dismissal == 1
        assert engine.stats().incidents_opened == 1, "no new incident during suppression"
        engine(make_candidate(0.70, step=700, track_id=track_id))  # 60s later
        assert engine.stats().incidents_opened == 2, "suppression expires"

    def test_nothing_in_the_engine_can_resolve_without_a_human(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = make_engine(incidents)
        engine(make_candidate(0.70, step=0))
        for incident in engine.open_incidents():
            assert incident.status is IncidentStatus.PENDING_REVIEW
        with pytest.raises(VisionConfigurationError):
            engine.confirm(engine.open_incidents()[0].incident_id, reviewer="  ")

    def test_resolving_unknown_incident_raises(self) -> None:
        engine = make_engine([])
        with pytest.raises(UnknownIncidentError):
            engine.confirm(uuid4(), reviewer="director-anna")


class TestRobustness:
    def test_consumer_failure_is_isolated(self) -> None:
        def broken(incident: SafetyIncident) -> None:
            raise ValueError("consumer bug")

        engine = RiskEngine(broken)
        engine(make_candidate(0.70))
        stats = engine.stats()
        assert stats.consumer_errors == 1
        assert stats.incidents_opened == 1, "the incident still exists and stays open"
        assert len(engine.open_incidents()) == 1


def test_deliverable_full_chain_candidate_to_incident() -> None:
    """PotentialFallCandidate -> SafetyIncident, through every real layer."""
    from guardian_edge.application.events.engine import EventEngine
    from guardian_edge.application.events.fall import PotentialFallDetector

    incidents: list[SafetyIncident] = []
    risk_engine = RiskEngine(incidents.append)
    event_engine = EventEngine([PotentialFallDetector()], risk_engine)

    track_id = uuid4()
    for step, box in enumerate(fall_trajectory()):
        event_engine(make_tracking_result(box, step, track_id=track_id))

    assert len(incidents) == 1, "one fall -> one incident"
    incident = incidents[0]
    assert incident.incident_type is CandidateEventType.POTENTIAL_FALL
    assert incident.status is IncidentStatus.PENDING_REVIEW, "humans decide, always"
    assert incident.severity is Severity.MEDIUM
    assert incident.events[0].signals, "evidence chain: incident -> candidate -> signals"
    assert incident.correlation_id == incident.events[0].correlation_id
    resolved = risk_engine.confirm(
        incident.incident_id, reviewer="director-anna", decided_at=timestamp(100)
    )
    assert resolved.status is IncidentStatus.CONFIRMED
    assert resolved.review is not None and resolved.review.reviewer == "director-anna"
