"""Per-track observation history (track + motion + shape history).

Stores a bounded time window of geometry per track: positions over time
(motion history), boxes over time (aspect-ratio history). CONFIRMED
observations only — LOST tracks carry *predicted* boxes, and predictions
must never masquerade as evidence for a safety event.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from guardian_edge.domain.detection import BoundingBox
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.track import TrackingResult, TrackState

DEFAULT_WINDOW_SECONDS = 6.0
DEFAULT_MAX_OBSERVATIONS = 120
DEFAULT_RETENTION_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class TrackObservation:
    """One confirmed sighting of a track."""

    captured_at: datetime
    frame_sequence: int
    box: BoundingBox

    @property
    def center_x(self) -> float:
        return self.box.x + self.box.width / 2.0

    @property
    def center_y(self) -> float:
        return self.box.y + self.box.height / 2.0

    @property
    def bottom(self) -> float:
        """Lower edge in normalized coordinates (1.0 = bottom of frame)."""
        return self.box.y + self.box.height

    @property
    def aspect_ratio(self) -> float:
        """width / height: standing people < 1, lying people > 1."""
        return self.box.width / self.box.height


class TrackHistoryStore:
    """Bounded observation history per track, pruned by time and absence."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_observations: int = DEFAULT_MAX_OBSERVATIONS,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
    ) -> None:
        if window_seconds <= 0 or retention_seconds <= 0 or max_observations < 2:
            raise VisionConfigurationError("history window/retention/size must be positive")
        self._window_seconds = window_seconds
        self._max_observations = max_observations
        self._retention_seconds = retention_seconds
        self._histories: dict[UUID, deque[TrackObservation]] = {}
        self._last_seen: dict[UUID, datetime] = {}

    def observe(self, result: TrackingResult) -> None:
        """Record this frame's confirmed tracks and prune stale histories."""
        for track in result.tracks:
            if track.state is not TrackState.CONFIRMED:
                continue
            history = self._histories.get(track.track_id)
            if history is None:
                history = deque(maxlen=self._max_observations)
                self._histories[track.track_id] = history
            history.append(
                TrackObservation(
                    captured_at=result.captured_at,
                    frame_sequence=result.frame_sequence,
                    box=track.box,
                )
            )
            self._last_seen[track.track_id] = result.captured_at
            self._prune_window(history, result.captured_at)
        self._prune_stale(result.captured_at)

    def history(self, track_id: UUID) -> tuple[TrackObservation, ...]:
        """Observations for one track, oldest first."""
        return tuple(self._histories.get(track_id, ()))

    def drop(self, track_id: UUID) -> None:
        self._histories.pop(track_id, None)
        self._last_seen.pop(track_id, None)

    def __len__(self) -> int:
        return len(self._histories)

    def _prune_window(self, history: deque[TrackObservation], now: datetime) -> None:
        while history and (now - history[0].captured_at).total_seconds() > self._window_seconds:
            history.popleft()

    def _prune_stale(self, now: datetime) -> None:
        stale = [
            track_id
            for track_id, last_seen in self._last_seen.items()
            if (now - last_seen).total_seconds() > self._retention_seconds
        ]
        for track_id in stale:
            self.drop(track_id)
