"""Semantic dataset versions.

Deliberately mirrors ``guardian_edge.domain.model.ModelVersion`` (simplified
SemVer). ai/ must not import edge code (ADR-0001); promoting one shared
implementation into ``guardian_common`` is flagged follow-up work now that a
second component needs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

from guardian_ai.datasets.errors import DatasetValidationError

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$")


@total_ordering
@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """MAJOR.MINOR.PATCH with optional -prerelease; numeric ordering."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    @classmethod
    def parse(cls, text: str) -> DatasetVersion:
        match = _VERSION_PATTERN.match(text)
        if match is None:
            raise DatasetValidationError(
                f"'{text}' is not a semantic version (expected MAJOR.MINOR.PATCH[-prerelease])"
            )
        major, minor, patch, prerelease = match.groups()
        return cls(major=int(major), minor=int(minor), patch=int(patch), prerelease=prerelease)

    @classmethod
    def try_parse(cls, text: str) -> DatasetVersion | None:
        try:
            return cls.parse(text)
        except DatasetValidationError:
            return None

    def sort_key(self) -> tuple[int, int, int, int, str]:
        return (
            self.major,
            self.minor,
            self.patch,
            1 if self.prerelease is None else 0,
            self.prerelease or "",
        )

    def __lt__(self, other: DatasetVersion) -> bool:
        return self.sort_key() < other.sort_key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.prerelease is None else f"{base}-{self.prerelease}"
