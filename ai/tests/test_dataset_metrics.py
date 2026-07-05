"""Dataset metrics for bias evaluation."""

from dataset_fixtures import make_record

from guardian_ai.datasets.metrics import compute_metrics


def test_computes_counts_and_balance() -> None:
    splits = {
        "train": [
            make_record("images/a.jpg", labels=("child", "child", "adult")),
            make_record("images/b.jpg", labels=("child",)),
            make_record("images/c.jpg", labels=()),  # background
        ],
        "val": [make_record("images/d.jpg", labels=("adult",))],
    }
    metrics = compute_metrics(splits)
    assert metrics.samples_total == 4
    assert metrics.annotations_total == 5
    assert metrics.samples_per_split == {"train": 3, "val": 1}
    assert metrics.annotations_per_label == {"adult": 2, "child": 3}
    assert metrics.background_samples == 1
    assert metrics.mean_annotations_per_sample == 1.25
    assert metrics.label_imbalance == 1.5
    assert 0.0 < metrics.mean_box_area < 1.0


def test_single_label_has_no_imbalance_ratio() -> None:
    metrics = compute_metrics({"train": [make_record(labels=("child",))]})
    assert metrics.label_imbalance is None


def test_empty_dataset_is_all_zeros() -> None:
    metrics = compute_metrics({"train": []})
    assert metrics.samples_total == 0
    assert metrics.annotations_total == 0
    assert metrics.mean_annotations_per_sample == 0.0
    assert metrics.mean_box_area == 0.0
