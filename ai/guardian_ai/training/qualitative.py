"""Qualitative report: a fixed random sample of validation predictions,
rendered as PNGs with ground truth AND predicted boxes drawn side by
side in color — so a reviewer can see failure modes without reading
error-analysis.json.

Runs its own small, bounded inference pass (independent of the full
evaluation sweep) so exporting 50 images never has to hold a whole
20,000-image split's pixels in memory. Boxes are drawn on the
letterboxed canvas — exactly the padded square the model actually saw —
not the original source frame, so box coordinates never need an inverse
transform.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from guardian_ai.training.video_data import VideoRegistryDataModule

QUALITATIVE_DIR = "qualitative"
_GT_COLOR = (80, 220, 130)
_PRED_COLOR = (90, 200, 240)
_BOX_WIDTH = 2


def export_qualitative_samples(
    model: Any,
    family: Any,
    data_module: VideoRegistryDataModule,
    split_name: str,
    destination: Path,
    count: int = 50,
    seed: int = 0,
    score_threshold: float = 0.25,
) -> list[Path]:
    """Render up to ``count`` random predictions from ``split_name``."""
    import torch

    all_paths = data_module.split(split_name)
    if not all_paths:
        raise ValueError(f"split '{split_name}' has no images to sample from")
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not crypto
    chosen = rng.sample(all_paths, min(count, len(all_paths)))

    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    device = next(model.parameters()).device
    model.eval()
    for image_path in chosen:
        sample = data_module.load_one(image_path, split_name)
        with torch.no_grad():
            outputs = model(torch.from_numpy(sample.image[np.newaxis, ...]).to(device))
        (prediction,) = family.decode(outputs)

        canvas = data_module.load_canvas(image_path)
        image = Image.fromarray(canvas)
        draw = ImageDraw.Draw(image)
        width, height = image.size

        for box, label in zip(sample.boxes, sample.labels, strict=True):
            _draw_box(
                draw,
                box,
                width,
                height,
                _GT_COLOR,
                f"GT: {data_module.class_names[int(label)]}",
            )
        for box, score, label in zip(
            prediction.boxes, prediction.scores, prediction.labels, strict=True
        ):
            if score < score_threshold:
                continue
            _draw_box(
                draw,
                box,
                width,
                height,
                _PRED_COLOR,
                f"{data_module.class_names[int(label)]} {score:.2f}",
            )

        out_path = destination / f"{image_path.stem}.png"
        image.save(out_path)
        written.append(out_path)
    model.train()
    return written


def _draw_box(
    draw: ImageDraw.ImageDraw,
    box_cxcywh_norm: np.ndarray,
    width: int,
    height: int,
    color: tuple[int, int, int],
    text: str,
) -> None:
    cx, cy, w, h = box_cxcywh_norm
    x1, y1 = (cx - w / 2) * width, (cy - h / 2) * height
    x2, y2 = (cx + w / 2) * width, (cy + h / 2) * height
    draw.rectangle([x1, y1, x2, y2], outline=color, width=_BOX_WIDTH)
    draw.text((max(0.0, x1 + 2), max(0.0, y1 - 12)), text, fill=color)
