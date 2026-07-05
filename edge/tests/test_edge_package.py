"""Scaffold smoke test: the package imports and declares a version."""

from guardian_edge import __version__


def test_package_imports() -> None:
    assert __version__
