"""Label taxonomy: the versioned vocabulary annotations may use.

Datasets bind to a named, versioned taxonomy; annotations using labels
outside it fail quality validation. Taxonomies never contain identity
labels — Guardian AI labels *safety-relevant states of scenes*, never who
somebody is (docs/04: no facial recognition, no behavioral profiling).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from guardian_ai.datasets.errors import TaxonomyError

_LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class LabelDefinition:
    """One label and what annotators should mean by it."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        if _LABEL_PATTERN.match(self.name) is None:
            raise TaxonomyError(
                f"label '{self.name}' must be lowercase alphanumeric/underscore/hyphen"
            )


@dataclass(frozen=True, slots=True)
class LabelTaxonomy:
    """A named, versioned set of labels."""

    name: str
    version: str
    labels: tuple[LabelDefinition, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise TaxonomyError("taxonomy name must not be empty")
        if not self.labels:
            raise TaxonomyError(f"taxonomy '{self.name}' must define at least one label")
        names = [label.name for label in self.labels]
        if len(names) != len(set(names)):
            raise TaxonomyError(f"taxonomy '{self.name}' has duplicate labels: {names}")

    def label_names(self) -> frozenset[str]:
        return frozenset(label.name for label in self.labels)

    def is_known(self, label: str) -> bool:
        return label in self.label_names()


GUARDIAN_TAXONOMY_V1 = LabelTaxonomy(
    name="guardian-safety",
    version="1.0.0",
    labels=(
        LabelDefinition("person", "Any visible human, when age group is not annotated"),
        LabelDefinition("child", "Person annotators judge to be a child"),
        LabelDefinition("adult", "Person annotators judge to be an adult"),
    ),
)
"""SafeKids V1 vocabulary. Event/state labels (fallen, crying) arrive with
their own taxonomy version when those datasets are designed."""
