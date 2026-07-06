"""Visual reports: what happened, on paper.

Every run gets confusion_matrix.png, pr_curve.png, loss_curve.png and a
metrics summary.pdf under its ``reports/`` directory — generated, never
hand-made, so a run can be judged without opening a notebook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: training servers have no display
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

CONFUSION_PNG = "confusion_matrix.png"
PR_CURVE_PNG = "pr_curve.png"
LOSS_CURVE_PNG = "loss_curve.png"
SUMMARY_PDF = "summary.pdf"


def generate_reports(
    evaluation: dict[str, Any],
    history: list[dict[str, Any]],
    reports_dir: Path,
    title: str,
) -> list[Path]:
    """All four artifacts; returns what was written."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _confusion_matrix(evaluation, reports_dir / CONFUSION_PNG, title),
        _pr_curve(evaluation, reports_dir / PR_CURVE_PNG, title),
        _loss_curve(history, reports_dir / LOSS_CURVE_PNG, title),
    ]
    written.append(_summary_pdf(evaluation, history, reports_dir / SUMMARY_PDF, title))
    return written


def _confusion_matrix(evaluation: dict[str, Any], path: Path, title: str) -> Path:
    labels = evaluation["confusion_matrix"]["labels"]
    matrix = evaluation["confusion_matrix"]["matrix"]
    figure, axis = plt.subplots(figsize=(6, 5))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    axis.set_yticks(range(len(labels)), labels)
    axis.set_xlabel("predicted")
    axis.set_ylabel("actual")
    axis.set_title(f"Confusion matrix — {title}")
    for row in range(len(labels)):
        for column in range(len(labels)):
            axis.text(column, row, str(matrix[row][column]), ha="center", va="center")
    figure.colorbar(image)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path


def _pr_curve(evaluation: dict[str, Any], path: Path, title: str) -> Path:
    figure, axis = plt.subplots(figsize=(6, 5))
    for name, metrics in evaluation["per_class"].items():
        axis.scatter(
            metrics["recall"],
            metrics["precision"],
            label=f"{name} (ap50={metrics['ap50']:.2f})",
        )
    overall = evaluation["overall"]
    axis.scatter(
        overall["recall"],
        overall["precision"],
        marker="*",
        s=200,
        label=f"overall (f1={overall['f1']:.2f})",
    )
    axis.set_xlim(0, 1.05)
    axis.set_ylim(0, 1.05)
    axis.set_xlabel("recall")
    axis.set_ylabel("precision")
    axis.set_title(f"Precision / Recall — {title}")
    axis.grid(alpha=0.3)
    axis.legend(loc="lower left", fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path


def _loss_curve(history: list[dict[str, Any]], path: Path, title: str) -> Path:
    figure, axis = plt.subplots(figsize=(6, 4))
    if history:
        epochs = [entry["epoch"] for entry in history]
        axis.plot(epochs, [entry["train_loss"] for entry in history], label="train loss")
        metric_keys = [key for key in history[0] if key.startswith("val_")]
        for key in metric_keys:
            twin = axis.twinx()
            twin.plot(
                epochs,
                [entry[key] for entry in history],
                color="tab:green",
                label=key,
            )
            twin.set_ylabel(key, color="tab:green")
    axis.set_xlabel("epoch")
    axis.set_ylabel("loss")
    axis.set_title(f"Training curves — {title}")
    axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path


def _summary_pdf(
    evaluation: dict[str, Any],
    history: list[dict[str, Any]],
    path: Path,
    title: str,
) -> Path:
    with PdfPages(path) as pdf:
        figure, axis = plt.subplots(figsize=(8.27, 11.69))  # A4
        axis.axis("off")
        overall = evaluation["overall"]
        lines = [
            f"Guardian AI — training summary: {title}",
            "",
            f"precision      {overall['precision']:.4f}",
            f"recall         {overall['recall']:.4f}",
            f"f1             {overall['f1']:.4f}",
            f"mAP@50         {overall['map50']:.4f}",
            f"mAP@50-95      {overall['map50_95']:.4f}",
            f"false pos      {overall['false_positives']}",
            f"false neg      {overall['false_negatives']}",
            f"images         {overall['images']}",
            f"epochs         {len(history)}",
            "",
            "per-class:",
        ]
        for name, metrics in evaluation["per_class"].items():
            lines.append(
                f"  {name:<16} p={metrics['precision']:.3f} r={metrics['recall']:.3f} "
                f"f1={metrics['f1']:.3f} ap50={metrics['ap50']:.3f}"
            )
        axis.text(0.05, 0.95, "\n".join(lines), family="monospace", fontsize=10, va="top")
        pdf.savefig(figure)
        plt.close(figure)
    return path


def load_history(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "history.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))
