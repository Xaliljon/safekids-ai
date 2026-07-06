"""Training-ready export: what Sprint 19 (Colab) consumes, automatically.

Every published dataset version carries a ``training/`` directory:

    training/
      data.yaml                  # dataset descriptor (paths, class names)
      images/{train,val,test}/   # annotated frames, extracted from clips
      labels/{train,val,test}/   # one txt per image: "<class> cx cy w h"
      metadata.json              # provenance back to the dataset version

Only frames that carry boxes are exported (a detector trains on boxes);
event spans stay in the dataset itself for temporal models. Extraction
is deterministic: frame indices come from the annotations, encoding is
PNG, ordering is lexicographic. No manual preparation, ever.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from guardian_ai.acquisition.errors import AcquisitionError
from guardian_ai.acquisition.taxonomy import BOX_LABELS
from guardian_ai.acquisition.workspace import SPLIT_NAMES, DatasetWorkspace

TRAINING_DIR = "training"
DATA_YAML = "data.yaml"

CLASS_NAMES = sorted(BOX_LABELS)  # stable class indices across all exports


def export_training_ready(workspace: DatasetWorkspace, destination: Path) -> dict[str, Any]:
    """Extract annotated frames + labels for every split. Returns a summary."""
    import cv2

    counts = dict.fromkeys(SPLIT_NAMES, 0)
    for split in SPLIT_NAMES:
        images_dir = destination / "images" / split
        labels_dir = destination / "labels" / split
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)
        for clip_id in sorted(workspace.clip_ids(split)):
            annotation = workspace.annotation(clip_id)
            annotated = {frame.index: frame for frame in annotation.frames if frame.boxes}
            if not annotated:
                continue
            capture = cv2.VideoCapture(str(workspace.video_path(clip_id)))
            try:
                for index in sorted(annotated):
                    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                    ok, frame = capture.read()
                    if not ok:
                        raise AcquisitionError(
                            f"training export: cannot read frame {index} of '{clip_id}'"
                        )
                    stem = f"{clip_id}-{index:06d}"
                    if not cv2.imwrite(str(images_dir / f"{stem}.png"), frame):
                        raise AcquisitionError(
                            f"training export: cannot write frame image '{stem}'"
                        )
                    lines = []
                    for box in annotated[index].boxes:
                        x, y, w, h = box.box
                        class_index = CLASS_NAMES.index(box.label)
                        lines.append(
                            f"{class_index} {x + w / 2:.6f} {y + h / 2:.6f} {w:.6f} {h:.6f}"
                        )
                    (labels_dir / f"{stem}.txt").write_text(
                        "\n".join(lines) + "\n", encoding="utf-8"
                    )
                    counts[split] += 1
            finally:
                capture.release()

    data = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "nc": len(CLASS_NAMES),
        "names": CLASS_NAMES,
    }
    (destination / DATA_YAML).write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")

    manifest = workspace.manifest
    summary = {
        "dataset": manifest.name,
        "taxonomy": workspace.manifest_raw()["taxonomy"],
        "classes": CLASS_NAMES,
        "images": counts,
        "license": manifest.license,
    }
    (destination / "metadata.json").write_text(json.dumps(summary, indent=2), "utf-8")
    return summary
