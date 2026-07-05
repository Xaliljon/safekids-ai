"""Shared OpenCV drawing primitives for overlay renderers."""

from __future__ import annotations

import zlib
from typing import Any

import cv2

FONT = cv2.FONT_HERSHEY_SIMPLEX
TEXT_COLOR = (255, 255, 255)  # white, BGR
HUD_COLOR = (0, 0, 0)  # black background behind HUD text
TEXT_PADDING_PX = 4
HUD_MARGIN_PX = 10

# Distinct, colorblind-considerate colors (BGR).
PALETTE = (
    (208, 146, 0),  # blue
    (64, 152, 255),  # orange
    (89, 178, 68),  # green
    (177, 122, 204),  # purple
    (39, 76, 217),  # red
    (0, 192, 255),  # amber
)


def label_color(label: str) -> tuple[int, int, int]:
    """Stable color per label (CRC-indexed) — consistent across runs."""
    return PALETTE[zlib.crc32(label.encode("utf-8")) % len(PALETTE)]


def index_color(index: int) -> tuple[int, int, int]:
    """Stable color per small integer (track display ids)."""
    return PALETTE[index % len(PALETTE)]


def draw_caption(
    image: Any,
    text: str,
    box_x: int,
    box_y: int,
    color: tuple[int, int, int],
    font_scale: float = 0.5,
) -> None:
    """Filled caption anchored above a box (inside it at the frame's top edge)."""
    (text_width, text_height), baseline = cv2.getTextSize(text, FONT, font_scale, thickness=1)
    top = max(box_y - text_height - baseline - 2 * TEXT_PADDING_PX, 0)
    bottom_right = (
        box_x + text_width + 2 * TEXT_PADDING_PX,
        top + text_height + baseline + 2 * TEXT_PADDING_PX,
    )
    cv2.rectangle(image, (box_x, top), bottom_right, color, cv2.FILLED)
    cv2.putText(
        image,
        text,
        (box_x + TEXT_PADDING_PX, top + text_height + TEXT_PADDING_PX),
        FONT,
        font_scale,
        TEXT_COLOR,
        thickness=1,
        lineType=cv2.LINE_AA,
    )


def draw_hud_line(image: Any, text: str, baseline_y: int, font_scale: float = 0.5) -> None:
    """One line of HUD text (FPS, timestamp) on a black background."""
    (text_width, text_height), baseline = cv2.getTextSize(text, FONT, font_scale, thickness=1)
    cv2.rectangle(
        image,
        (HUD_MARGIN_PX - TEXT_PADDING_PX, baseline_y - text_height - TEXT_PADDING_PX),
        (HUD_MARGIN_PX + text_width + TEXT_PADDING_PX, baseline_y + baseline + TEXT_PADDING_PX),
        HUD_COLOR,
        cv2.FILLED,
    )
    cv2.putText(
        image,
        text,
        (HUD_MARGIN_PX, baseline_y),
        FONT,
        font_scale,
        TEXT_COLOR,
        thickness=1,
        lineType=cv2.LINE_AA,
    )
