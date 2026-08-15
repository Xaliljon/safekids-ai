"""Sprint 23: the runtime-configuration and parity machinery.

The optimization matrix itself is a recorded experiment
(reports/rtdetr/inference-optimization-report.md), not a test — it takes
tens of minutes and needs an idle machine, which is the whole point of it.
What is tested here is the machinery the matrix relies on: that a session
honours the configuration it is given, that an unavailable provider fails
loudly instead of falling back silently, and that a graph optimization
level cannot change what a detector means.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
import torch

from guardian_ai.export.onnx_export import MODEL_FILE, export_onnx
from guardian_ai.training.errors import ProviderUnavailableError
from guardian_ai.training.families import get_family
from guardian_ai.training.profiling import RuntimeConfig, make_session, profile_inference

_INPUT_SIZE = 64
_PARITY_TOLERANCE = 1e-4
"""The same tolerance the export gate enforces. An optimization that cannot
meet it is not an optimization — Sprint 23 rejected CoreML's Neural Engine
path (34.22 ms, max delta 0.9875) on exactly this line."""


@pytest.fixture(scope="module")
def model_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real ONNX artifact, small enough to profile in a unit test."""
    destination = tmp_path_factory.mktemp("rtdetr-perf") / MODEL_FILE
    family = get_family("tiny-ssd")
    model = family.build(num_classes=1, input_size=_INPUT_SIZE)
    export_onnx(model, family, _INPUT_SIZE, destination)
    return destination


def _run(session: ort.InferenceSession, seed: int = 0) -> np.ndarray:
    generator = np.random.default_rng(seed)
    example = generator.standard_normal((1, 3, _INPUT_SIZE, _INPUT_SIZE)).astype(np.float32)
    return session.run(None, {"images": example})[0]


# ------------------------------------------------ session configuration


def test_session_honours_the_configuration_it_is_given(model_path: Path) -> None:
    config = RuntimeConfig(graph_optimization_level="ORT_ENABLE_BASIC", intra_op_threads=2)
    options = make_session(model_path, config)._sess_options  # noqa: SLF001
    assert options.graph_optimization_level == ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    assert options.intra_op_num_threads == 2


@pytest.mark.parametrize(
    "level",
    ["ORT_DISABLE_ALL", "ORT_ENABLE_BASIC", "ORT_ENABLE_EXTENDED", "ORT_ENABLE_ALL"],
)
def test_every_optimization_level_loads(model_path: Path, level: str) -> None:
    session = make_session(model_path, RuntimeConfig(graph_optimization_level=level))
    assert session.get_inputs()[0].name == "images"


def test_an_unavailable_provider_fails_loudly(model_path: Path) -> None:
    """The defect this sprint found in Guardian's own harness.

    ONNX Runtime does not raise on an unknown provider — it warns and runs
    on CPU. Left alone, that reports CPU latency under a CUDA or CoreML
    label, which is worse than no benchmark (Sprint 23 §9). make_session
    now checks what actually got loaded.
    """
    with pytest.raises(ProviderUnavailableError, match="fell back to"):
        make_session(model_path, RuntimeConfig(provider="NoSuchExecutionProvider"))


def test_an_available_provider_is_accepted(model_path: Path) -> None:
    session = make_session(model_path, RuntimeConfig(provider="CPUExecutionProvider"))
    assert "CPUExecutionProvider" in session.get_providers()


def test_an_invalid_optimization_level_fails_loudly(model_path: Path) -> None:
    with pytest.raises(AttributeError):
        make_session(model_path, RuntimeConfig(graph_optimization_level="ORT_ENABLE_MAGIC"))


# ------------------------------------------------------- static shapes


def test_export_is_fully_static(model_path: Path) -> None:
    """Guardian inference is batch=1 at a fixed resolution. A symbolic
    dimension would leave shape work for run time that Sprint 23 measured
    ORT folding away entirely."""
    session = make_session(model_path, RuntimeConfig())
    assert session.get_inputs()[0].shape == [1, 3, _INPUT_SIZE, _INPUT_SIZE]
    assert all(isinstance(dimension, int) for dimension in session.get_inputs()[0].shape)


# -------------------------------------------------------------- parity


def test_graph_optimization_does_not_change_the_answer(model_path: Path) -> None:
    """§12: an optimization must not alter detector meaning."""
    baseline = _run(
        make_session(model_path, RuntimeConfig(graph_optimization_level="ORT_DISABLE_ALL"))
    )
    for level in ("ORT_ENABLE_BASIC", "ORT_ENABLE_EXTENDED", "ORT_ENABLE_ALL"):
        optimized = _run(make_session(model_path, RuntimeConfig(graph_optimization_level=level)))
        assert optimized.shape == baseline.shape, level
        assert float(np.abs(optimized - baseline).max()) <= _PARITY_TOLERANCE, level


def test_thread_count_does_not_change_the_answer(model_path: Path) -> None:
    """Sprint 23's fastest CPU configuration was intra=8 rather than the
    default; it is only usable because it computes the same thing."""
    baseline = _run(make_session(model_path, RuntimeConfig(intra_op_threads=1)))
    for threads in (2, 4):
        optimized = _run(make_session(model_path, RuntimeConfig(intra_op_threads=threads)))
        assert float(np.abs(optimized - baseline).max()) <= _PARITY_TOLERANCE, threads


def test_decoded_predictions_survive_optimization(model_path: Path) -> None:
    """Parity on the tensor is necessary; parity on what the detector says
    is what actually matters."""
    family = get_family("tiny-ssd")
    baseline = family.decode(
        torch.from_numpy(
            _run(
                make_session(model_path, RuntimeConfig(graph_optimization_level="ORT_DISABLE_ALL"))
            )
        )
    )[0]
    optimized = family.decode(
        torch.from_numpy(
            _run(make_session(model_path, RuntimeConfig(graph_optimization_level="ORT_ENABLE_ALL")))
        )
    )[0]
    assert baseline.boxes.shape == optimized.boxes.shape
    assert np.array_equal(baseline.labels, optimized.labels)
    if baseline.scores.size:
        assert float(np.abs(baseline.scores - optimized.scores).max()) <= _PARITY_TOLERANCE


# --------------------------------------------------- benchmark metadata


def test_profile_records_the_configuration_it_measured(model_path: Path) -> None:
    """A latency number whose configuration is not recorded cannot be
    compared to anything later — which is how Sprint 22's figure survived
    as long as it did."""
    config = RuntimeConfig(graph_optimization_level="ORT_ENABLE_ALL", intra_op_threads=2)
    profile = profile_inference(
        model_path, config, (1, 3, _INPUT_SIZE, _INPUT_SIZE), warmup=2, runs=5
    )
    payload = profile.to_dict()
    assert payload["config"]["graph_optimization_level"] == "ORT_ENABLE_ALL"
    assert payload["config"]["intra_op_threads"] == 2
    assert payload["config"]["provider"] == "CPUExecutionProvider"
    assert payload["steady_state"]["mean_ms"] > 0
    assert payload["first_call_ms"] > 0


def test_profile_separates_cold_start_from_steady_state(model_path: Path) -> None:
    profile = profile_inference(
        model_path, RuntimeConfig(), (1, 3, _INPUT_SIZE, _INPUT_SIZE), warmup=2, runs=5
    )
    assert profile.first_ten.mean_ms > 0
    assert profile.steady_state.mean_ms > 0
    assert profile.first_call_ms >= profile.steady_state.p50_ms * 0.1
