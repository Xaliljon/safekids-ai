"""Privacy checker: the docs/04 floor, mechanically enforced."""

from dataset_fixtures import make_manifest, make_record

from guardian_ai.datasets.privacy import check_privacy


def resolves(_reference: str) -> bool:
    """Stands in for a real ethics-review store (ADR-0005 §3). Tests that
    assert a *clean* dataset must supply one: without a resolver the
    checker refuses minors' data on principle, which is its own test."""
    return True


def test_clean_dataset_passes() -> None:
    report = check_privacy(
        make_manifest(),
        {"train": [make_record(attributes={"scene": "classroom"})]},
        resolves,
    )
    assert report.ok


def test_missing_consent_reference_is_a_violation() -> None:
    report = check_privacy(make_manifest(consent_reference=""), {"train": [make_record()]})
    assert any("consent_reference" in violation.message for violation in report.violations)


def test_minors_without_ethics_review_is_a_violation() -> None:
    manifest = make_manifest(contains_minors=True, review_reference="")
    report = check_privacy(manifest, {"train": [make_record()]})
    assert any("review_reference" in violation.message for violation in report.violations)


def test_no_minors_needs_no_review_reference() -> None:
    manifest = make_manifest(contains_minors=False, review_reference="")
    assert check_privacy(manifest, {"train": [make_record()]}, resolves).ok


def test_identity_attribute_keys_are_violations() -> None:
    record = make_record(attributes={"student_id": "S-1024"})
    report = check_privacy(make_manifest(), {"train": [record]})
    assert any("'student_id'" in violation.message for violation in report.violations)


def test_identity_keys_on_annotations_are_caught_too() -> None:
    record = make_record(annotation_attributes={"Name": "somebody"})
    report = check_privacy(make_manifest(), {"train": [record]})
    assert any("'Name'" in violation.message for violation in report.violations)


def test_email_and_phone_values_are_violations() -> None:
    record = make_record(
        attributes={"note": "contact parent@example.com or +998 90 123 45 67"},
    )
    report = check_privacy(make_manifest(), {"train": [record]})
    assert any("email" in violation.message for violation in report.violations)


def test_absolute_and_escaping_paths_are_violations() -> None:
    for path in ("/home/collector/images/a.jpg", "../outside.jpg"):
        report = check_privacy(make_manifest(), {"train": [make_record(path)]})
        assert not report.ok, path
