"""DummyDetector: deterministic synthetic detections."""

import pytest
from camera_fakes import make_frame

from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.infrastructure.vision.dummy_detector import DummyDetector


def test_same_frame_metadata_gives_identical_detections() -> None:
    detector = DummyDetector(labels=("person", "child"), detections_per_frame=3)
    frame = make_frame("cam-1", sequence=17)
    first = detector.detect(frame)
    second = detector.detect(frame)
    assert first.detections == second.detections
    assert first.model == second.model


def test_detections_move_as_sequence_advances() -> None:
    detector = DummyDetector()
    boxes = {detector.detect(make_frame("cam-1", sequence=s)).detections[0].box for s in range(10)}
    assert len(boxes) > 1, "boxes must sweep across frames, not sit still"


def test_all_detections_stay_within_frame_bounds() -> None:
    detector = DummyDetector(labels=("person",), detections_per_frame=4)
    for sequence in range(50):
        result = detector.detect(make_frame("cam-1", sequence=sequence))
        for detection in result.detections:
            assert 0.0 <= detection.box.x + detection.box.width <= 1.0
            assert 0.0 <= detection.box.y + detection.box.height <= 1.0
            assert 0.0 <= detection.confidence <= 1.0


def test_result_carries_frame_metadata_and_model_identity() -> None:
    frame = make_frame("cam-7", sequence=99)
    result = DummyDetector().detect(frame)
    assert result.camera_id == "cam-7"
    assert result.frame_id == frame.frame_id
    assert result.frame_sequence == 99
    assert result.captured_at == frame.captured_at
    assert result.correlation_id == frame.correlation_id
    assert result.model.name == "dummy-detector"
    assert result.model.version


def test_every_detection_carries_all_downstream_identifiers() -> None:
    frame = make_frame("cam-7", sequence=99)
    result = DummyDetector(detections_per_frame=3).detect(frame)
    detection_ids = {d.detection_id for d in result.detections}
    assert len(detection_ids) == 3, "detection ids must be unique within a frame"
    for detection in result.detections:
        assert detection.frame_id == frame.frame_id
        assert detection.camera_id == frame.camera_id
        assert detection.captured_at == frame.captured_at
        assert detection.correlation_id == frame.correlation_id


def test_detection_ids_differ_across_frames() -> None:
    detector = DummyDetector()
    first = detector.detect(make_frame("cam-1", sequence=1)).detections[0]
    second = detector.detect(make_frame("cam-1", sequence=1)).detections[0]
    assert first.detection_id != second.detection_id, (
        "distinct captured frames must never share detection ids"
    )


def test_labels_cycle_across_detections() -> None:
    detector = DummyDetector(labels=("person", "child"), detections_per_frame=4)
    labels = [d.label for d in detector.detect(make_frame("cam-1", sequence=1)).detections]
    assert labels == ["person", "child", "person", "child"]


def test_zero_detections_is_valid() -> None:
    detector = DummyDetector(detections_per_frame=0)
    assert detector.detect(make_frame("cam-1", sequence=1)).detections == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"labels": ()},
        {"labels": ("",)},
        {"detections_per_frame": -1},
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(VisionConfigurationError):
        DummyDetector(**kwargs)  # type: ignore[arg-type]
