"""Model-runtime compatibility checks.

A model that requires a newer runtime, or speaks a manifest generation this
runtime does not know, is refused before installation — an OTA-delivered
model must never brick inference on an older box in the field.
"""

from __future__ import annotations

from collections.abc import Collection

import guardian_edge
from guardian_edge.domain.errors import ModelCompatibilityError
from guardian_edge.domain.model import ModelManifest, ModelVersion

SUPPORTED_MANIFEST_SCHEMAS = frozenset({1})


class CompatibilityChecker:
    """Verifies a manifest's compatibility block against this runtime."""

    def __init__(
        self,
        edge_version: str | None = None,
        supported_schemas: Collection[int] = SUPPORTED_MANIFEST_SCHEMAS,
    ) -> None:
        self._edge_version = ModelVersion.parse(edge_version or guardian_edge.__version__)
        self._supported_schemas = frozenset(supported_schemas)

    def check(self, manifest: ModelManifest) -> None:
        """Raises ModelCompatibilityError when this runtime cannot honor the model."""
        identity = f"model {manifest.model.name} v{manifest.model.version}"
        compatibility = manifest.compatibility
        if compatibility.schema not in self._supported_schemas:
            raise ModelCompatibilityError(
                f"{identity}: manifest schema {compatibility.schema} is not supported "
                f"by this runtime (supported: {sorted(self._supported_schemas)})"
            )
        if compatibility.min_edge_version is not None:
            required = ModelVersion.parse(compatibility.min_edge_version)
            if required > self._edge_version:
                raise ModelCompatibilityError(
                    f"{identity}: requires guardian-edge >= {required}, "
                    f"this device runs {self._edge_version}"
                )
