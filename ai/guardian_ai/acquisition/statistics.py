"""Dataset statistics: the mechanical inputs to bias review (docs/04).

Computes the numbers the spec mandates — videos, duration, classes and
balance, average fall/clip duration, fps/resolution distributions,
camera angles — and renders ``dataset-report.pdf``. Generated, never
hand-made.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from guardian_ai.acquisition.workspace import SPLIT_NAMES, DatasetWorkspace  # noqa: E402

DATASET_REPORT_FILE = "dataset-report.pdf"


def compute_statistics(workspace: DatasetWorkspace) -> dict[str, Any]:
    box_labels: Counter[str] = Counter()
    event_labels: Counter[str] = Counter()
    fps_distribution: Counter[str] = Counter()
    resolution_distribution: Counter[str] = Counter()
    camera_angles: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    split_sizes = {split: len(workspace.clip_ids(split)) for split in SPLIT_NAMES}

    clip_durations: list[float] = []
    fall_durations: list[float] = []

    for clip_id in workspace.clip_ids():
        annotation = workspace.annotation(clip_id)
        metadata = workspace.metadata(clip_id)
        duration = annotation.frame_count / annotation.fps
        clip_durations.append(duration)
        fps_distribution[f"{annotation.fps:g}"] += 1
        resolution_distribution[f"{annotation.width}x{annotation.height}"] += 1
        camera_angles[
            str(metadata.get("attr_camera_angle") or metadata.get("camera_angle") or "unknown")
        ] += 1
        sources[str(metadata.get("source_dataset", "unknown"))] += 1
        for frame in annotation.frames:
            for box in frame.boxes:
                box_labels[box.label] += 1
        for event in annotation.events:
            event_labels[event.label] += 1
            if event.label == "fall":
                fall_durations.append((event.end_frame - event.start_frame + 1) / annotation.fps)

    total_events = sum(event_labels.values())
    return {
        "videos": len(clip_durations),
        "total_duration_s": round(sum(clip_durations), 2),
        "average_clip_duration_s": _mean(clip_durations),
        "average_fall_duration_s": _mean(fall_durations),
        "splits": split_sizes,
        # Which groups sit where, and which of those were placed by
        # decision rather than by hash. A held-out corpus makes the test
        # number mean something quite different, and a reader comparing
        # two reports has no way to know unless it says so here.
        "split_groups": sorted(set(workspace.split_groups().values())),
        "split_pins": workspace.split_pins(),
        "straddling_groups": workspace.straddling_groups(),
        "box_labels": dict(box_labels),
        "event_labels": dict(event_labels),
        "class_balance": {
            label: round(count / total_events, 4) for label, count in sorted(event_labels.items())
        }
        if total_events
        else {},
        "fps_distribution": dict(fps_distribution),
        "resolution_distribution": dict(resolution_distribution),
        "camera_angles": dict(camera_angles),
        "sources": dict(sources),
    }


def generate_dataset_report(workspace: DatasetWorkspace, destination: Path | None = None) -> Path:
    """Render dataset-report.pdf from the computed statistics."""
    statistics = compute_statistics(workspace)
    manifest = workspace.manifest
    destination = destination or workspace.root / "metadata" / DATASET_REPORT_FILE
    destination.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(destination) as pdf:
        # page 1: the facts, on paper
        figure, axis = plt.subplots(figsize=(8.27, 11.69))
        axis.axis("off")
        lines = [
            f"Guardian Dataset Report — {manifest.name}",
            "",
            f"videos                 {statistics['videos']}",
            f"total duration         {statistics['total_duration_s']:.1f} s",
            f"avg clip duration      {statistics['average_clip_duration_s']:.2f} s",
            f"avg fall duration      {statistics['average_fall_duration_s']:.2f} s",
            f"splits                 {statistics['splits']}",
            "",
            "event classes:",
            *(
                f"  {label:<12} {count:>5}   ({statistics['class_balance'].get(label, 0):.1%})"
                for label, count in sorted(statistics["event_labels"].items())
            ),
            "",
            "box classes:",
            *(
                f"  {label:<12} {count:>5}"
                for label, count in sorted(statistics["box_labels"].items())
            ),
            "",
            f"fps distribution       {statistics['fps_distribution']}",
            f"resolutions            {statistics['resolution_distribution']}",
            f"camera angles          {statistics['camera_angles']}",
            f"sources                {statistics['sources']}",
            "",
            f"consent reference      {manifest.consent_reference}",
            f"contains minors        {manifest.contains_minors}",
            f"license                {manifest.license}",
        ]
        axis.text(0.05, 0.97, "\n".join(lines), family="monospace", fontsize=10, va="top")
        pdf.savefig(figure)
        plt.close(figure)

        # page 2: class balance + splits, visually
        figure, axes = plt.subplots(2, 2, figsize=(8.27, 11.69))
        _bar(axes[0][0], statistics["event_labels"], "Event class balance")
        _bar(axes[0][1], statistics["box_labels"], "Box class balance")
        _bar(axes[1][0], statistics["splits"], "Split sizes")
        _bar(axes[1][1], statistics["camera_angles"], "Camera angles")
        figure.suptitle(f"{manifest.name} — distributions")
        figure.tight_layout()
        pdf.savefig(figure)
        plt.close(figure)
    return destination


def _bar(axis: Any, counts: dict[str, int], title: str) -> None:
    axis.set_title(title, fontsize=10)
    if counts:
        names = sorted(counts)
        axis.bar(names, [counts[name] for name in names], color="#6eaaff")
        axis.tick_params(axis="x", rotation=45, labelsize=8)
    else:
        axis.text(0.5, 0.5, "no data", ha="center", va="center")
        axis.set_xticks(())


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0
