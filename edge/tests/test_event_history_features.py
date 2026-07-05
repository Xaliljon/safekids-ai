"""Track history store and motion/shape features."""

from uuid import uuid4

import pytest
from event_fixtures import (
    LYING,
    STANDING,
    fall_trajectory,
    make_tracking_result,
    walking_trajectory,
)

from guardian_edge.application.events.features import (
    average_speed,
    baseline_aspect_ratio,
    current_aspect_ratio,
    duration_seconds,
    ground_proximity,
    peak_downward_velocity,
    stillness_score,
)
from guardian_edge.application.events.history import TrackHistoryStore, TrackObservation
from guardian_edge.domain.track import TrackState


def build_history(boxes: list, track_id: object = None) -> tuple[TrackObservation, ...]:
    store = TrackHistoryStore()
    track_id = track_id or uuid4()
    for step, box in enumerate(boxes):
        store.observe(make_tracking_result(box, step, track_id=track_id))
    return store.history(track_id)  # type: ignore[arg-type]


class TestHistoryStore:
    def test_records_confirmed_observations_in_order(self) -> None:
        history = build_history(walking_trajectory(10))
        assert len(history) == 10
        assert history[0].captured_at < history[-1].captured_at

    def test_ignores_lost_tracks_predicted_boxes(self) -> None:
        store = TrackHistoryStore()
        track_id = uuid4()
        store.observe(make_tracking_result(STANDING, 0, track_id=track_id))
        store.observe(make_tracking_result(STANDING, 1, track_id=track_id, state=TrackState.LOST))
        assert len(store.history(track_id)) == 1, "predictions are not evidence"

    def test_window_prunes_old_observations(self) -> None:
        store = TrackHistoryStore(window_seconds=1.0)
        track_id = uuid4()
        for step in range(30):  # 3 seconds at 0.1s per frame
            store.observe(make_tracking_result(STANDING, step, track_id=track_id))
        history = store.history(track_id)
        assert duration_seconds(history) <= 1.0 + 1e-9

    def test_stale_tracks_are_forgotten(self) -> None:
        store = TrackHistoryStore(retention_seconds=2.0)
        old_track = uuid4()
        store.observe(make_tracking_result(STANDING, 0, track_id=old_track))
        # Another track keeps observing long after the first disappeared.
        for step in range(25, 50):
            store.observe(make_tracking_result(STANDING, step, track_id=uuid4()))
        assert store.history(old_track) == ()


class TestFeatures:
    def test_peak_downward_velocity_on_a_fall(self) -> None:
        history = build_history(fall_trajectory())
        velocity = peak_downward_velocity(history, window_seconds=10.0)
        # Center drops ~0.285 normalized units in ~0.5s.
        assert velocity == pytest.approx(0.57, rel=0.25)

    def test_no_downward_velocity_when_walking(self) -> None:
        history = build_history(walking_trajectory())
        assert peak_downward_velocity(history, window_seconds=10.0) == pytest.approx(0.0, abs=0.02)

    def test_velocity_needs_at_least_two_spaced_observations(self) -> None:
        history = build_history([STANDING])
        assert peak_downward_velocity(history, window_seconds=10.0) == 0.0

    def test_aspect_ratio_flip_on_a_fall(self) -> None:
        history = build_history(fall_trajectory())
        assert baseline_aspect_ratio(history) == pytest.approx(0.286, abs=0.01)
        assert current_aspect_ratio(history) == pytest.approx(2.5, abs=0.01)

    def test_ground_proximity_is_the_lower_edge(self) -> None:
        history = build_history(fall_trajectory())
        assert ground_proximity(history) == pytest.approx(LYING.y + LYING.height, abs=1e-6)

    def test_stillness_after_a_fall_and_motion_while_walking(self) -> None:
        fallen = build_history(fall_trajectory(still_frames=15))
        walking = build_history(walking_trajectory())
        assert stillness_score(fallen, window_seconds=1.0, max_speed=0.06) == pytest.approx(
            1.0, abs=0.05
        )
        assert stillness_score(walking, window_seconds=1.0, max_speed=0.06) == 0.0

    def test_average_speed_of_a_walker(self) -> None:
        history = build_history(walking_trajectory())
        # 0.015 units per 0.1s = 0.15 units/s horizontally.
        assert average_speed(history, window_seconds=10.0) == pytest.approx(0.15, rel=0.1)
