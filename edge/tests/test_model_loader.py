"""Model loader: the blessed registry -> engine -> warmup path."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import DYNAMIC_MODEL_NAME

from guardian_edge.application.inference.loader import ModelLoader
from guardian_edge.application.inference.metrics import EngineMetrics, EngineMetricsRecorder
from guardian_edge.application.inference.ports import RegisteredModel
from guardian_edge.domain.errors import ModelRegistryError
from guardian_edge.domain.model import ModelManifest
from guardian_edge.infrastructure.inference.onnx_engine import OnnxRuntimeEngineFactory
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry


class FakeEngine:
    def __init__(self, manifest: ModelManifest) -> None:
        self.manifest = manifest
        self.warmup_calls: list[int] = []
        self._recorder = EngineMetricsRecorder()

    def infer(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        return dict(inputs)

    def warmup(
        self, iterations: int = 2, shapes: Mapping[str, tuple[int, ...]] | None = None
    ) -> None:
        self.warmup_calls.append(iterations)

    def metrics(self) -> EngineMetrics:
        return self._recorder.snapshot()

    def close(self) -> None:
        pass


class FakeFactory:
    def __init__(self) -> None:
        self.engines: list[FakeEngine] = []

    def load(self, model: RegisteredModel) -> FakeEngine:
        engine = FakeEngine(model.manifest)
        self.engines.append(engine)
        return engine


def test_loads_and_warms_up(dynamic_model_dir: Path) -> None:
    factory = FakeFactory()
    loader = ModelLoader(
        registry=FileSystemModelRegistry(dynamic_model_dir),
        engine_factory=factory,
        warmup_iterations=3,
    )
    engine = loader.load(DYNAMIC_MODEL_NAME)
    assert engine.manifest.model.name == DYNAMIC_MODEL_NAME
    assert factory.engines[0].warmup_calls == [3]


def test_warmup_can_be_disabled(dynamic_model_dir: Path) -> None:
    factory = FakeFactory()
    loader = ModelLoader(
        registry=FileSystemModelRegistry(dynamic_model_dir),
        engine_factory=factory,
        warmup_iterations=0,
    )
    loader.load(DYNAMIC_MODEL_NAME)
    assert factory.engines[0].warmup_calls == []


def test_unknown_model_propagates_registry_error(dynamic_model_dir: Path) -> None:
    loader = ModelLoader(
        registry=FileSystemModelRegistry(dynamic_model_dir),
        engine_factory=FakeFactory(),
    )
    with pytest.raises(ModelRegistryError):
        loader.load("ghost-model")


def test_end_to_end_with_real_onnx_backend(dynamic_model_dir: Path) -> None:
    loader = ModelLoader(
        registry=FileSystemModelRegistry(dynamic_model_dir),
        engine_factory=OnnxRuntimeEngineFactory(),
    )
    engine = loader.load(DYNAMIC_MODEL_NAME)
    try:
        tensor = np.ones((1, 3, 8, 8), dtype=np.float32)
        assert np.array_equal(engine.infer({"input": tensor})["output"], tensor)
        assert engine.metrics().warmup_runs == 2, "loader must warm the engine"
    finally:
        engine.close()
