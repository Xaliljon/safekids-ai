"""ONNX Runtime engine: loading, dynamic shapes, validation, metrics, profiling."""

from pathlib import Path

import numpy as np
import pytest
from conftest import DYNAMIC_MODEL_NAME, install_model

from guardian_edge.domain.errors import (
    InferenceError,
    ModelLoadError,
    TensorValidationError,
)
from guardian_edge.infrastructure.inference.onnx_engine import OnnxRuntimeEngineFactory
from guardian_edge.infrastructure.inference.registry import FileSystemModelRegistry


@pytest.fixture
def registry(dynamic_model_dir: Path) -> FileSystemModelRegistry:
    return FileSystemModelRegistry(dynamic_model_dir)


def load_engine(registry: FileSystemModelRegistry):  # noqa: ANN201 - fixture helper
    return OnnxRuntimeEngineFactory().load(registry.get(DYNAMIC_MODEL_NAME))


def test_loads_and_infers_with_dynamic_shapes(registry: FileSystemModelRegistry) -> None:
    engine = load_engine(registry)
    try:
        for height, width in ((32, 32), (48, 64)):  # different shapes, same session
            tensor = np.random.rand(1, 3, height, width).astype(np.float32)
            outputs = engine.infer({"input": tensor})
            assert np.array_equal(outputs["output"], tensor), "identity graph must echo input"
    finally:
        engine.close()


def test_rejects_invalid_inputs_before_the_backend(registry: FileSystemModelRegistry) -> None:
    engine = load_engine(registry)
    try:
        with pytest.raises(TensorValidationError, match="axis 0 is 2, declared 1"):
            engine.infer({"input": np.zeros((2, 3, 8, 8), dtype=np.float32)})
        with pytest.raises(TensorValidationError, match="dtype"):
            engine.infer({"input": np.zeros((1, 3, 8, 8), dtype=np.float64)})
        with pytest.raises(TensorValidationError, match="missing"):
            engine.infer({})
        assert engine.metrics().inferences_total == 0, "rejected inputs never reach the model"
    finally:
        engine.close()


def test_warmup_runs_are_separate_from_inference_metrics(
    registry: FileSystemModelRegistry,
) -> None:
    engine = load_engine(registry)
    try:
        engine.warmup(iterations=3, shapes={"input": (1, 3, 16, 16)})
        metrics = engine.metrics()
        assert metrics.warmup_runs == 3
        assert metrics.inferences_total == 0
    finally:
        engine.close()


def test_metrics_track_latency_statistics(registry: FileSystemModelRegistry) -> None:
    engine = load_engine(registry)
    try:
        tensor = np.zeros((1, 3, 8, 8), dtype=np.float32)
        for _ in range(10):
            engine.infer({"input": tensor})
        metrics = engine.metrics()
        assert metrics.inferences_total == 10
        assert metrics.errors_total == 0
        assert metrics.last_latency_ms is not None and metrics.last_latency_ms >= 0.0
        assert metrics.mean_latency_ms is not None
        assert metrics.p50_latency_ms is not None
        assert metrics.p95_latency_ms is not None
        assert metrics.p95_latency_ms >= metrics.p50_latency_ms
    finally:
        engine.close()


def test_closed_engine_refuses_to_run(registry: FileSystemModelRegistry) -> None:
    engine = load_engine(registry)
    engine.close()
    engine.close()  # idempotent
    with pytest.raises(InferenceError, match="closed"):
        engine.infer({"input": np.zeros((1, 3, 8, 8), dtype=np.float32)})


def test_manifest_disagreeing_with_model_is_rejected(tmp_path: Path) -> None:
    install_model(
        tmp_path,
        "liar-model",
        manifest_overrides={
            "inputs": [{"name": "input", "dtype": "float32", "shape": [1, 10]}],
        },
    )
    registered = FileSystemModelRegistry(tmp_path).get("liar-model")
    with pytest.raises(ModelLoadError, match="rank"):
        OnnxRuntimeEngineFactory().load(registered)


def test_manifest_with_wrong_tensor_names_is_rejected(tmp_path: Path) -> None:
    install_model(
        tmp_path,
        "misnamed-model",
        manifest_overrides={
            "inputs": [{"name": "images", "dtype": "float32", "shape": [1, 3, None, None]}],
        },
    )
    registered = FileSystemModelRegistry(tmp_path).get("misnamed-model")
    with pytest.raises(ModelLoadError, match="declares input"):
        OnnxRuntimeEngineFactory().load(registered)


def test_profiling_writes_a_trace_when_enabled(tmp_path: Path) -> None:
    install_model(tmp_path, "profiled-model")
    registered = FileSystemModelRegistry(tmp_path).get("profiled-model")
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    engine = OnnxRuntimeEngineFactory(profiling_dir=profile_dir).load(registered)
    engine.infer({"input": np.zeros((1, 3, 8, 8), dtype=np.float32)})
    engine.close()
    traces = list(profile_dir.glob("profiled-model-*.json"))
    assert traces, "ONNX Runtime must write a profiling trace on close"
