# AI Training Platform (Training Pipeline v1)

- **Date:** 2026-07-06 (Sprint 17)
- **Reflects:** ADR-0003 (detector licensing), ADR-0008/0009 (inference runtime & model zoo), ADR-0010 (dataset platform)
- **Scope:** the platform only — **no model has been trained**; real training starts after the architecture review

## Purpose

One reproducible road from a registered dataset to a model the Edge Box can
load — with a permanent record at every step and a human decision at the end:

```
 Dataset Registry (Sprint 7)          ai/training/runs/<experiment-id>/
 ────────────────────────────         ──────────────────────────────────
 quality + privacy + taxonomy   ───▶  train    ─▶ checkpoints/{last,best}.pt
 gates already passed                 evaluate ─▶ reports/evaluation.json
                                      report   ─▶ confusion_matrix.png, pr_curve.png,
                                                  loss_curve.png, summary.pdf
                                      export   ─▶ export/model.onnx  (validated)
                                                  export/manifest.json (generated)
                                      compare  ─▶ comparison.json  PROMOTE | REJECT
                                           │
                                           ▼  manual approval only (--approved-by)
                                      Guardian Model Zoo  models/<name>/<version>/
                                           │
                                           ▼  separate manual guardianctl step
                                      Guardian Edge Box  (ONNX only — never PyTorch)
```

Everything lives in `ai/`. Edge, Mobile and Backend are untouched;
`torch` is an `ai/`-only dependency and never crosses the export boundary.

## Architecture

```
guardian_ai/
  training/
    config.py      YAML -> frozen TrainingConfig; unknown keys fail loudly
    experiment.py  experiment.json per run — "no anonymous models"
    data.py        RegistryDataModule — the registry is the ONLY door to data
    families.py    DetectorFamily port: build/loss/decode/tensor names
    engine.py      Trainer: seeded loop, checkpoints, early stopping, resume
    compare.py     candidate vs baseline -> PROMOTE/REJECT with reasons
    promote.py     manual, gated, audited copy into the model zoo
    reports.py     PNG/PDF visual reports (matplotlib Agg)
  evaluation/
    detection.py   pure-numpy metrics: P/R/F1, mAP@50, mAP@50-95,
                   confusion matrix (+background), absolute FP/FN, per-class
  export/
    onnx_export.py torch -> ONNX (opset 17, batch=1) + structural check
                   + torch/onnxruntime parity — divergence is rejected
    manifest.py    automatic manifest generation (the only writer)
    compat.py      Guardian compatibility contract, mirrored from the zoo
  train/           CLI: python -m guardian_ai.train <command>
```

### Detector families — training never depends on one detector

`DetectorFamily` is a port: `build()`, `loss()`, `decode()`, `input_name()`,
`output_name()`. The engine speaks only this protocol, so a new architecture
is one registered family, never an engine change.

| Family | Status | Why |
|---|---|---|
| `tiny-ssd` | ✅ trainable | smoke family: small enough to genuinely train in tests; proves the whole platform |
| `yolox-tiny` | 🔒 reserved | the production family; lands with the first REAL run, gated behind this sprint's architecture review |
| `yolov8`, `yolo11` | 🔒 blocked | AGPL-3.0 (ADR-0003) — no compliant path approved |
| `rt-detr` | 🔒 reserved | Apache-2.0; scheduled after YOLOX |

A config referencing a reserved family fails at load time with the exact
reason — never silently.

## Experiment lifecycle

1. `train --config <yaml>` — the YAML is the full recipe (family, dataset
   coordinates, optimizer, scheduler, augmentation, early stopping, seed).
   Misspelled keys are errors; a silently defaulted knob would be a lie in
   the record.
2. The run gets an isolated directory `runs/<utc>-<name>-<id>/` and an
   `experiment.json` holding: dataset **name+version**, taxonomy version,
   git commit, full config, timings, metrics, artifact checksums, promotion
   record. A model without this record does not exist for promotion.
3. Every epoch writes `last.pt`; the best validation metric writes `best.pt`.
   `resume --run <dir>` restores model, optimizer, scheduler, epoch counter
   and early-stopping state — an interruption costs at most one epoch.
4. Same config + same seed ⇒ identical history (asserted by tests).

## Evaluation

`evaluate` runs the best checkpoint over the test split and writes
`reports/evaluation.json` with the mandated set: precision, recall, F1,
mAP@50, mAP@50-95, per-class metrics, absolute FP/FN counts and a confusion
matrix with a background row/column (so every false positive and miss is
visible, not averaged away). `report` renders the four visual artifacts.
All metric code is pure numpy, verified against hand-computed cases.

## Export and validation

`export` is not "done" when the file exists:

1. `torch.onnx.export` (opset 17, batch=1, named tensors),
2. ONNX structural checker,
3. **parity proof** — one inference in torch and onnxruntime on the same
   input; max |Δ| > 1e-4 ⇒ `ExportRejectedError`, nothing else happens,
4. `manifest.json` generated (SHA256, labels, dataset+taxonomy versions,
   experiment id, git commit, license, edge compatibility) — hand-editing
   is indistinguishable from lying, so this module is the only writer,
5. Guardian compatibility check against the zoo contract: single float32
   NCHW input with batch fixed at 1, named outputs, manifest/artifact
   checksum agreement, license on the on-device allowlist (ADR-0003),
   compatibility schema 1. Any violation ⇒ `CompatibilityError`.

## Comparison and promotion

`compare --candidate --baseline` benchmarks both ONNX artifacts
(latency, memory, size) and diffs the evaluations:

- precision and recall may not regress (small slack for eval noise),
- extra false positives pass **only** if precision held — they must be the
  price of real recall gains, not noise (and a dead baseline that predicts
  nothing is not unbeatable),
- latency may grow ≤ 20 %, size ≤ 50 %.

The verdict (`PROMOTE`/`REJECT` + reasons) is **advisory**. Promotion itself:

- `promote --run <dir> --zoo <root> --approved-by <name>` — refuses without
  a named human, re-runs the compatibility check on the bytes that ship,
  copies `model.onnx` + `manifest.json` into `models/<name>/<version>/`
  (versions are immutable), and writes the approval into `experiment.json`.
- Activating the model on a box stays a separate manual `guardianctl` step —
  promotion never flips `state.json`.

## Colab

`ai/training/notebooks/colab.ipynb`: mount Drive → install → publish the
synthetic dataset → train → evaluate → export → copy the validated ONNX to
Drive. Every step is the same CLI; the notebook adds no logic. Promotion is
deliberately not runnable from Colab.

`ai/training/notebooks/model-v1-training.ipynb` (Sprint 19) is the same
pattern for the first real run: mount Drive → clone the repo → copy the
*published* `guardian-fall-detection-v1` registry export from Drive →
train on a T4 with `ai/training/configs/model-v1.yaml` → evaluate →
error analysis → qualitative export → validated ONNX export → benchmark
→ COCO-pretrained comparison → mark candidate. Same CLI, same "no zoo
writes from Colab" rule.

## Failure recovery

| Failure | Recovery |
|---|---|
| interrupted training (Ctrl-C, crash, Colab disconnect) | `resume --run <dir>` — loses at most one epoch |
| corrupt/tampered ONNX | sha256 re-check at compat + promotion time rejects it |
| diverging export | parity check rejects at export time; no manifest written |
| wrong config key | load fails with the key name; nothing runs |
| unregistered dataset | `RegistryDataModule`/`VideoRegistryDataModule` refuses — no loose folders |
| duplicate zoo version | promotion refuses; bump the version |
| a real split has tens of thousands of images | `VideoRegistryDataModule.batches()` is lazy (`LazyBatches`) — decodes one batch at a time, O(batch_size) peak memory, never the whole split |

## Sprint 19: the first production model (YOLOX-Tiny)

`yolox-tiny` (`ai/guardian_ai/training/yolox_tiny.py`) is a from-scratch,
anchor-free, multi-scale `DetectorFamily` — CSPDarknet-tiny-style
backbone, PAFPN-lite neck, decoupled head over strides 8/16/32 — unlocked
from Sprint 17's reservation now that the architecture review covers it.
Target assignment is a **documented simplification** of the paper's
SimOTA (center-region candidates + nearest-k, not optimal transport); see
the module's docstring for exactly what differs and why.

Real published video datasets (Sprint 18) export one training image per
*annotated frame*, not per clip — `guardian-fall-detection-v1`'s 357
clips are 19,940/1,269/3,692 train/val/test images. Training reads this
through `VideoRegistryDataModule` (`dataset.format: video`), which
resolves the dataset via `VideoDatasetRegistry.get()` (checksum-verified)
and letterboxes each image onto a square canvas matching the model's
input size, transforming box coordinates through the identical padding.

New evaluation-adjacent modules, all built on the same per-image greedy
matching `evaluate_detections` already uses (so metrics and diagnostics
can never quietly disagree):

- `evaluation/error_analysis.py` — top FP/FN images, worst-confidence
  false positives, worst-localized true positives, most confused class
  pairs → `error-analysis.json`.
- `training/qualitative.py` — renders N random predictions (ground truth
  + predicted boxes, with confidence) on the letterboxed canvas the model
  actually saw → PNGs.
- `training/coco_baseline.py` — the mandated "COCO-pretrained vs Guardian
  model" comparison. Fetches the official Apache-2.0 YOLOX-Tiny COCO
  checkpoint through the **existing**, already-reviewed
  `edge/guardian_edge/tools/install_yolox.py` installer (a subprocess
  call to a sibling app's CLI, not an in-process import — ADR-0001 still
  holds), decodes its output independently (matching the documented
  contract, never importing `edge/` code), and evaluates it with our own
  harness on the same images.

**Candidate, not promoted.** `train/__init__.py`'s `candidate` command
writes `status: candidate, not_production: true` into `experiment.json`
and does **nothing else** — no zoo write, no activation. Promotion
(`promote`) remains a separate, later, human decision. See
[reports/model-v1/](../reports/model-v1/) for the actual run: a bounded
256-image/6-epoch local validation (the real 19,940-image/30-epoch spec
run needs the Colab notebook's GPU) that proves the pipeline end to end
and — honestly, on real numbers — loses to the COCO baseline, exactly as
expected at that scale.

## Testing

348 platform tests (`ai/tests/test_training_*`, `test_evaluation_*`,
`test_export_*`, `test_train_cli*.py`, `test_training_workspace.py`,
`test_yolox_tiny.py`, `test_video_data.py`, `test_error_analysis.py`,
`test_qualitative.py`, `test_coco_baseline.py`, `test_model_v1_notebook.py`)
cover config validation, the experiment record, registry-only data access
(both formats), smoke training + resume + early stopping +
reproducibility, hand-computed metrics, report artifacts, export parity +
rejection, the full compatibility contract, PROMOTE/REJECT verdicts, the
promotion gates, YOLOX-Tiny's build/loss/assignment/decode/export, lazy
video batching (including multi-worker determinism and memory bounds),
error analysis, qualitative export, COCO-baseline decode math, and the
CLI end to end on synthetic datasets. Coverage over the training/
evaluation modules: 96 %.
