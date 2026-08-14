"""Zone-exit detection: the gates, the schedule, and the fail-safe (ADR-0018).

The detector accumulates dwell across frames, so these tests drive it frame
by frame exactly as the event engine does — one ``evaluate`` per tracking
result — rather than handing it a finished history.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta, timezone

import pytest
from event_fixtures import FRAME_INTERVAL_SECONDS, make_tracking_result

from guardian_edge.application.debugging.explain import TrackEvaluation
from guardian_edge.application.events.history import TrackHistoryStore
from guardian_edge.application.events.zone import ZoneExitDetector, ZoneExitDetectorConfig
from guardian_edge.domain.detection import BoundingBox
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.event import CandidateEvent, CandidateEventType
from guardian_edge.domain.zone import ScheduleWindow, Weekday, Zone, ZonePoint
from guardian_edge.ops.clock import ClockStatus

# A safe area covering the left half of the frame's lower two thirds.
SAFE_AREA = Zone(
    zone_id="play-area",
    camera_id="cam-1",
    name="Play area",
    polygon=(
        ZonePoint(0.05, 0.30),
        ZonePoint(0.50, 0.30),
        ZonePoint(0.50, 0.95),
        ZonePoint(0.05, 0.95),
    ),
)

INSIDE_X, OUTSIDE_X = 0.25, 0.80
ON_THE_LINE_X = 0.51  # past the edge, but inside the hysteresis margin
FEET_Y = 0.90

TRUSTED = ClockStatus(trusted=True, reason="synchronized", timezone_name="Asia/Tashkent")
UNTRUSTED = ClockStatus(trusted=False, reason="never synchronized")

Frame = tuple[int, float]
"""(frame step, the track's centre x) — steps are 100 ms apart."""


def frames_for(seconds: float) -> int:
    return int(seconds / FRAME_INTERVAL_SECONDS) + 1


def steady(center_x: float, seconds: float, start: int = 0) -> list[Frame]:
    """The child stays at one spot for this long, starting at frame ``start``."""
    return [(step, center_x) for step in range(start, start + frames_for(seconds))]


def next_step(frames: Sequence[Frame]) -> int:
    return frames[-1][0] + 1 if frames else 0


def box_at(center_x: float, feet_y: float = FEET_Y) -> BoundingBox:
    """A standing child whose feet (the box's bottom edge) sit at ``feet_y``."""
    width, height = 0.08, 0.30
    return BoundingBox(x=center_x - width / 2, y=feet_y - height, width=width, height=height)


def make_detector(
    zones: Sequence[Zone] = (SAFE_AREA,),
    status: ClockStatus = TRUSTED,
    config: ZoneExitDetectorConfig | None = None,
    observer: object = None,
    local_zone: timezone | None = None,
) -> ZoneExitDetector:
    return ZoneExitDetector(
        list(zones),
        lambda: status,
        config=config,
        observer=observer,  # type: ignore[arg-type]
        local_zone=local_zone,
    )


def run(
    frames: Sequence[Frame],
    detector: ZoneExitDetector | None = None,
    **detector_kwargs: object,
) -> list[CandidateEvent]:
    """Feed the frames through the detector; return every candidate raised."""
    detector = detector or make_detector(**detector_kwargs)  # type: ignore[arg-type]
    store = TrackHistoryStore()
    candidates: list[CandidateEvent] = []
    track_id = None
    for step, center_x in frames:
        result = make_tracking_result(box_at(center_x), step=step, track_id=track_id)
        track_id = result.tracks[0].track_id
        store.observe(result)
        track = result.tracks[0]
        candidate = detector.evaluate(store.history(track.track_id), track, result)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


class TestTheGates:
    def test_a_child_inside_the_safe_area_is_never_a_candidate(self) -> None:
        assert run(steady(INSIDE_X, seconds=30)) == []

    def test_a_sustained_exit_is_a_candidate(self) -> None:
        candidates = run(steady(OUTSIDE_X, seconds=20))

        assert candidates, "10 seconds outside must be reported"
        first = candidates[0]
        assert first.event_type is CandidateEventType.ZONE_EXIT
        assert {signal.name for signal in first.signals} == {
            "dwell_outside",
            "distance_past_boundary",
            "observation_consistency",
        }

    def test_the_candidate_arrives_at_the_declared_dwell_not_before(self) -> None:
        assert run(steady(OUTSIDE_X, seconds=9)) == []
        assert run(steady(OUTSIDE_X, seconds=11)) != []

    def test_a_brief_step_over_the_line_is_not_a_candidate(self) -> None:
        frames = steady(INSIDE_X, seconds=10)
        frames += steady(OUTSIDE_X, seconds=3, start=next_step(frames))
        assert run(frames) == []

    def test_standing_on_the_boundary_never_fires(self) -> None:
        # Hysteresis: a child on the line must not oscillate between
        # candidate and not, however long they stand there.
        assert run(steady(ON_THE_LINE_X, seconds=60)) == []

    def test_re_entering_restarts_the_dwell(self) -> None:
        frames = steady(OUTSIDE_X, seconds=9)
        frames += steady(INSIDE_X, seconds=1, start=next_step(frames))
        frames += steady(OUTSIDE_X, seconds=8, start=next_step(frames))
        assert run(frames) == [], "the clock restarts at the last sighting inside"

    def test_only_monitored_labels_are_evaluated(self) -> None:
        detector = make_detector()
        store = TrackHistoryStore()
        for step in range(frames_for(20)):
            result = make_tracking_result(box_at(OUTSIDE_X), step=step, label="chair")
            store.observe(result)
            track = result.tracks[0]
            assert detector.evaluate(store.history(track.track_id), track, result) is None

    def test_a_camera_without_zones_produces_nothing(self) -> None:
        elsewhere = Zone(
            zone_id="elsewhere",
            camera_id="cam-2",
            name="Other room",
            polygon=SAFE_AREA.polygon,
        )
        assert run(steady(OUTSIDE_X, seconds=20), zones=(elsewhere,)) == []


class TestAbsenceIsNeverEvidence:
    """ADR-0018 §9: a child who stops being tracked has not been seen to
    leave. Only where the polygon was drawn can catch that."""

    def test_a_track_that_vanishes_before_the_dwell_raises_nothing(self) -> None:
        # Nine seconds outside, then the tracker loses the child (no more
        # frames). Nothing may be inferred from the silence that follows.
        assert run(steady(OUTSIDE_X, seconds=9)) == []

    def test_a_gap_longer_than_the_limit_restarts_the_dwell(self) -> None:
        frames = steady(OUTSIDE_X, seconds=9)
        resume = next_step(frames) + frames_for(5)  # occluded for 5 seconds
        frames += steady(OUTSIDE_X, seconds=8, start=resume)

        assert run(frames) == [], "we never claim a child was outside while unobserved"

    def test_a_gap_within_the_limit_keeps_the_dwell_and_costs_consistency(self) -> None:
        frames = steady(OUTSIDE_X, seconds=6)
        resume = next_step(frames) + frames_for(1.0)  # a 1.1 s blink, under the 1.5 s limit
        frames += steady(OUTSIDE_X, seconds=6, start=resume)

        candidates = run(frames)

        assert candidates, "a short blink does not restart the dwell"
        consistency = next(
            signal for signal in candidates[0].signals if signal.name == "observation_consistency"
        )
        assert consistency.score < 1.0, "a bridged stretch is weaker evidence than a watched one"


class TestSchedule:
    """BASE_TIME is 12:00 UTC, so a fixed offset puts every capture at a
    chosen local hour without depending on the machine's timezone."""

    NAP_ONLY = Zone(
        zone_id="nap-area",
        camera_id="cam-1",
        name="Nap area",
        polygon=SAFE_AREA.polygon,
        active_windows=(
            ScheduleWindow(days=frozenset(Weekday), start_minute=13 * 60, end_minute=15 * 60),
        ),
    )

    AT_0900 = timezone(timedelta(hours=-3))
    AT_1400 = timezone(timedelta(hours=2))
    AT_1257 = timezone(timedelta(minutes=57))

    def test_a_zone_outside_its_hours_is_not_part_of_the_scene(self) -> None:
        assert run(steady(OUTSIDE_X, 20), zones=(self.NAP_ONLY,), local_zone=self.AT_0900) == []

    def test_the_same_exit_inside_the_hours_is_a_candidate(self) -> None:
        assert run(steady(OUTSIDE_X, 20), zones=(self.NAP_ONLY,), local_zone=self.AT_1400) != []

    def test_an_untrusted_clock_enforces_every_zone_regardless_of_hours(self) -> None:
        """ADR-0018 §5. Over-alerting costs a director one glance;
        under-alerting costs an unwatched child."""
        candidates = run(
            steady(OUTSIDE_X, 20),
            zones=(self.NAP_ONLY,),
            status=UNTRUSTED,
            local_zone=self.AT_0900,
        )
        assert candidates != []

    def test_a_clock_that_cannot_be_read_enforces_too(self) -> None:
        def exploding_clock() -> ClockStatus:
            raise RuntimeError("timesyncd is not answering")

        detector = ZoneExitDetector([self.NAP_ONLY], exploding_clock, local_zone=self.AT_0900)
        assert run(steady(OUTSIDE_X, 20), detector=detector) != []

    def test_a_stale_clock_widens_the_edges_it_never_narrows_them(self) -> None:
        stale = ClockStatus(
            trusted=True,
            reason="70 days offline",
            error_bound_seconds=5 * 60,
            timezone_name="Asia/Tashkent",
        )
        # 12:57 local — three minutes before the window opens.
        assert (
            run(steady(OUTSIDE_X, 20), zones=(self.NAP_ONLY,), local_zone=self.AT_1257) == []
        ), "precondition: a trusted clock honours the declared edge"
        assert (
            run(
                steady(OUTSIDE_X, 20),
                zones=(self.NAP_ONLY,),
                status=stale,
                local_zone=self.AT_1257,
            )
            != []
        )


class TestCooldown:
    def test_one_candidate_per_track_per_zone_per_cooldown(self) -> None:
        assert len(run(steady(OUTSIDE_X, seconds=50))) == 1

    def test_the_next_candidate_comes_after_the_cooldown(self) -> None:
        # 60 s cooldown, then the dwell must build again from zero.
        assert len(run(steady(OUTSIDE_X, seconds=100))) == 2

    def test_per_track_state_does_not_accumulate_forever(self) -> None:
        detector = make_detector()
        run(steady(OUTSIDE_X, seconds=12), detector=detector)
        assert detector._outside or detector._cooldown_until  # noqa: SLF001

        # A different child, long after the first one left the scene.
        run(steady(OUTSIDE_X, seconds=12, start=frames_for(600)), detector=detector)

        assert len(detector._cooldown_until) == 1, "the departed track was forgotten"  # noqa: SLF001
        assert len(detector._outside) <= 1  # noqa: SLF001


class TestExplanation:
    def test_every_decision_carries_a_reason(self) -> None:
        seen: list[TrackEvaluation] = []
        run(steady(INSIDE_X, seconds=20), observer=seen.append)

        assert seen, "a decision without an explanation is forbidden (docs/04)"
        assert all(evaluation.reason for evaluation in seen)
        assert any("inside safe area" in evaluation.reason for evaluation in seen)

    def test_a_schedule_rejection_names_the_hours(self) -> None:
        seen: list[TrackEvaluation] = []
        run(
            steady(OUTSIDE_X, seconds=20),
            zones=(TestSchedule.NAP_ONLY,),
            observer=seen.append,
            local_zone=TestSchedule.AT_0900,
        )

        reasons = " ".join(evaluation.reason for evaluation in seen)
        assert "is not active" in reasons
        assert "13:00–15:00" in reasons, "the director must see which hours applied"

    def test_the_candidate_explanation_names_the_zone(self) -> None:
        seen: list[TrackEvaluation] = []
        run(steady(OUTSIDE_X, seconds=20), observer=seen.append)

        candidates = [e for e in seen if e.outcome == "candidate"]
        assert candidates
        assert "Play area" in candidates[0].reason
        assert candidates[0].signals.to_dict()["zone_id"] == "play-area"

    def test_a_failing_observer_never_breaks_detection(self) -> None:
        def broken(_: TrackEvaluation) -> None:
            raise RuntimeError("recorder is down")

        assert run(steady(OUTSIDE_X, seconds=20), observer=broken) != []


class TestConfigValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"monitored_labels": ()},
            {"min_dwell_seconds": 0.0},
            {"min_dwell_seconds": 60.0, "dwell_reference_seconds": 30.0},
            {"distance_reference": 0.0},
            {"max_gap_seconds": 0.0},
            {"confidence_threshold": 1.5},
            {"weight_dwell": 0.0, "weight_distance": 0.0, "weight_consistency": 0.0},
        ],
    )
    def test_impossible_tuning_is_refused(self, overrides: dict[str, object]) -> None:
        with pytest.raises(VisionConfigurationError):
            ZoneExitDetectorConfig(**overrides)  # type: ignore[arg-type]
