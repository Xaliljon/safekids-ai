"""OpenCV implementation of the OverlayRenderer port.

Draws bounding boxes, labels with confidence, FPS, and the frame timestamp
onto a *copy* of the frame buffer. Confidence is always shown (docs/04,
transparency). The original frame is never mutated — other consumers see
the same pixels the camera delivered.
"""

from __future__ import annotations

from typing import Any

import cv2

from guardian_edge.domain.detection import DetectionResult
from guardian_edge.domain.frame import Frame
from guardian_edge.infrastructure.vision.drawing import (
    HUD_MARGIN_PX,
    draw_caption,
    draw_hud_line,
    label_color,
)


class OpenCvOverlayRenderer:
    """Renders detection overlays with OpenCV drawing primitives."""

    def __init__(self, box_thickness: int = 2, font_scale: float = 0.5) -> None:
        self._box_thickness = box_thickness
        self._font_scale = font_scale

    def render(self, frame: Frame, result: DetectionResult, fps: float) -> Any:
        image = frame.data.copy()
        for detection in result.detections:
            color = label_color(detection.label)
            x1, y1, x2, y2 = detection.box.to_pixels(frame.width, frame.height)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, self._box_thickness)
            draw_caption(
                image,
                f"{detection.label} {detection.confidence:.0%}",
                x1,
                y1,
                color,
                self._font_scale,
            )
        draw_hud_line(image, f"FPS {fps:.1f}", HUD_MARGIN_PX + 14, self._font_scale)
        draw_hud_line(
            image,
            frame.captured_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            frame.height - HUD_MARGIN_PX,
            self._font_scale,
        )
        return image
