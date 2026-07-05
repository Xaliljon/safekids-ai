"""Model manifest parsing (manifest.json).

The JSON format mirrors the future contracts/models schema; ai/export will
emit these files next to every exported artifact. Parsing is strict: a
manifest that cannot be fully understood is a manifest that cannot be
trusted to gate inference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelLoadError, ModelValidationError
from guardian_edge.domain.model import ModelManifest, TensorSpec

MANIFEST_FILE_NAME = "manifest.json"


def load_manifest(path: Path) -> ModelManifest:
    """Load and validate a manifest.json.

    Raises ModelLoadError on unreadable/malformed files or invalid content.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelLoadError(f"cannot read manifest '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelLoadError(f"manifest '{path}' is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelLoadError(f"manifest '{path}' must be a JSON object")
    try:
        return _parse(raw)
    except (KeyError, TypeError, ValueError, ModelValidationError) as exc:
        raise ModelLoadError(f"manifest '{path}' is invalid: {exc}") from exc


def _parse(raw: dict[str, Any]) -> ModelManifest:
    sha256 = raw.get("sha256")
    return ModelManifest(
        model=ModelDescriptor(name=str(raw["name"]), version=str(raw["version"])),
        task=str(raw["task"]),
        file_name=str(raw["file"]),
        inputs=_parse_specs(raw["inputs"], kind="inputs"),
        outputs=_parse_specs(raw["outputs"], kind="outputs"),
        sha256=str(sha256) if sha256 is not None else None,
    )


def _parse_specs(raw: Any, kind: str) -> tuple[TensorSpec, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"'{kind}' must be a list of tensor specs")
    specs = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"'{kind}' entries must be objects")
        shape = entry["shape"]
        if not isinstance(shape, list):
            raise ValueError(f"'{kind}' shape must be a list (null = dynamic dimension)")
        specs.append(
            TensorSpec(
                name=str(entry["name"]),
                dtype=str(entry["dtype"]),
                shape=tuple(None if dim is None else int(dim) for dim in shape),
            )
        )
    return tuple(specs)
