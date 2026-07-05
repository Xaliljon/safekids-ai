"""Detection domain model: validation, identity, and coordinate mapping."""

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

CAPTURED_AT = datetime(2026, 7, 5, 10, 18, 0, tzinfo=timezone.utc)
FRAME_ID = uuid4()
CORRELATION_ID = uuid4()
MODEL = ModelDescriptor(name="dummy-detector", version="0.1.0")


def make_box(
    x: float = 0.25, y: float = 0.25, width: float = 0.5, height: float = 0.5
) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=width, height=height)


def make_detection(
    label: str = "person",
    confidence: float = 0.87,
    camera_id: str = "cam-1",
) -> Detection:
    return Detection(
        detection_id=uuid4(),
        frame_id=FRAME_ID,
        camera_id=camera_id,
        captured_at=CAPTURED_AT,
        correlation_id=CORRELATION_ID,
        label=label,
        confidence=confidence,
        box=make_box(),
    )


class TestBoundingBox:
    def test_accepts_valid_normalized_box(self) -> None:
        box = make_box()
        assert box.x + box.width <= 1.0

    @pytest.mark.parametrize(
        ("x", "y", "width", "height"),
        [
            (-0.1, 0.0, 0.5, 0.5),  # origin out of range
            (0.0, 1.1, 0.5, 0.5),
            (0.0, 0.0, 0.0, 0.5),  # empty
            (0.0, 0.0, 0.5, -0.5),
            (0.8, 0.0, 0.3, 0.5),  # exceeds right edge
            (0.0, 0.9, 0.5, 0.2),  # exceeds bottom edge
        ],
    )
    def test_rejects_invalid_boxes(self, x: float, y: float, width: float, height: float) -> None:
        with pytest.raises(VisionConfigurationError):
            BoundingBox(x=x, y=y, width=width, height=height)

    def test_to_pixels_maps_and_rounds(self) -> None:
        box = BoundingBox(x=0.25, y=0.5, width=0.5, height=0.25)
        assert box.to_pixels(640, 480) == (160, 240, 480, 360)

    def test_to_pixels_clamps_to_frame(self) -> None:
        box = BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0)
        x1, y1, x2, y2 = box.to_pixels(640, 480)
        assert (x1, y1) == (0, 0)
        assert (x2, y2) == (639, 479)


class TestDetection:
    def test_carries_all_downstream_identifiers(self) -> None:
        detection = make_detection()
        assert detection.detection_id
        assert detection.frame_id == FRAME_ID
        assert detection.camera_id == "cam-1"
        assert detection.captured_at == CAPTURED_AT
        assert detection.correlation_id == CORRELATION_ID

    @pytest.mark.parametrize("confidence", [-0.01, 1.01])
    def test_rejects_out_of_range_confidence(self, confidence: float) -> None:
        with pytest.raises(VisionConfigurationError):
            make_detection(confidence=confidence)

    def test_rejects_blank_label(self) -> None:
        with pytest.raises(VisionConfigurationError):
            make_detection(label="  ")


class TestDetectionResult:
    def make_result(self, detections: tuple[Detection, ...]) -> DetectionResult:
        return DetectionResult(
            camera_id="cam-1",
            frame_id=FRAME_ID,
            frame_sequence=42,
            captured_at=CAPTURED_AT,
            correlation_id=CORRELATION_ID,
            detections=detections,
            model=MODEL,
            inference_ms=0.0,
        )

    def test_is_immutable_and_traceable(self) -> None:
        result = self.make_result((make_detection(),))
        assert result.model.name == "dummy-detector", "results must name their model (docs/04)"
        assert isinstance(result.detections, tuple)
        with pytest.raises(AttributeError):
            result.camera_id = "other"  # type: ignore[misc]

    def test_rejects_detection_from_another_frame(self) -> None:
        foreign = Detection(
            detection_id=uuid4(),
            frame_id=uuid4(),  # different frame
            camera_id="cam-1",
            captured_at=CAPTURED_AT,
            correlation_id=CORRELATION_ID,
            label="person",
            confidence=0.9,
            box=make_box(),
        )
        with pytest.raises(VisionConfigurationError, match="does not belong"):
            self.make_result((foreign,))

    def test_rejects_detection_from_another_camera(self) -> None:
        with pytest.raises(VisionConfigurationError, match="does not belong"):
            self.make_result((make_detection(camera_id="cam-2"),))
