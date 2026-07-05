"""DetectionResult mapper: labels, identity stamping, strictness."""

import pytest
from camera_fakes import make_frame

from guardian_edge.application.vision.mapper import DetectionResultMapper
from guardian_edge.application.vision.ports import RawDetection
from guardian_edge.domain.detection import BoundingBox, ModelDescriptor
from guardian_edge.domain.errors import DetectorError

MODEL = ModelDescriptor(name="any-model", version="2.0.0")
BOX = BoundingBox(x=0.1, y=0.1, width=0.3, height=0.3)


def make_mapper() -> DetectionResultMapper:
    return DetectionResultMapper(labels=("person", "child"), model=MODEL)


def test_maps_candidates_with_full_identity() -> None:
    frame = make_frame("cam-1", 7)
    result = make_mapper().map(
        frame,
        [RawDetection(label_index=1, confidence=0.8, box=BOX)],
        inference_ms=12.3456,
    )
    assert result.camera_id == "cam-1"
    assert result.frame_id == frame.frame_id
    assert result.correlation_id == frame.correlation_id
    assert result.model == MODEL
    assert result.inference_ms == 12.346
    detection = result.detections[0]
    assert detection.label == "child"
    assert detection.confidence == 0.8
    assert detection.box == BOX
    assert detection.frame_id == frame.frame_id
    assert detection.correlation_id == frame.correlation_id
    assert detection.captured_at == frame.captured_at


def test_each_detection_gets_its_own_uuid() -> None:
    frame = make_frame("cam-1", 7)
    candidates = [RawDetection(label_index=0, confidence=0.9, box=BOX) for _ in range(3)]
    result = make_mapper().map(frame, candidates, inference_ms=1.0)
    assert len({d.detection_id for d in result.detections}) == 3


def test_empty_candidates_map_to_empty_result() -> None:
    result = make_mapper().map(make_frame("cam-1", 7), [], inference_ms=1.0)
    assert result.detections == ()


def test_out_of_range_label_index_refuses_to_guess() -> None:
    frame = make_frame("cam-1", 7)
    with pytest.raises(DetectorError, match="refusing to guess"):
        make_mapper().map(
            frame,
            [RawDetection(label_index=2, confidence=0.9, box=BOX)],
            inference_ms=1.0,
        )
    with pytest.raises(DetectorError):
        make_mapper().map(
            frame,
            [RawDetection(label_index=-1, confidence=0.9, box=BOX)],
            inference_ms=1.0,
        )
