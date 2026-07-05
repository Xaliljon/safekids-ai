"""EngineDetector: the model-independent object detector.

Implements the Detector port (ADR-0006) for ANY object detection model by
composing pluggable stages around an InferenceEngine (ADR-0008):

    preprocess -> infer -> decode -> confidence filter -> NMS -> map

A model family contributes exactly two adapters — a Preprocessor and an
OutputDecoder — and inherits thresholds, suppression, identity stamping,
and result mapping. Nothing in this module knows what the model is.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from guardian_edge.application.inference.ports import InferenceEngine
from guardian_edge.application.vision.mapper import DetectionResultMapper
from guardian_edge.application.vision.nms import GreedyNms
from guardian_edge.application.vision.ports import (
    NonMaxSuppression,
    OutputDecoder,
    Preprocessor,
)
from guardian_edge.domain.detection import DetectionResult, ModelDescriptor
from guardian_edge.domain.errors import VisionConfigurationError
from guardian_edge.domain.frame import Frame
from guardian_edge.domain.model import ModelManifest

_THRESHOLD_KEYS = ("confidence_threshold", "nms_iou_threshold", "max_detections")


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Detection thresholds and the model's class labels.

    Confidence below ``confidence_threshold`` is discarded before NMS;
    ``nms_iou_threshold`` controls duplicate suppression; at most
    ``max_detections`` (highest confidence first) survive per frame.
    """

    labels: tuple[str, ...]
    confidence_threshold: float = 0.5
    nms_iou_threshold: float = 0.45
    max_detections: int = 100

    def __post_init__(self) -> None:
        if not self.labels or not all(label.strip() for label in self.labels):
            raise VisionConfigurationError("labels must be non-empty strings")
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise VisionConfigurationError(
                f"confidence_threshold out of range: {self.confidence_threshold}"
            )
        if not (0.0 < self.nms_iou_threshold <= 1.0):
            raise VisionConfigurationError(
                f"nms_iou_threshold out of range: {self.nms_iou_threshold}"
            )
        if self.max_detections < 1:
            raise VisionConfigurationError("max_detections must be >= 1")

    @classmethod
    def from_manifest(cls, manifest: ModelManifest, **overrides: Any) -> DetectorConfig:
        """Build config from the model's own metadata (labels required).

        Manifest metadata supplies defaults; keyword overrides win — a
        deployment can tighten thresholds without touching the model.
        """
        labels = manifest.metadata.get("labels")
        if not isinstance(labels, list | tuple) or not labels:
            raise VisionConfigurationError(
                f"model {manifest.model.name}: manifest metadata must declare 'labels' "
                f"to be used as a detection model"
            )
        values: dict[str, Any] = {"labels": tuple(str(label) for label in labels)}
        for key in _THRESHOLD_KEYS:
            if key in manifest.metadata:
                values[key] = manifest.metadata[key]
        values.update(overrides)
        return cls(**values)


class EngineDetector:
    """Detector-port implementation over an InferenceEngine.

    Owns its engine: closing the detector closes the engine. Not
    thread-safe by design — the vision pipeline serializes detector calls
    (ADR-0006).
    """

    def __init__(
        self,
        engine: InferenceEngine,
        preprocessor: Preprocessor,
        decoder: OutputDecoder,
        config: DetectorConfig,
        nms: NonMaxSuppression | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._engine = engine
        self._preprocessor = preprocessor
        self._decoder = decoder
        self._config = config
        self._nms = nms or GreedyNms()
        self._clock = clock
        self._mapper = DetectionResultMapper(labels=config.labels, model=engine.manifest.model)

    @property
    def descriptor(self) -> ModelDescriptor:
        return self._engine.manifest.model

    @property
    def config(self) -> DetectorConfig:
        return self._config

    def detect(self, frame: Frame) -> DetectionResult:
        preprocessed = self._preprocessor.preprocess(frame)
        started = self._clock()
        outputs = self._engine.infer(preprocessed.inputs)
        inference_ms = (self._clock() - started) * 1000.0
        candidates = self._decoder.decode(outputs, preprocessed.meta)
        confident = [
            candidate
            for candidate in candidates
            if candidate.confidence >= self._config.confidence_threshold
        ]
        survivors = self._nms.suppress(confident, self._config.nms_iou_threshold)
        survivors.sort(key=lambda candidate: candidate.confidence, reverse=True)
        return self._mapper.map(
            frame, survivors[: self._config.max_detections], inference_ms=inference_ms
        )

    def close(self) -> None:
        """Release the underlying engine. Idempotent."""
        self._engine.close()
