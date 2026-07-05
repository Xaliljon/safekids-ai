"""ByteTrack: stable ids, lifecycle, BYTE recovery, identity preservation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import TrackState
from guardian_edge.infrastructure.tracking.bytetrack import ByteTrackConfig, ByteTracker

MODEL = ModelDescriptor(name="test-detector", version="1.0.0")
CAPTURED_AT = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def make_result(
    boxes: list[tuple[float, float, float, str]],  # (x, y, confidence, label)
    camera_id: str = "cam-1",
    sequence: int = 1,
    size: float = 0.2,
) -> DetectionResult:
    frame = Frame(
        camera_id=camera_id,
        sequence=sequence,
        captured_at=CAPTURED_AT,
        width=640,
        height=480,
        data=object(),
    )
    detections = tuple(
        Detection(
            detection_id=uuid4(),
            frame_id=frame.frame_id,
            camera_id=camera_id,
            captured_at=CAPTURED_AT,
            correlation_id=frame.correlation_id,
            label=label,
            confidence=confidence,
            box=BoundingBox(x=x, y=y, width=size, height=size),
        )
        for x, y, confidence, label in boxes
    )
    return DetectionResult(
        camera_id=camera_id,
        frame_id=frame.frame_id,
        frame_sequence=sequence,
        captured_at=CAPTURED_AT,
        correlation_id=frame.correlation_id,
        detections=detections,
        model=MODEL,
        inference_ms=1.0,
    )


def fast_config(confirm_after: int = 3, max_lost: int = 5) -> ByteTrackConfig:
    return ByteTrackConfig(confirm_after=confirm_after, max_lost_frames=max_lost)


def test_moving_object_keeps_one_stable_id() -> None:
    tracker = ByteTracker(fast_config())
    track_ids = set()
    display_ids = set()
    for step in range(20):
        x = 0.1 + step * 0.02  # smooth motion
        result = tracker.update(make_result([(x, 0.4, 0.9, "person")], sequence=step))
        assert len(result.tracks) == 1
        track_ids.add(result.tracks[0].track_id)
        display_ids.add(result.tracks[0].display_id)
    assert len(track_ids) == 1, "one physical object must keep one track id"
    assert len(display_ids) == 1


def test_lifecycle_tentative_confirmed_lost_removed() -> None:
    tracker = ByteTracker(fast_config(confirm_after=3, max_lost=2))
    box = [(0.4, 0.4, 0.9, "person")]
    assert tracker.update(make_result(box)).tracks[0].state is TrackState.TENTATIVE
    assert tracker.update(make_result(box)).tracks[0].state is TrackState.TENTATIVE
    assert tracker.update(make_result(box)).tracks[0].state is TrackState.CONFIRMED
    # Object disappears: confirmed -> lost (position predicted), then removed.
    assert tracker.update(make_result([])).tracks[0].state is TrackState.LOST
    assert tracker.update(make_result([])).tracks[0].state is TrackState.LOST
    assert tracker.update(make_result([])).tracks == ()


def test_tentative_track_that_vanishes_is_removed_immediately() -> None:
    tracker = ByteTracker(fast_config(confirm_after=3))
    tracker.update(make_result([(0.4, 0.4, 0.9, "person")]))
    assert tracker.update(make_result([])).tracks == ()


def test_byte_association_rescues_track_through_low_confidence() -> None:
    """The ByteTrack idea: an occluded object's low-score box keeps its id."""
    tracker = ByteTracker(fast_config(confirm_after=2))
    for step in range(3):
        result = tracker.update(make_result([(0.4, 0.4, 0.9, "person")], sequence=step))
    original = result.tracks[0].track_id
    # Occlusion: confidence collapses below high_threshold but above low_threshold.
    result = tracker.update(make_result([(0.41, 0.4, 0.25, "person")], sequence=3))
    assert len(result.tracks) == 1
    assert result.tracks[0].track_id == original, "low-score box must rescue, not respawn"
    assert result.tracks[0].state is TrackState.CONFIRMED


def test_low_confidence_detections_never_spawn_tracks() -> None:
    tracker = ByteTracker(fast_config())
    result = tracker.update(make_result([(0.4, 0.4, 0.3, "person")]))
    assert result.tracks == ()


def test_lost_track_is_reacquired_with_same_id() -> None:
    tracker = ByteTracker(fast_config(confirm_after=2, max_lost=5))
    for step in range(3):
        result = tracker.update(make_result([(0.4, 0.4, 0.9, "person")], sequence=step))
    original = result.tracks[0].track_id
    tracker.update(make_result([]))  # one missed frame -> LOST
    result = tracker.update(make_result([(0.42, 0.41, 0.9, "person")], sequence=5))
    assert result.tracks[0].track_id == original
    assert result.tracks[0].state is TrackState.CONFIRMED


def test_two_separated_objects_keep_distinct_ids() -> None:
    tracker = ByteTracker(fast_config(confirm_after=2))
    for step in range(10):
        left = (0.1 + step * 0.01, 0.2, 0.9, "person")
        right = (0.7 - step * 0.01, 0.6, 0.9, "person")
        result = tracker.update(make_result([left, right], sequence=step))
    ids = {track.display_id for track in result.tracks}
    assert len(ids) == 2
    assert all(track.state is TrackState.CONFIRMED for track in result.tracks)


def test_association_is_label_aware() -> None:
    """A child track is never continued by an overlapping non-child box."""
    tracker = ByteTracker(fast_config(confirm_after=1))
    first = tracker.update(make_result([(0.4, 0.4, 0.9, "child")]))
    child_id = first.tracks[0].track_id
    result = tracker.update(make_result([(0.4, 0.4, 0.9, "chair")]))
    labels = {track.label: track for track in result.tracks}
    assert "chair" in labels
    assert labels["chair"].track_id != child_id


def test_cameras_are_tracked_independently() -> None:
    tracker = ByteTracker(fast_config(confirm_after=1))
    a = tracker.update(make_result([(0.4, 0.4, 0.9, "person")], camera_id="cam-a"))
    b = tracker.update(make_result([(0.4, 0.4, 0.9, "person")], camera_id="cam-b"))
    assert a.tracks[0].track_id != b.tracks[0].track_id
    assert a.tracks[0].display_id != b.tracks[0].display_id


def test_adr_0007_identity_is_preserved() -> None:
    tracker = ByteTracker(fast_config(confirm_after=1))
    result_in = make_result([(0.4, 0.4, 0.9, "person")])
    result_out = tracker.update(result_in)
    assert result_out.correlation_id == result_in.correlation_id, "propagate, never regenerate"
    assert result_out.frame_id == result_in.frame_id
    assert result_out.captured_at == result_in.captured_at
    track = result_out.tracks[0]
    assert track.last_detection == result_in.detections[0], "full detection evidence kept"
    assert result_out.tracker.name == "bytetrack"
    assert result_out.detection_model == MODEL
    assert result_out.tracking_ms >= 0.0


def test_predicted_position_moves_while_lost() -> None:
    tracker = ByteTracker(fast_config(confirm_after=2, max_lost=10))
    for step in range(10):
        result = tracker.update(make_result([(0.1 + step * 0.02, 0.4, 0.9, "person")]))
    seen_x = result.tracks[0].box.x
    lost = tracker.update(make_result([]))
    assert lost.tracks[0].state is TrackState.LOST
    assert lost.tracks[0].box.x > seen_x - 0.005, "lost track must coast, not jump back"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"low_threshold": 0.6, "high_threshold": 0.5},
        {"match_iou": 0.0},
        {"confirm_after": 0},
        {"max_lost_frames": 0},
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(VisionConfigurationError):
        ByteTrackConfig(**kwargs)  # type: ignore[arg-type]
