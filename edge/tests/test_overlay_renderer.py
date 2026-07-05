"""OpenCV overlay renderer: draws on a copy, never mutates the source."""

from datetime import datetime, timezone
from uuid import uuid4

import numpy as np

from guardian_edge.domain.detection import (
    BoundingBox,
    Detection,
    DetectionResult,
    ModelDescriptor,
)
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.vision.overlay import OpenCvOverlayRenderer

WIDTH, HEIGHT = 320, 240
PERSON_BOX = BoundingBox(x=0.25, y=0.25, width=0.5, height=0.5)


def make_image_frame(sequence: int = 1) -> Frame:
    return Frame(
        camera_id="cam-1",
        sequence=sequence,
        captured_at=datetime(2026, 7, 5, 10, 18, 0, tzinfo=timezone.utc),
        width=WIDTH,
        height=HEIGHT,
        data=np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8),
    )


def make_result(frame: Frame, boxes: tuple[BoundingBox, ...]) -> DetectionResult:
    detections = tuple(
        Detection(
            detection_id=uuid4(),
            frame_id=frame.frame_id,
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            correlation_id=frame.correlation_id,
            label="person",
            confidence=0.87,
            box=box,
        )
        for box in boxes
    )
    return DetectionResult(
        camera_id=frame.camera_id,
        frame_id=frame.frame_id,
        frame_sequence=frame.sequence,
        captured_at=frame.captured_at,
        correlation_id=frame.correlation_id,
        detections=detections,
        model=ModelDescriptor(name="dummy-detector", version="0.1.0"),
        inference_ms=0.0,
    )


def test_draws_boxes_and_hud_onto_copy() -> None:
    frame = make_image_frame()
    rendered = OpenCvOverlayRenderer().render(frame, make_result(frame, (PERSON_BOX,)), fps=24.9)
    assert rendered is not frame.data, "renderer must return a copy"
    assert not np.array_equal(rendered, frame.data), "something must be drawn"
    assert frame.data.sum() == 0, "original frame must never be mutated"
    assert rendered.shape == frame.data.shape
    assert rendered.dtype == frame.data.dtype


def test_box_edges_are_drawn_at_expected_pixels() -> None:
    frame = make_image_frame()
    rendered = OpenCvOverlayRenderer(box_thickness=1).render(
        frame, make_result(frame, (PERSON_BOX,)), fps=0.0
    )
    x1, y1, x2, _y2 = PERSON_BOX.to_pixels(WIDTH, HEIGHT)
    assert rendered[y1, (x1 + x2) // 2].any(), "top box edge must be colored"


def test_hud_is_drawn_even_without_detections() -> None:
    frame = make_image_frame()
    rendered = OpenCvOverlayRenderer().render(frame, make_result(frame, ()), fps=12.5)
    assert not np.array_equal(rendered, frame.data), "FPS and timestamp must render"
    top_strip = rendered[: HEIGHT // 4]
    bottom_strip = rendered[3 * HEIGHT // 4 :]
    assert top_strip.any(), "FPS text expected near the top"
    assert bottom_strip.any(), "timestamp expected near the bottom"


def test_full_frame_box_does_not_crash_at_edges() -> None:
    frame = make_image_frame()
    full = BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0)
    rendered = OpenCvOverlayRenderer().render(frame, make_result(frame, (full,)), fps=1.0)
    assert rendered.shape == frame.data.shape
