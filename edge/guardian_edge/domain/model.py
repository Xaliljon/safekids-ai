"""AI model identity and I/O contract (the manifest).

Pure Python. A ModelManifest is the domain's view of contracts/models: what
a model is called, which version it is, and exactly which tensors it accepts
and produces. Engines refuse to load models that disagree with their
manifest, and refuse inputs that disagree with the specs (ADR-0008) —
"models must be replaceable" only works if their contracts are explicit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import total_ordering
from typing import Any

from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelValidationError

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$")


@total_ordering
@dataclass(frozen=True, slots=True)
class ModelVersion:
    """Semantic model version: MAJOR.MINOR.PATCH with optional -prerelease.

    Ordering is numeric on the triple; a release outranks any prerelease of
    the same triple; prereleases compare lexicographically (simplified
    SemVer — sufficient for model artifacts, no build metadata).
    """

    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    @classmethod
    def parse(cls, text: str) -> ModelVersion:
        """Raises ModelValidationError on anything that is not strict semver."""
        match = _VERSION_PATTERN.match(text)
        if match is None:
            raise ModelValidationError(
                f"'{text}' is not a semantic version (expected MAJOR.MINOR.PATCH[-prerelease])"
            )
        major, minor, patch, prerelease = match.groups()
        return cls(major=int(major), minor=int(minor), patch=int(patch), prerelease=prerelease)

    @classmethod
    def try_parse(cls, text: str) -> ModelVersion | None:
        try:
            return cls.parse(text)
        except ModelValidationError:
            return None

    def sort_key(self) -> tuple[int, int, int, int, str]:
        return (
            self.major,
            self.minor,
            self.patch,
            1 if self.prerelease is None else 0,  # releases outrank prereleases
            self.prerelease or "",
        )

    def __lt__(self, other: ModelVersion) -> bool:
        return self.sort_key() < other.sort_key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.prerelease is None else f"{base}-{self.prerelease}"


_KNOWN_DTYPES = frozenset(
    {
        "float16",
        "float32",
        "float64",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "bool",
    }
)


@dataclass(frozen=True, slots=True)
class TensorSpec:
    """Contract for one named tensor.

    ``shape`` dimensions are either fixed ints or ``None`` for dynamic
    dimensions resolved at runtime (dynamic input shapes). By convention the
    first dimension is the batch dimension; the runtime enforces batch
    size 1 on it (ADR-0008).
    """

    name: str
    dtype: str
    shape: tuple[int | None, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ModelValidationError("tensor name must not be empty")
        if self.dtype not in _KNOWN_DTYPES:
            raise ModelValidationError(
                f"tensor '{self.name}': unknown dtype '{self.dtype}' "
                f"(expected one of {sorted(_KNOWN_DTYPES)})"
            )
        for dim in self.shape:
            if dim is not None and dim < 1:
                raise ModelValidationError(
                    f"tensor '{self.name}': dimensions must be positive or None, got {dim}"
                )


@dataclass(frozen=True, slots=True)
class ModelCompatibility:
    """What a model requires from the runtime that loads it."""

    schema: int = 1
    """Manifest schema generation; the runtime refuses generations it doesn't know."""

    min_edge_version: str | None = None
    """Lowest guardian-edge version this model works on (semver), if constrained."""

    def __post_init__(self) -> None:
        if self.schema < 1:
            raise ModelValidationError(f"compatibility schema must be >= 1, got {self.schema}")
        if self.min_edge_version is not None:
            ModelVersion.parse(self.min_edge_version)


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Everything the runtime needs to know about one model artifact."""

    model: ModelDescriptor
    task: str
    file_name: str
    inputs: tuple[TensorSpec, ...]
    outputs: tuple[TensorSpec, ...]
    sha256: str | None = None
    """Optional artifact checksum; verified by the registry when present,
    and REQUIRED by the model zoo at install time."""

    license: str | None = None
    """SPDX-style license identifier; the zoo refuses undeclared or
    disallowed licenses at install time (see LicensePolicy, ADR-0009)."""

    compatibility: ModelCompatibility = field(default_factory=ModelCompatibility)

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Task-specific metadata the runtime never interprets.

    Detection models declare class ``labels`` and may declare default
    thresholds here (read by ``DetectorConfig.from_manifest``); other tasks
    put their own keys. Keeps models self-describing without the runtime
    knowing any task.
    """

    def __post_init__(self) -> None:
        ModelVersion.parse(self.model.version)  # versions must be strict semver
        if not self.task.strip():
            raise ModelValidationError(f"model '{self.model.name}': task must not be empty")
        if not self.file_name.strip():
            raise ModelValidationError(f"model '{self.model.name}': file_name must not be empty")
        if not self.inputs or not self.outputs:
            raise ModelValidationError(
                f"model '{self.model.name}': at least one input and one output are required"
            )
        for specs in (self.inputs, self.outputs):
            names = [spec.name for spec in specs]
            if len(names) != len(set(names)):
                raise ModelValidationError(
                    f"model '{self.model.name}': duplicate tensor names in {names}"
                )
