"""Dataset quality validation.

Structural integrity checks a dataset must pass before publication:
duplicates, cross-split leakage, unknown labels, empty splits. ERRORs block
publication; WARNINGs are surfaced for human judgment. Quality issues in a
safety dataset become false negatives in a kindergarten — this gate is not
cosmetic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, unique

from guardian_ai.datasets.annotations import SampleRecord
from guardian_ai.datasets.taxonomy import LabelTaxonomy

_TINY_DIMENSION_PX = 32
_BACKGROUND_WARNING_FRACTION = 0.5


@unique
class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    severity: Severity
    message: str
    sample: str | None = None


@dataclass(frozen=True, slots=True)
class QualityReport:
    issues: tuple[QualityIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)


def validate_quality(
    splits: Mapping[str, Sequence[SampleRecord]], taxonomy: LabelTaxonomy
) -> QualityReport:
    """Validate structural quality of a split dataset against its taxonomy."""
    issues: list[QualityIssue] = []
    issues.extend(_check_duplicates_and_leakage(splits))
    issues.extend(_check_labels(splits, taxonomy))
    issues.extend(_check_split_sizes(splits))
    issues.extend(_check_sample_sanity(splits))
    return QualityReport(issues=tuple(issues))


def _check_duplicates_and_leakage(
    splits: Mapping[str, Sequence[SampleRecord]],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    seen: dict[str, str] = {}  # path -> split
    for split_name, records in splits.items():
        in_this_split: set[str] = set()
        for record in records:
            if record.path in in_this_split:
                issues.append(
                    QualityIssue(
                        Severity.ERROR,
                        f"duplicate sample in split '{split_name}'",
                        sample=record.path,
                    )
                )
            in_this_split.add(record.path)
            previous_split = seen.get(record.path)
            if previous_split is not None and previous_split != split_name:
                issues.append(
                    QualityIssue(
                        Severity.ERROR,
                        f"sample leaks across splits '{previous_split}' and '{split_name}' — "
                        f"evaluation on training data is invisible overfitting",
                        sample=record.path,
                    )
                )
            seen.setdefault(record.path, split_name)
    return issues


def _check_labels(
    splits: Mapping[str, Sequence[SampleRecord]], taxonomy: LabelTaxonomy
) -> list[QualityIssue]:
    known = taxonomy.label_names()
    issues: list[QualityIssue] = []
    for records in splits.values():
        for record in records:
            for annotation in record.annotations:
                if annotation.label not in known:
                    issues.append(
                        QualityIssue(
                            Severity.ERROR,
                            f"label '{annotation.label}' is not in taxonomy "
                            f"{taxonomy.name} v{taxonomy.version}",
                            sample=record.path,
                        )
                    )
    return issues


def _check_split_sizes(splits: Mapping[str, Sequence[SampleRecord]]) -> list[QualityIssue]:
    return [
        QualityIssue(Severity.ERROR, f"split '{name}' is empty")
        for name, records in splits.items()
        if not records
    ]


def _check_sample_sanity(splits: Mapping[str, Sequence[SampleRecord]]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    total = 0
    background = 0
    for records in splits.values():
        for record in records:
            total += 1
            if not record.annotations:
                background += 1
            if record.width < _TINY_DIMENSION_PX or record.height < _TINY_DIMENSION_PX:
                issues.append(
                    QualityIssue(
                        Severity.WARNING,
                        f"suspiciously small image ({record.width}x{record.height})",
                        sample=record.path,
                    )
                )
    if total and background / total > _BACKGROUND_WARNING_FRACTION:
        issues.append(
            QualityIssue(
                Severity.WARNING,
                f"{background}/{total} samples have no annotations — verify this "
                f"background ratio is intentional",
            )
        )
    return issues
