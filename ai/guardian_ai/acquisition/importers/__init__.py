"""Dataset importers: raw datasets never enter Guardian directly.

Every importer converts one documented raw layout into guardian_dataset_v1
(normalized video + Guardian annotation + provenance metadata). The
registry of importers is what the CLI's ``import <source>`` resolves.
"""

from __future__ import annotations

from collections.abc import Callable

from guardian_ai.acquisition.errors import ImporterError
from guardian_ai.acquisition.importers.base import DatasetImporter

_IMPORTERS: dict[str, Callable[[], DatasetImporter]] = {}


def register_importer(name: str, factory: Callable[[], DatasetImporter]) -> None:
    _IMPORTERS[name] = factory


def available_importers() -> list[str]:
    return sorted(_IMPORTERS)


def get_importer(name: str) -> DatasetImporter:
    factory = _IMPORTERS.get(name)
    if factory is None:
        raise ImporterError(f"unknown dataset source '{name}' (available: {available_importers()})")
    return factory()


def _register_builtin() -> None:
    from guardian_ai.acquisition.importers.gmdcsa24 import Gmdcsa24Importer
    from guardian_ai.acquisition.importers.le2i import Le2iImporter
    from guardian_ai.acquisition.importers.urfall import UrFallImporter

    register_importer(UrFallImporter.source, UrFallImporter)
    register_importer(Le2iImporter.source, Le2iImporter)
    register_importer(Gmdcsa24Importer.source, Gmdcsa24Importer)


_register_builtin()
