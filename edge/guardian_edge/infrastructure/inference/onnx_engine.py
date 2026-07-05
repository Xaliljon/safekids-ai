"""ONNX Runtime implementation of the InferenceEngine port.

The canonical, portable backend (ADR-0001 §7): CPU by default, other
execution providers (CUDA, TensorRT) by configuration. Model-agnostic —
this module never interprets tensors; it loads what the manifest describes,
validates what callers feed it, and measures everything.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort

from guardian_edge.application.inference.metrics import EngineMetrics, EngineMetricsRecorder
from guardian_edge.application.inference.ports import RegisteredModel
from guardian_edge.application.inference.validation import resolve_shape, validate_inputs
from guardian_edge.domain.errors import InferenceError, ModelLoadError
from guardian_edge.domain.model import ModelManifest, TensorSpec

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS = ("CPUExecutionProvider",)

# ONNX Runtime element types -> manifest dtype names.
_ORT_TO_DTYPE = {
    "tensor(float16)": "float16",
    "tensor(float)": "float32",
    "tensor(double)": "float64",
    "tensor(int8)": "int8",
    "tensor(int16)": "int16",
    "tensor(int32)": "int32",
    "tensor(int64)": "int64",
    "tensor(uint8)": "uint8",
    "tensor(uint16)": "uint16",
    "tensor(bool)": "bool",
}


class OnnxRuntimeEngine:
    """A loaded ONNX Runtime session bound to its manifest."""

    def __init__(
        self,
        session: ort.InferenceSession,
        manifest: ModelManifest,
        recorder: EngineMetricsRecorder | None = None,
        clock: Any = time.perf_counter,
    ) -> None:
        self._session: ort.InferenceSession | None = session
        self._manifest = manifest
        self._recorder = recorder or EngineMetricsRecorder()
        self._clock = clock
        self._output_names = [spec.name for spec in manifest.outputs]

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    def infer(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        session = self._require_open()
        validate_inputs(self._manifest.inputs, inputs)
        started = self._clock()
        try:
            raw = session.run(self._output_names, dict(inputs))
        except Exception as exc:
            self._recorder.record_error()
            raise InferenceError(
                f"model {self._manifest.model.name} v{self._manifest.model.version}: "
                f"inference failed: {exc}"
            ) from exc
        self._recorder.record_inference((self._clock() - started) * 1000.0)
        return dict(zip(self._output_names, raw, strict=True))

    def warmup(
        self, iterations: int = 2, shapes: Mapping[str, tuple[int, ...]] | None = None
    ) -> None:
        """Run throwaway zero-tensor passes; excluded from inference metrics."""
        session = self._require_open()
        synthetic = {
            spec.name: np.zeros(resolve_shape(spec, shapes), dtype=spec.dtype)
            for spec in self._manifest.inputs
        }
        for _ in range(iterations):
            try:
                session.run(self._output_names, synthetic)
            except Exception as exc:
                raise InferenceError(
                    f"model {self._manifest.model.name}: warmup failed: {exc}"
                ) from exc
            self._recorder.record_warmup()

    def metrics(self) -> EngineMetrics:
        return self._recorder.snapshot()

    def close(self) -> None:
        session = self._session
        self._session = None
        if session is None:
            return
        profile_path = session.end_profiling()
        if profile_path:
            logger.info(
                "model %s v%s: profiling trace written to %s",
                self._manifest.model.name,
                self._manifest.model.version,
                profile_path,
            )

    def _require_open(self) -> ort.InferenceSession:
        if self._session is None:
            raise InferenceError(f"model {self._manifest.model.name}: engine is closed")
        return self._session


class OnnxRuntimeEngineFactory:
    """Loads registered models into OnnxRuntimeEngine instances.

    ``profiling_dir`` enables ONNX Runtime's operator-level profiler; the
    JSON trace path is logged on ``close()``. Per-call latency metrics are
    always on regardless.
    """

    def __init__(
        self,
        providers: Sequence[str] = DEFAULT_PROVIDERS,
        profiling_dir: Path | None = None,
        intra_op_threads: int | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._profiling_dir = profiling_dir
        self._intra_op_threads = intra_op_threads

    def load(self, model: RegisteredModel) -> OnnxRuntimeEngine:
        manifest = model.manifest
        options = ort.SessionOptions()
        if self._intra_op_threads is not None:
            options.intra_op_num_threads = self._intra_op_threads
        if self._profiling_dir is not None:
            options.enable_profiling = True
            options.profile_file_prefix = str(
                self._profiling_dir / f"{manifest.model.name}-{manifest.model.version}"
            )
        try:
            session = ort.InferenceSession(
                str(model.path), sess_options=options, providers=list(self._providers)
            )
        except Exception as exc:
            raise ModelLoadError(
                f"model {manifest.model.name} v{manifest.model.version}: "
                f"ONNX Runtime could not load '{model.path}': {exc}"
            ) from exc
        _verify_io(session, manifest, model.path)
        logger.info(
            "model %s v%s loaded with providers %s",
            manifest.model.name,
            manifest.model.version,
            list(self._providers),
        )
        return OnnxRuntimeEngine(session, manifest)


def _verify_io(session: ort.InferenceSession, manifest: ModelManifest, path: Path) -> None:
    """The manifest must agree with the model's real graph, or nothing runs."""
    _verify_tensors(manifest.inputs, session.get_inputs(), kind="input", path=path)
    _verify_tensors(manifest.outputs, session.get_outputs(), kind="output", path=path)


def _verify_tensors(specs: tuple[TensorSpec, ...], nodes: list[Any], kind: str, path: Path) -> None:
    actual = {node.name: node for node in nodes}
    declared = {spec.name for spec in specs}
    if declared != set(actual):
        raise ModelLoadError(
            f"'{path}': manifest declares {kind}s {sorted(declared)} "
            f"but the model has {sorted(actual)}"
        )
    for spec in specs:
        node = actual[spec.name]
        node_dtype = _ORT_TO_DTYPE.get(node.type)
        if node_dtype != spec.dtype:
            raise ModelLoadError(
                f"'{path}': {kind} '{spec.name}' is {node.type} in the model "
                f"but '{spec.dtype}' in the manifest"
            )
        node_shape = list(node.shape)
        if len(node_shape) != len(spec.shape):
            raise ModelLoadError(
                f"'{path}': {kind} '{spec.name}' has rank {len(node_shape)} in the model "
                f"but {len(spec.shape)} in the manifest"
            )
        for axis, (declared_dim, model_dim) in enumerate(zip(spec.shape, node_shape, strict=True)):
            model_fixed = isinstance(model_dim, int)
            if model_fixed and declared_dim is not None and declared_dim != model_dim:
                raise ModelLoadError(
                    f"'{path}': {kind} '{spec.name}' axis {axis} is {model_dim} "
                    f"in the model but {declared_dim} in the manifest"
                )
            if model_fixed and declared_dim is None:
                raise ModelLoadError(
                    f"'{path}': {kind} '{spec.name}' axis {axis} is fixed ({model_dim}) "
                    f"in the model but dynamic in the manifest"
                )
