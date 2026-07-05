"""Scaffold smoke test: the package imports and declares a version."""

from app import __version__


def test_package_imports() -> None:
    assert __version__
