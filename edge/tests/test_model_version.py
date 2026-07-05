"""Semantic model version parsing and ordering."""

import pytest

from guardian_edge.domain.errors import ModelValidationError
from guardian_edge.domain.model import ModelVersion


def test_parses_and_round_trips() -> None:
    version = ModelVersion.parse("1.2.3")
    assert (version.major, version.minor, version.patch) == (1, 2, 3)
    assert str(version) == "1.2.3"
    assert str(ModelVersion.parse("2.0.0-rc.1")) == "2.0.0-rc.1"


@pytest.mark.parametrize("text", ["1.2", "v1.2.3", "1.2.3.4", "latest", "", "1.a.0"])
def test_rejects_non_semver(text: str) -> None:
    with pytest.raises(ModelValidationError):
        ModelVersion.parse(text)
    assert ModelVersion.try_parse(text) is None


def test_orders_numerically_not_lexicographically() -> None:
    assert ModelVersion.parse("1.10.0") > ModelVersion.parse("1.2.0")
    assert ModelVersion.parse("2.0.0") > ModelVersion.parse("1.99.99")


def test_release_outranks_prerelease_of_same_triple() -> None:
    assert ModelVersion.parse("1.0.0") > ModelVersion.parse("1.0.0-rc.1")
    assert ModelVersion.parse("1.0.1-rc.1") > ModelVersion.parse("1.0.0")


def test_equality() -> None:
    assert ModelVersion.parse("1.0.0") == ModelVersion.parse("1.0.0")
    assert ModelVersion.parse("1.0.0") != ModelVersion.parse("1.0.0-beta")
