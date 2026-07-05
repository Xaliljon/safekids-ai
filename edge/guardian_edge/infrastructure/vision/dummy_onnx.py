"""Dummy ONNX detector: the abstraction proven end-to-end, without YOLO.

Wires a real ONNX Runtime engine (loaded from a model registry) into the
model-independent EngineDetector using the generic image preprocessor and
row decoder. The registry must contain a model named
``dummy-onnx-detector`` whose manifest metadata declares its labels —
tests author that artifact as a tiny synthetic graph.

Swapping in a real model family later means: new registry entry + that
family's Preprocessor/OutputDecoder pair. Nothing else changes.
"""

from __future__ import annotations

from typing import Any

from guardian_edge.application.inference.loader import ModelLoader
from guardian_edge.application.inference.ports import InferenceEngineFactory, ModelRegistry
from guardian_edge.application.vision.detector import DetectorConfig, EngineDetector
from guardian_edge.infrastructure.inference.onnx_engine import OnnxRuntimeEngineFactory
from guardian_edge.infrastructure.vision.decoders import TensorRowDecoder
from guardian_edge.infrastructure.vision.preprocessing import ImagePreprocessor

DUMMY_ONNX_DETECTOR_NAME = "dummy-onnx-detector"


def create_dummy_onnx_detector(
    registry: ModelRegistry,
    engine_factory: InferenceEngineFactory | None = None,
    **config_overrides: Any,
) -> EngineDetector:
    """Load the dummy detection model and wrap it in an EngineDetector.

    Thresholds come from the model's manifest metadata; keyword overrides
    win (``confidence_threshold=…``, ``nms_iou_threshold=…``, …).
    """
    loader = ModelLoader(
        registry=registry,
        engine_factory=engine_factory or OnnxRuntimeEngineFactory(),
    )
    engine = loader.load(DUMMY_ONNX_DETECTOR_NAME)
    manifest = engine.manifest
    return EngineDetector(
        engine=engine,
        preprocessor=ImagePreprocessor(input_name=manifest.inputs[0].name),
        decoder=TensorRowDecoder(output_name=manifest.outputs[0].name),
        config=DetectorConfig.from_manifest(manifest, **config_overrides),
    )
