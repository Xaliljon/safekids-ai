"""Quality validation: leakage, duplicates, labels, split sizes."""

from dataset_fixtures import make_record

from guardian_ai.datasets.annotations import SampleRecord
from guardian_ai.datasets.quality import Severity, validate_quality
from guardian_ai.datasets.taxonomy import GUARDIAN_TAXONOMY_V1


def test_clean_dataset_passes() -> None:
    splits = {
        "train": [make_record(f"images/t{i}.jpg") for i in range(4)],
        "val": [make_record("images/v0.jpg")],
    }
    report = validate_quality(splits, GUARDIAN_TAXONOMY_V1)
    assert report.ok
    assert report.issues == ()


def test_cross_split_leakage_is_an_error() -> None:
    shared = make_record("images/leaked.jpg")
    report = validate_quality(
        {"train": [shared], "val": [shared]},
        GUARDIAN_TAXONOMY_V1,
    )
    assert not report.ok
    assert any("leaks across splits" in issue.message for issue in report.errors)


def test_duplicates_within_a_split_are_an_error() -> None:
    record = make_record("images/dup.jpg")
    report = validate_quality({"train": [record, record]}, GUARDIAN_TAXONOMY_V1)
    assert any("duplicate sample" in issue.message for issue in report.errors)


def test_unknown_label_is_an_error() -> None:
    report = validate_quality(
        {"train": [make_record(labels=("unicorn",))]},
        GUARDIAN_TAXONOMY_V1,
    )
    assert any("'unicorn' is not in taxonomy" in issue.message for issue in report.errors)


def test_empty_split_is_an_error() -> None:
    report = validate_quality(
        {"train": [make_record()], "test": []},
        GUARDIAN_TAXONOMY_V1,
    )
    assert any("'test' is empty" in issue.message for issue in report.errors)


def test_tiny_images_and_background_ratio_are_warnings_not_errors() -> None:
    tiny = SampleRecord(path="images/tiny.jpg", width=16, height=16)
    backgrounds = [make_record(f"images/bg{i}.jpg", labels=()) for i in range(3)]
    report = validate_quality(
        {"train": [tiny, *backgrounds]},
        GUARDIAN_TAXONOMY_V1,
    )
    assert report.ok, "warnings must not block publication"
    messages = [issue.message for issue in report.warnings]
    assert any("suspiciously small" in message for message in messages)
    assert any("no annotations" in message for message in messages)
    assert all(issue.severity is Severity.WARNING for issue in report.warnings)
