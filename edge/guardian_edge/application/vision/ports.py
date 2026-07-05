"""Ports (interfaces) of the vision pipeline.

Two abstraction levels (ADR-0006):

- ``Detector`` is the task-level port the pipeline drives: frame in,
  DetectionResult out. This is all the pipeline ever knows about AI.
- ``InferenceEngine`` is the runtime-level port real detectors will compose
  with pre/post-processing once model backends (ONNX Runtime, TensorRT)
  land in later sprints. Nothing implements it yet — it is the contract
  those backends must satisfy.

Dependencies point inward: this module imports domain only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from guardian_edge.domain.detection import DetectionResult, ModelDescriptor
from guardian_edge.domain.frame import Frame


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


class InferenceEngine(Protocol):
    """Low-level model runtime (ONNX Runtime / TensorRT — later sprints).

    Inputs and outputs are backend-specific buffers, so they are typed
    ``Any`` here; the contracts/models manifest binds concrete shapes when
    real backends land. Engines must be replaceable without touching any
    code above the Detector port (docs/03, AI is a subsystem).
    """

    @property
    def model(self) -> ModelDescriptor: ...

    def infer(self, inputs: Any) -> Any:
        """Run one forward pass. Deterministic for identical inputs."""
        ...

    def close(self) -> None:
        """Release runtime resources. Idempotent."""
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
