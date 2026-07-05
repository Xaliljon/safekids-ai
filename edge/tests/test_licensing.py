"""License policy: the on-device allowlist gate."""

import pytest

from guardian_edge.application.inference.licensing import (
    DEFAULT_ALLOWED_LICENSES,
    LicensePolicy,
)
from guardian_edge.domain.detection import ModelDescriptor
from guardian_edge.domain.errors import ModelLicenseError
from guardian_edge.domain.model import ModelManifest, TensorSpec


def make_manifest(license_id: str | None) -> ModelManifest:
    return ModelManifest(
        model=ModelDescriptor(name="test-model", version="1.0.0"),
        task="test",
        file_name="model.onnx",
        inputs=(TensorSpec(name="input", dtype="float32", shape=(1, 4)),),
        outputs=(TensorSpec(name="output", dtype="float32", shape=(1, 4)),),
        license=license_id,
    )


@pytest.mark.parametrize("license_id", sorted(DEFAULT_ALLOWED_LICENSES))
def test_default_allowlist_passes(license_id: str) -> None:
    LicensePolicy().check(make_manifest(license_id))


def test_agpl_is_refused_by_default() -> None:
    """The ADR-0003 risk, blocked structurally: AGPL never installs on-device."""
    with pytest.raises(ModelLicenseError, match="AGPL-3.0"):
        LicensePolicy().check(make_manifest("AGPL-3.0"))


@pytest.mark.parametrize("license_id", [None, "", "   "])
def test_undeclared_license_is_refused(license_id: str | None) -> None:
    with pytest.raises(ModelLicenseError, match="no license"):
        LicensePolicy().check(make_manifest(license_id))


def test_custom_allowlist_replaces_default() -> None:
    policy = LicensePolicy(allowed={"MIT"})
    policy.check(make_manifest("MIT"))
    with pytest.raises(ModelLicenseError):
        policy.check(make_manifest("Apache-2.0"))
