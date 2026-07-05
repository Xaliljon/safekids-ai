"""Captured video frame."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Frame:
    """A single captured frame plus capture metadata.

    Identity is minted here, at capture, exactly once (ADR-0007):

    - ``frame_id`` identifies this captured image globally (``sequence`` is
      only a human-readable per-stream counter and resets on reconnect).
    - ``correlation_id`` is the trace token for everything this capture
      causes downstream — detections, tracks, risk events, notifications,
      analytics all carry it. Downstream stages propagate it and never
      regenerate it.

    ``data`` is an opaque pixel buffer owned by the capture backend (for the
    OpenCV backend, a ``numpy.ndarray`` in BGR order). The domain never
    inspects pixels; only downstream consumers (the AI pipeline) do.
    Frames stay in memory and are never persisted by the camera service.
    """

    camera_id: str
    sequence: int
    captured_at: datetime
    width: int
    height: int
    data: Any
    frame_id: UUID = field(default_factory=uuid4)
    correlation_id: UUID = field(default_factory=uuid4)
