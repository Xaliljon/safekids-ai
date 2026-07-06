"""Visual reports: every artifact generated, never hand-made."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from guardian_ai.evaluation.detection import evaluate_detections
from guardian_ai.training.families import Prediction
from guardian_ai.training.reports import (
    CONFUSION_PNG,
    LOSS_CURVE_PNG,
    PR_CURVE_PNG,
    SUMMARY_PDF,
    generate_reports,
    load_history,
)


def make_evaluation() -> dict:
    box = np.array([[0.5, 0.5, 0.3, 0.3]], dtype=np.float32)
    prediction = Prediction(
        boxes=box,
        scores=np.array([0.9], dtype=np.float32),
        labels=np.array([1], dtype=np.int64),
    )
    return evaluate_detections(
        [prediction], [(box, np.array([1], dtype=np.int64))], ["adult", "child"]
    )


HISTORY = [
    {"epoch": 0, "train_loss": 2.5, "val_f1": 0.0},
    {"epoch": 1, "train_loss": 1.2, "val_f1": 0.4},
]


def test_generate_reports_writes_all_four(tmp_path: Path) -> None:
    written = generate_reports(make_evaluation(), HISTORY, tmp_path, title="unit")
    names = {path.name for path in written}
    assert names == {CONFUSION_PNG, PR_CURVE_PNG, LOSS_CURVE_PNG, SUMMARY_PDF}
    for path in written:
        assert path.is_file()
        assert path.stat().st_size > 0
    assert (tmp_path / CONFUSION_PNG).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / SUMMARY_PDF).read_bytes()[:5] == b"%PDF-"


def test_reports_survive_empty_history(tmp_path: Path) -> None:
    written = generate_reports(make_evaluation(), [], tmp_path, title="empty")
    assert all(path.is_file() for path in written)


def test_load_history_missing_returns_empty(tmp_path: Path) -> None:
    assert load_history(tmp_path) == []
