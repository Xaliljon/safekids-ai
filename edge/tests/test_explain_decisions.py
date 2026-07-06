"""Every decision is explainable: exact reasons, no silent paths."""

from __future__ import annotations

from uuid import uuid4

from event_fixtures import (
    fall_trajectory,
    make_candidate,
    make_tracking_result,
    walking_trajectory,
)

from guardian_edge.application.debugging.explain import RiskDecision, TrackEvaluation
from guardian_edge.application.events.engine import EventEngine
from guardian_edge.application.events.fall import FallDetectorConfig, PotentialFallDetector
from guardian_edge.application.events.history import TrackHistoryStore
from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.risk.policy import RiskPolicy, RiskPolicySet
from guardian_edge.domain.detection import BoundingBox
from guardian_edge.domain.event import CandidateEventType
from guardian_edge.domain.track import TrackState

BOX = BoundingBox(x=0.4, y=0.3, width=0.1, height=0.4)


def run(boxes: list, detector: PotentialFallDetector, label: str = "child") -> list:
    store = TrackHistoryStore()
    track_id = uuid4()
    events = []
    for step, box in enumerate(boxes):
        result = make_tracking_result(box, step, track_id=track_id, label=label)
        store.observe(result)
        event = detector.evaluate(store.history(track_id), result.tracks[0], result)
        if event is not None:
            events.append(event)
    return events


class TestFallDetectorExplanations:
    def observer(self) -> tuple[list[TrackEvaluation], PotentialFallDetector]:
        seen: list[TrackEvaluation] = []
        return seen, PotentialFallDetector(observer=seen.append)

    def test_every_evaluation_produces_an_explanation(self) -> None:
        """No silent paths: one explanation per evaluate() call."""
        seen, detector = self.observer()
        boxes = fall_trajectory()
        run(boxes, detector)
        assert len(seen) == len(boxes)
        assert all(entry.reason for entry in seen), "reasons are never empty"

    def test_label_not_monitored(self) -> None:
        seen, detector = self.observer()
        run([BOX] * 3, detector, label="chair")
        assert seen[0].outcome == "rejected"
        assert "label 'chair' is not monitored" in seen[0].reason

    def test_history_too_short(self) -> None:
        seen, detector = self.observer()
        run([BOX] * 3, detector)  # 0.2s of history < 1.0s required
        assert "track history too short" in seen[0].reason
        assert "1.00s required" in seen[0].reason

    def test_downward_velocity_too_low(self) -> None:
        seen, detector = self.observer()
        run(walking_trajectory(), detector)
        rejected = [entry for entry in seen if "downward velocity too low" in entry.reason]
        assert rejected, "a flat walk must be rejected for lack of downward motion"
        assert "< 0.20" in rejected[0].reason
        # motion analysis is present even on gate rejections
        assert rejected[0].motion.peak_downward_velocity is not None
        assert rejected[0].motion.horizontal_velocity is not None

    def test_confidence_below_threshold_carries_the_breakdown(self) -> None:
        # Raise the threshold so a real fall now falls short of it: the
        # rejection must include the full signal breakdown.
        seen: list[TrackEvaluation] = []
        detector = PotentialFallDetector(
            FallDetectorConfig(confidence_threshold=0.99), observer=seen.append
        )
        run(fall_trajectory(), detector)
        below = [entry for entry in seen if "confidence below threshold" in entry.reason]
        assert below, "the fall scores high but below 0.99"
        entry = below[0]
        assert "< 0.99" in entry.reason
        assert entry.signals.velocity_score is not None
        assert entry.signals.aspect_ratio_score is not None
        assert entry.signals.ground_score is not None
        assert entry.signals.stillness_score is not None
        assert entry.signals.confidence is not None

    def test_detector_cooldown_reason_with_remaining_seconds(self) -> None:
        seen, detector = self.observer()
        boxes = fall_trajectory() + fall_trajectory(standing_frames=1)
        run(boxes, detector)
        cooldown = [entry for entry in seen if "detector cooldown active" in entry.reason]
        assert cooldown
        assert "s remaining" in cooldown[0].reason

    def test_candidate_explanation_matches_the_event(self) -> None:
        seen, detector = self.observer()
        events = run(fall_trajectory(), detector)
        assert events
        accepted = [entry for entry in seen if entry.outcome == "candidate"]
        assert len(accepted) == len(events)
        entry, event = accepted[0], events[0]
        assert entry.signals.confidence == event.confidence
        assert entry.frame_id == event.frame_id
        assert entry.correlation_id == event.correlation_id
        by_name = {signal.name: signal.score for signal in event.signals}
        assert entry.signals.velocity_score == round(by_name["downward_velocity"], 3)
        assert entry.signals.stillness_score == round(by_name["stillness"], 3)

    def test_observer_never_changes_decisions(self) -> None:
        silent = PotentialFallDetector()
        observed = PotentialFallDetector(observer=lambda evaluation: None)
        assert len(run(fall_trajectory(), silent)) == len(run(fall_trajectory(), observed))
        assert run(walking_trajectory(), silent) == run(walking_trajectory(), observed) == []

    def test_broken_observer_never_breaks_detection(self) -> None:
        def explode(evaluation: TrackEvaluation) -> None:
            raise RuntimeError("observer bug")

        detector = PotentialFallDetector(observer=explode)
        events = run(fall_trajectory(), detector)
        assert events, "detection unaffected by a crashing observer"


class TestEventEngineExplanations:
    def test_unconfirmed_tracks_get_explicit_reasons(self) -> None:
        seen: list[TrackEvaluation] = []
        engine = EventEngine(
            [PotentialFallDetector()], lambda event: None, evaluation_observer=seen.append
        )
        tentative = make_tracking_result(BOX, 0, state=TrackState.TENTATIVE)
        lost = make_tracking_result(BOX, 1, state=TrackState.LOST)
        engine(tentative)
        engine(lost)
        reasons = [entry.reason for entry in seen]
        assert any("track not confirmed" in reason for reason in reasons)
        assert any("track lost" in reason for reason in reasons)

    def test_confirmed_tracks_are_not_flagged_by_the_engine(self) -> None:
        seen: list[TrackEvaluation] = []
        engine = EventEngine([], lambda event: None, evaluation_observer=seen.append)
        engine(make_tracking_result(BOX, 0, state=TrackState.CONFIRMED))
        assert seen == []


class TestRiskEngineExplanations:
    def harness(self, policy: RiskPolicy | None = None):  # noqa: ANN201
        decisions: list[RiskDecision] = []
        incidents: list = []
        policies = (
            RiskPolicySet({CandidateEventType.POTENTIAL_FALL: policy})
            if policy is not None
            else RiskPolicySet()
        )
        engine = RiskEngine(incidents.append, policies=policies, observer=decisions.append)
        return engine, decisions, incidents

    def test_incident_opened_explanation(self) -> None:
        engine, decisions, incidents = self.harness()
        engine(make_candidate(0.9))
        assert incidents, "fast path opens immediately"
        decision = decisions[-1]
        assert decision.outcome == "incident_opened"
        assert "risk confidence" in decision.reason
        assert "incident created" in decision.reason
        assert decision.severity is not None
        assert decision.incident_id == incidents[0].incident_id

    def test_corroboration_and_escalation_explanations(self) -> None:
        engine, decisions, incidents = self.harness()
        track_id = uuid4()
        engine(make_candidate(0.86, step=0, track_id=track_id))
        engine(make_candidate(0.95, step=5, track_id=track_id))
        outcomes = [decision.outcome for decision in decisions]
        assert outcomes[0] == "incident_opened"
        assert outcomes[1] in ("corroborated", "escalated")
        assert "corroborates open incident" in decisions[1].reason
        assert decisions[1].corroborating_events == 2

    def test_low_confidence_rejection(self) -> None:
        engine, decisions, _ = self.harness()
        engine(make_candidate(0.3))
        decision = decisions[-1]
        assert decision.outcome == "rejected"
        assert "confidence below policy minimum" in decision.reason
        assert "0.30 < 0.60" in decision.reason

    def test_awaiting_corroboration_rejection(self) -> None:
        engine, decisions, incidents = self.harness(
            RiskPolicy(
                event_type=CandidateEventType.POTENTIAL_FALL,
                min_events_to_open=2,
                fast_path_confidence=0.99,
            )
        )
        engine(make_candidate(0.7))
        assert not incidents
        decision = decisions[-1]
        assert decision.outcome == "rejected"
        assert "awaiting corroboration" in decision.reason
        assert "1/2" in decision.reason

    def test_suppressed_after_dismissal_with_remaining_seconds(self) -> None:
        engine, decisions, incidents = self.harness()
        track_id = uuid4()
        engine(make_candidate(0.9, step=0, track_id=track_id))
        incident = incidents[0]
        engine.dismiss(incident.incident_id, reviewer="director")
        engine(make_candidate(0.9, step=1, track_id=track_id))
        decision = decisions[-1]
        assert decision.outcome == "rejected"
        assert "suppressed after human dismissal" in decision.reason
        assert decision.seconds_remaining is not None
        assert decision.seconds_remaining > 0

    def test_no_policy_rejection(self) -> None:
        decisions: list[RiskDecision] = []
        engine = RiskEngine(
            lambda incident: None,
            policies=RiskPolicySet({}),
            observer=decisions.append,
        )
        engine(make_candidate(0.9))
        assert "no risk policy registered" in decisions[-1].reason

    def test_observer_never_changes_decisions(self) -> None:
        silent, _, silent_incidents = self.harness()
        loud, _, loud_incidents = self.harness()
        for engine in (silent, loud):
            track_id = uuid4()
            engine(make_candidate(0.3, track_id=track_id))
            engine(make_candidate(0.9, track_id=track_id))
        assert len(silent_incidents) == len(loud_incidents) == 1
