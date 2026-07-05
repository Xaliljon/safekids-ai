"""Non-maximum suppression implementations."""

from __future__ import annotations

from collections.abc import Sequence

from guardian_edge.application.vision.ports import RawDetection


class GreedyNms:
    """Greedy IoU suppression: keep the most confident candidate, drop
    overlapping weaker ones.

    Class-aware by default (a person box never suppresses a child box).
    Pure Python — trivial at the tens-of-boxes scale a frame produces;
    a vectorized implementation can replace this behind the same port if
    profiling ever demands it.
    """

    def __init__(self, class_aware: bool = True) -> None:
        self._class_aware = class_aware

    def suppress(
        self, candidates: Sequence[RawDetection], iou_threshold: float
    ) -> list[RawDetection]:
        ordered = sorted(candidates, key=lambda c: c.confidence, reverse=True)
        kept: list[RawDetection] = []
        for candidate in ordered:
            if not any(self._suppresses(winner, candidate, iou_threshold) for winner in kept):
                kept.append(candidate)
        return kept

    def _suppresses(self, winner: RawDetection, candidate: RawDetection, threshold: float) -> bool:
        if self._class_aware and winner.label_index != candidate.label_index:
            return False
        return winner.box.intersection_over_union(candidate.box) > threshold
