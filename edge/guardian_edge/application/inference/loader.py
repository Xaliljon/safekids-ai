"""Model loader: registry entry -> verified, warmed, ready engine.

The one blessed path from "a model exists" to "a model is serving":
resolve in the registry (which verifies the artifact), load through the
engine factory (which verifies the manifest against real model I/O), then
warm up so the first real inference is representative. Callers never
assemble engines by hand.
"""

from __future__ import annotations

import logging

from guardian_edge.application.inference.ports import (
    InferenceEngine,
    InferenceEngineFactory,
    ModelRegistry,
)

logger = logging.getLogger(__name__)

DEFAULT_WARMUP_ITERATIONS = 2


class ModelLoader:
    """Loads models from a registry into ready-to-serve engines."""

    def __init__(
        self,
        registry: ModelRegistry,
        engine_factory: InferenceEngineFactory,
        warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
    ) -> None:
        self._registry = registry
        self._engine_factory = engine_factory
        self._warmup_iterations = warmup_iterations

    def load(self, name: str, version: str | None = None) -> InferenceEngine:
        """Resolve, load, verify, and warm up a model by name.

        Raises ModelRegistryError (unknown/failed verification) or
        ModelLoadError (artifact/manifest disagreement).
        """
        registered = self._registry.get(name, version)
        engine = self._engine_factory.load(registered)
        if self._warmup_iterations > 0:
            engine.warmup(self._warmup_iterations)
        descriptor = registered.manifest.model
        logger.info(
            "model %s v%s loaded (task=%s, warmup=%d)",
            descriptor.name,
            descriptor.version,
            registered.manifest.task,
            self._warmup_iterations,
        )
        return engine
