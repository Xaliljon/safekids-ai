"""Ports (interfaces) of the vision pipeline.

``Detector`` is the task-level port the pipeline drives: frame in,
DetectionResult out. This is all the pipeline ever knows about AI
(ADR-0006). Real detectors compose the runtime-level ``InferenceEngine``
port from ``guardian_edge.application.inference.ports`` (ADR-0008) with
task-specific pre/post-processing.

Dependencies point inward: this module imports domain only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from guardian_edge.domain.detection import BoundingBox, DetectionResult, ModelDescriptor
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.track import TrackingResult


class Detector(Protocol):
    """Task-level detection: one frame in, one result out."""

    @property
    def descriptor(self) -> ModelDescriptor:
        """Identity of the model behind this detector (traceability, docs/04)."""
        ...

    def detect(self, frame: Frame) -> DetectionResult:
        """Run detection on one frame.

        Must be synchronous and bounded in time; raises DetectorError (or
        any exception — the pipeline isolates failures) when a frame cannot
        be processed.
        """
        ...


@dataclass(frozen=True, slots=True)
class RawDetection:
    """A model output candidate — before thresholding, NMS, and mapping.

    ``label_index`` is model-space (an index into the detector's label
    list); it becomes a human label only in the DetectionResult mapper.
    """

    label_index: int
    confidence: float
    box: BoundingBox


@dataclass(frozen=True, slots=True)
class PreprocessedFrame:
    """Named tensors ready for the engine, plus whatever context the
    matching decoder needs (scale factors, original size, …).

    ``meta`` is produced by a Preprocessor and consumed only by the
    OutputDecoder of the same model family — the detector core never
    inspects it.
    """

    inputs: Mapping[str, Any]
    meta: Any = None


class Preprocessor(Protocol):
    """Turns a captured frame into the tensors one model family expects."""

    def preprocess(self, frame: Frame) -> PreprocessedFrame:
        """Raises DetectorError when the frame cannot be converted."""
        ...


class OutputDecoder(Protocol):
    """Turns one model family's raw output tensors into RawDetections."""

    def decode(self, outputs: Mapping[str, Any], meta: Any) -> Sequence[RawDetection]:
        """Boxes must come back normalized to [0, 1] in frame space.

        Raises DetectorError when the outputs cannot be decoded.
        """
        ...


class NonMaxSuppression(Protocol):
    """Removes duplicate candidates that cover the same object."""

    def suppress(
        self, candidates: Sequence[RawDetection], iou_threshold: float
    ) -> list[RawDetection]: ...


class Tracker(Protocol):
    """Associates detections across frames into persistent tracks (ADR-0011).

    Called by the vision pipeline once per processed frame, on the single
    inference worker thread — implementations hold per-camera state and
    need not be thread-safe. A tracker that raises loses that frame's
    tracking only; detections still flow.
    """

    @property
    def descriptor(self) -> ModelDescriptor:
        """Identity of the tracking algorithm (traceability, docs/04)."""
        ...

    def update(self, result: DetectionResult) -> TrackingResult:
        """Advance tracking with one frame's detections."""
        ...


class TrackConsumer(Protocol):
    """Receives every tracking result (the future risk engine attaches here)."""

    def __call__(self, result: TrackingResult) -> None: ...


class TrackOverlayRenderer(Protocol):
    """Draws tracking results onto a copy of a frame's pixel buffer."""

    def render(self, frame: Frame, result: TrackingResult, fps: float) -> Any:
        """Return an annotated copy of ``frame.data``; never mutate the original."""
        ...


class OverlayRenderer(Protocol):
    """Draws detection results onto a copy of a frame's pixel buffer."""

    def render(self, frame: Frame, result: DetectionResult, fps: float) -> Any:
        """Return an annotated copy of ``frame.data``.

        Must never mutate the original buffer — other consumers see the
        same frame object.
        """
        ...


@dataclass(frozen=True, slots=True)
class AnnotatedFrame:
    """A rendered overlay image plus the result it visualizes."""

    frame: Frame
    result: DetectionResult
    image: Any


class DetectionConsumer(Protocol):
    """Receives every detection result (the future risk engine attaches here).

    The pipeline neither knows nor cares who consumes results; a consumer
    that raises loses that result but never stops the pipeline.
    """

    def __call__(self, result: DetectionResult) -> None: ...


class AnnotatedFrameConsumer(Protocol):
    """Receives rendered overlay frames (debug views, future dashboard feed)."""

    def __call__(self, annotated: AnnotatedFrame) -> None: ...
