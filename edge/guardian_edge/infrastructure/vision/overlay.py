"""OpenCV implementation of the OverlayRenderer port.

Draws bounding boxes, labels with confidence, FPS, and the frame timestamp
onto a *copy* of the frame buffer. Confidence is always shown (docs/04,
transparency). The original frame is never mutated — other consumers see
the same pixels the camera delivered.
"""

from __future__ import annotations

import zlib
from typing import Any

import cv2

from guardian_edge.domain.detection import DetectionResult
from guardian_edge.domain.frame import Frame

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_TEXT_COLOR = (255, 255, 255)  # white, BGR
_HUD_COLOR = (0, 0, 0)  # black background behind HUD text
_TEXT_PADDING_PX = 4
_HUD_MARGIN_PX = 10

# Distinct, colorblind-considerate box colors (BGR). A label always maps to
# the same color via CRC so videos stay visually consistent across runs.
_PALETTE = (
    (208, 146, 0),  # blue
    (64, 152, 255),  # orange
    (89, 178, 68),  # green
    (177, 122, 204),  # purple
    (39, 76, 217),  # red
    (0, 192, 255),  # amber
)


def _label_color(label: str) -> tuple[int, int, int]:
    return _PALETTE[zlib.crc32(label.encode("utf-8")) % len(_PALETTE)]


class OpenCvOverlayRenderer:
    """Renders detection overlays with OpenCV drawing primitives."""

    def __init__(self, box_thickness: int = 2, font_scale: float = 0.5) -> None:
        self._box_thickness = box_thickness
        self._font_scale = font_scale

    def render(self, frame: Frame, result: DetectionResult, fps: float) -> Any:
        image = frame.data.copy()
        for detection in result.detections:
            color = _label_color(detection.label)
            x1, y1, x2, y2 = detection.box.to_pixels(frame.width, frame.height)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, self._box_thickness)
            self._draw_caption(
                image,
                f"{detection.label} {detection.confidence:.0%}",
                x1,
                y1,
                color,
            )
        self._draw_hud(image, frame, fps)
        return image

    def _draw_caption(
        self, image: Any, text: str, box_x: int, box_y: int, color: tuple[int, int, int]
    ) -> None:
        (text_width, text_height), baseline = cv2.getTextSize(
            text, _FONT, self._font_scale, thickness=1
        )
        # Caption sits above the box; falls inside it at the frame's top edge.
        top = max(box_y - text_height - baseline - 2 * _TEXT_PADDING_PX, 0)
        bottom_right = (
            box_x + text_width + 2 * _TEXT_PADDING_PX,
            top + text_height + baseline + 2 * _TEXT_PADDING_PX,
        )
        cv2.rectangle(image, (box_x, top), bottom_right, color, cv2.FILLED)
        cv2.putText(
            image,
            text,
            (box_x + _TEXT_PADDING_PX, top + text_height + _TEXT_PADDING_PX),
            _FONT,
            self._font_scale,
            _TEXT_COLOR,
            thickness=1,
            lineType=cv2.LINE_AA,
        )

    def _draw_hud(self, image: Any, frame: Frame, fps: float) -> None:
        timestamp = frame.captured_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        self._draw_hud_line(image, f"FPS {fps:.1f}", _HUD_MARGIN_PX + 14)
        self._draw_hud_line(image, timestamp, frame.height - _HUD_MARGIN_PX)

    def _draw_hud_line(self, image: Any, text: str, baseline_y: int) -> None:
        (text_width, text_height), baseline = cv2.getTextSize(
            text, _FONT, self._font_scale, thickness=1
        )
        cv2.rectangle(
            image,
            (_HUD_MARGIN_PX - _TEXT_PADDING_PX, baseline_y - text_height - _TEXT_PADDING_PX),
            (
                _HUD_MARGIN_PX + text_width + _TEXT_PADDING_PX,
                baseline_y + baseline + _TEXT_PADDING_PX,
            ),
            _HUD_COLOR,
            cv2.FILLED,
        )
        cv2.putText(
            image,
            text,
            (_HUD_MARGIN_PX, baseline_y),
            _FONT,
            self._font_scale,
            _TEXT_COLOR,
            thickness=1,
            lineType=cv2.LINE_AA,
        )
