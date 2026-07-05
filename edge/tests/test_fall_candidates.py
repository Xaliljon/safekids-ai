"""PotentialFallDetector: the deliverable — fall candidates from tracking data."""

from uuid import uuid4

import pytest
from event_fixtures import (
    fall_trajectory,
    make_tracking_result,
    slow_sit_trajectory,
    walking_trajectory,
)

from guardian_edge.application.events.fall import FallDetectorConfig, PotentialFallDetector
from guardian_edge.application.events.history import TrackHistoryStore
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType


def run_trajectory(
    boxes: list,
    detector: PotentialFallDetector | None = None,
    label: str = "child",
) -> list[CandidateEvent]:
    """Feed a trajectory through history + detector; collect emitted events."""
    detector = detector or PotentialFallDetector()
    store = TrackHistoryStore()
    track_id = uuid4()
    events: list[CandidateEvent] = []
    for step, box in enumerate(boxes):
        result = make_tracking_result(box, step, track_id=track_id, label=label)
        store.observe(result)
        event = detector.evaluate(store.history(track_id), result.tracks[0], result)
        if event is not None:
            events.append(event)
    return events


def test_fall_produces_a_potential_fall_candidate() -> None:
    events = run_trajectory(fall_trajectory())
    assert events, "a fall trajectory must produce a candidate"
    event = events[0]
    assert event.event_type is CandidateEventType.POTENTIAL_FALL
    assert event.confidence >= 0.6
    signal_names = {signal.name for signal in event.signals}
    assert signal_names == {
        "downward_velocity",
        "aspect_ratio_flip",
        "ground_proximity",
        "stillness",
    }, "every candidate must explain itself (docs/04)"


def test_candidate_preserves_adr_0007_identity() -> None:
    events = run_trajectory(fall_trajectory())
    event = events[0]
    assert event.camera_id == "cam-1"
    assert event.track.last_detection.correlation_id, "detection evidence chain intact"
    assert event.frame_id != event.track.track_id
    assert event.observed_at == event.track.last_seen_at


def test_walking_never_produces_a_candidate() -> None:
    assert run_trajectory(walking_trajectory()) == []


def test_sitting_down_slowly_never_produces_a_candidate() -> None:
    assert run_trajectory(slow_sit_trajectory()) == []


def test_cooldown_prevents_candidate_spam() -> None:
    # 15 still frames after the fall = many above-threshold evaluations,
    # but one candidate per cooldown window.
    events = run_trajectory(fall_trajectory(still_frames=20))
    assert len(events) == 1


def test_unmonitored_labels_are_never_evaluated() -> None:
    assert run_trajectory(fall_trajectory(), label="chair") == []


def test_fall_without_stillness_scores_lower() -> None:
    from guardian_edge.domain.detection import BoundingBox

    def permissive_detector() -> PotentialFallDetector:
        # No threshold and no cooldown: observe the confidence trajectory itself.
        return PotentialFallDetector(
            FallDetectorConfig(confidence_threshold=0.0, cooldown_seconds=0.01)
        )

    crawling_away = [
        BoundingBox(x=min(0.40 + i * 0.02, 0.65), y=0.70, width=0.30, height=0.12)
        for i in range(10)
    ]
    moving_after = fall_trajectory(still_frames=0) + crawling_away
    still_after = fall_trajectory(still_frames=10)
    moving_events = run_trajectory(moving_after, detector=permissive_detector())
    still_events = run_trajectory(still_after, detector=permissive_detector())
    assert moving_events and still_events
    assert max(e.confidence for e in still_events) > max(e.confidence for e in moving_events)


def test_short_history_is_never_judged() -> None:
    events = run_trajectory(fall_trajectory(standing_frames=0, falling_frames=3, still_frames=2))
    assert events == [], "insufficient history must not produce candidates"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"monitored_labels": ()},
        {"drop_velocity_gate": 0.0},
        {"drop_velocity_gate": 0.9, "drop_velocity_reference": 0.5},
        {"confidence_threshold": 1.5},
        {"weight_drop": -0.1},
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(VisionConfigurationError):
        FallDetectorConfig(**kwargs)  # type: ignore[arg-type]
