"""OpenCV implementation of the TrackOverlayRenderer port.

Draws persistent track identities: each confirmed track keeps one color
across its whole life and is captioned "#<id> <label> <confidence>".
LOST tracks (position predicted through occlusion) draw as thin gray boxes
so operators can see the tracker holding an identity. The original frame
buffer is never mutated.
"""

from __future__ import annotations

from typing import Any

import cv2

from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import TrackingResult, TrackState
from guardian_edge.infrastructure.vision.drawing import (
    HUD_MARGIN_PX,
    draw_caption,
    draw_hud_line,
    index_color,
)

_LOST_COLOR = (128, 128, 128)  # gray, BGR


class OpenCvTrackOverlayRenderer:
    """Renders tracking results with stable per-track colors."""

    def __init__(self, box_thickness: int = 2, font_scale: float = 0.5) -> None:
        self._box_thickness = box_thickness
        self._font_scale = font_scale

    def render(self, frame: Frame, result: TrackingResult, fps: float) -> Any:
        image = frame.data.copy()
        confirmed = 0
        for track in result.tracks:
            x1, y1, x2, y2 = track.box.to_pixels(frame.width, frame.height)
            if track.state is TrackState.CONFIRMED:
                confirmed += 1
                color = index_color(track.display_id)
                cv2.rectangle(image, (x1, y1), (x2, y2), color, self._box_thickness)
                draw_caption(
                    image,
                    f"#{track.display_id} {track.label} {track.confidence:.0%}",
                    x1,
                    y1,
                    color,
                    self._font_scale,
                )
            elif track.state is TrackState.LOST:
                cv2.rectangle(image, (x1, y1), (x2, y2), _LOST_COLOR, 1)
        draw_hud_line(
            image,
            f"FPS {fps:.1f}  tracks {confirmed}",
            HUD_MARGIN_PX + 14,
            self._font_scale,
        )
        draw_hud_line(
            image,
            frame.captured_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            frame.height - HUD_MARGIN_PX,
            self._font_scale,
        )
        return image
