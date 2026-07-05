"""Ports (interfaces) of the inference runtime.

Infrastructure provides implementations (ONNX Runtime today, TensorRT on
Jetson later); tests provide fakes. Dependencies point inward: domain only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from guardian_edge.application.inference.metrics import EngineMetrics
from guardian_edge.domain.model import ModelManifest


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A registry entry: a verified manifest plus the artifact it describes."""

    manifest: ModelManifest
    path: Path


class InferenceEngine(Protocol):
    """A loaded, ready-to-run model. Model-agnostic by contract (ADR-0008).

    Engines exchange *named* tensors — ``{"input": array}`` in,
    ``{"output": array}`` out — validated against the manifest on every
    call. Batch size is 1. Tensor values are backend buffers (numpy arrays
    for ONNX Runtime), typed ``Any`` here so the application layer stays
    framework-free.
    """

    @property
    def manifest(self) -> ModelManifest:
        """The contract this engine was loaded against."""
        ...

    def infer(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        """Run one forward pass on named input tensors.

        Raises TensorValidationError when inputs disagree with the manifest
        and InferenceError when the backend fails.
        """
        ...

    def warmup(
        self, iterations: int = 2, shapes: Mapping[str, tuple[int, ...]] | None = None
    ) -> None:
        """Run throwaway inferences so first real latency is representative.

        ``shapes`` resolves dynamic dimensions; unresolved dynamic
        dimensions default to 1. Warmup runs never count as inferences in
        the metrics.
        """
        ...

    def metrics(self) -> EngineMetrics:
        """Latency and error statistics for this engine instance."""
        ...

    def close(self) -> None:
        """Release backend resources (and finalize profiling). Idempotent."""
        ...


class InferenceEngineFactory(Protocol):
    """Loads registered models into ready engines."""

    def load(self, model: RegisteredModel) -> InferenceEngine:
        """Load the artifact and verify it against its manifest.

        Raises ModelLoadError when the artifact cannot be loaded or its
        real I/O disagrees with the manifest.
        """
        ...


class ModelRegistry(Protocol):
    """Source of verified model artifacts."""

    def list_models(self) -> list[ModelManifest]:
        """Manifests of every model available in the registry."""
        ...

    def get(self, name: str, version: str | None = None) -> RegisteredModel:
        """Resolve a model by name (latest version when omitted).

        Raises ModelRegistryError when the model is unknown or fails
        verification (missing artifact, checksum mismatch).
        """
        ...
