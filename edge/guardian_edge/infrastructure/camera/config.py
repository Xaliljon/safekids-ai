"""Camera configuration loading (YAML).

Secrets never live in the file (docs/03, configuration rules): RTSP
credentials are referenced as ``${ENV_VAR}`` placeholders and resolved from
the environment at load time. See edge/config/cameras.example.yaml.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from guardian_edge.domain.camera import Camera
from guardian_edge.domain.errors import CameraConfigurationError

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_cameras(path: Path) -> list[Camera]:
    """Load and validate the camera list from a YAML config file.

    Raises CameraConfigurationError on unreadable files, malformed YAML,
    missing keys, duplicate ids, unresolved environment placeholders, or
    invalid camera definitions.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CameraConfigurationError(f"cannot read camera config '{path}': {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CameraConfigurationError(f"camera config '{path}' is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("cameras"), list):
        raise CameraConfigurationError(f"camera config '{path}' needs a top-level 'cameras' list")

    cameras: list[Camera] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw["cameras"]):
        context = f"camera config '{path}': cameras[{index}]"
        if not isinstance(entry, dict):
            raise CameraConfigurationError(f"{context} must be a mapping")
        try:
            camera_id = str(entry["id"])
            name = str(entry["name"])
            rtsp_url = str(entry["rtsp_url"])
        except KeyError as exc:
            raise CameraConfigurationError(f"{context} is missing key {exc}") from exc
        if camera_id in seen_ids:
            raise CameraConfigurationError(f"{context} duplicates camera id '{camera_id}'")
        seen_ids.add(camera_id)
        cameras.append(
            Camera(
                camera_id=camera_id,
                name=name,
                rtsp_url=_expand_env(rtsp_url, context=context),
                location=str(entry.get("location", "")),
            )
        )
    return cameras


def _expand_env(value: str, *, context: str) -> str:
    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        resolved = os.environ.get(variable)
        if resolved is None:
            raise CameraConfigurationError(
                f"{context}: environment variable '{variable}' is not set"
            )
        return resolved

    return _ENV_PATTERN.sub(replace, value)
