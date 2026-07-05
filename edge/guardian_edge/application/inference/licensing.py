"""Model license policy.

Every model installed on a Guardian Edge Box must declare a license the
company is allowed to ship in a proprietary product. This gate exists
specifically to make AGPL contamination (the ADR-0003 risk — e.g.
Ultralytics YOLO weights) structurally impossible: an AGPL model bundle is
refused at install time, on the device, regardless of who built it.
"""

from __future__ import annotations

from collections.abc import Collection

from guardian_edge.domain.errors import ModelLicenseError
from guardian_edge.domain.model import ModelManifest

DEFAULT_ALLOWED_LICENSES = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Proprietary-GuardianAI",  # our own trained/licensed models
    }
)


class LicensePolicy:
    """Allowlist of SPDX-style license identifiers permitted on-device."""

    def __init__(self, allowed: Collection[str] = DEFAULT_ALLOWED_LICENSES) -> None:
        self._allowed = frozenset(allowed)

    @property
    def allowed(self) -> frozenset[str]:
        return self._allowed

    def check(self, manifest: ModelManifest) -> None:
        """Raises ModelLicenseError for undeclared or disallowed licenses."""
        identity = f"model {manifest.model.name} v{manifest.model.version}"
        if manifest.license is None or not manifest.license.strip():
            raise ModelLicenseError(
                f"{identity}: manifest declares no license — undeclared licenses "
                f"are never installed (docs/03, ADR-0009)"
            )
        if manifest.license not in self._allowed:
            raise ModelLicenseError(
                f"{identity}: license '{manifest.license}' is not allowed on this device "
                f"(allowed: {sorted(self._allowed)})"
            )
