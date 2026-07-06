"""AI-analysis overlay for evidence clips (ADR-0017).

Draws what the AI concluded onto the raw frames at EXPORT time — never on
the hot path: bounding boxes, track ids, confidence, a clip timeline with
the incident marker, and a timestamp. The director can switch between the
original view and this analysis view to understand exactly why the AI
raised the incident.
"""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

from guardian_edge.infrastructure.evidence.rings import TrackSnapshot

_BOX_COLOR = {"confirmed": (80, 200, 60), "tentative": (60, 180, 220), "lost": (60, 60, 220)}
_MARKER_COLOR = (40, 40, 220)  # BGR red — the incident moment
_BAR_BG = (30, 30, 30)
_BAR_FG = (200, 200, 200)


def render_overlay(
    image: np.ndarray,
    snapshot: TrackSnapshot | None,
    captured_at: datetime,
    clip_start: datetime,
    clip_end: datetime,
    incident_at: datetime,
) -> np.ndarray:
    """One overlay frame: boxes + ids + confidence + timeline + marker."""
    canvas = image.copy()
    height, width = canvas.shape[:2]

    if snapshot is not None:
        for display_id, confidence, x, y, w, h, state in snapshot.tracks:
            color = _BOX_COLOR.get(state, (200, 200, 200))
            left, top = int(x * width), int(y * height)
            right, bottom = int((x + w) * width), int((y + h) * height)
            cv2.rectangle(canvas, (left, top), (right, bottom), color, 2)
            label = f"#{display_id} {confidence:.0%} {state}"
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(canvas, (left, top - text_h - 8), (left + text_w + 6, top), color, -1)
            cv2.putText(
                canvas,
                label,
                (left + 3, top - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    # Timestamp (top-left) — evidence must be temporally attributable.
    stamp = captured_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    cv2.putText(
        canvas, stamp, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA
    )
    cv2.putText(
        canvas,
        "AI ANALYSIS",
        (width - 130, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (60, 180, 220),
        1,
        cv2.LINE_AA,
    )

    # Clip timeline (bottom): progress bar + red incident marker.
    total = max((clip_end - clip_start).total_seconds(), 0.001)
    progress = min(max((captured_at - clip_start).total_seconds() / total, 0.0), 1.0)
    marker = min(max((incident_at - clip_start).total_seconds() / total, 0.0), 1.0)
    bar_top = height - 14
    cv2.rectangle(canvas, (10, bar_top), (width - 10, height - 6), _BAR_BG, -1)
    cv2.rectangle(
        canvas, (10, bar_top), (10 + int((width - 20) * progress), height - 6), _BAR_FG, -1
    )
    marker_x = 10 + int((width - 20) * marker)
    cv2.rectangle(
        canvas, (marker_x - 2, bar_top - 6), (marker_x + 2, height - 4), _MARKER_COLOR, -1
    )
    return canvas
