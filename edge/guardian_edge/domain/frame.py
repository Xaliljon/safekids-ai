"""Captured video frame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Frame:
    """A single captured frame plus capture metadata.

    ``data`` is an opaque pixel buffer owned by the capture backend (for the
    OpenCV backend, a ``numpy.ndarray`` in BGR order). The domain never
    inspects pixels; only downstream consumers (the future AI pipeline) do.
    Frames stay in memory and are never persisted by the camera service.
    """

    camera_id: str
    sequence: int
    captured_at: datetime
    width: int
    height: int
    data: Any
