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
| interrupted training (Ctrl-C, crash, Colab disconnect) | every epoch atomically flushes `last.pt` (weights + optimizer + scheduler + AMP scaler + RNG state + epoch), `history.json`, `metrics.json`, `experiment.json`, `training.log`; `train --auto-resume` (or `resume --run <dir>`) continues from the next epoch — loses at most the epoch in progress (Sprint 20.1) |
| corrupt/tampered ONNX | sha256 re-check at compat + promotion time rejects it |
| diverging export | parity check rejects at export time; no manifest written |
| wrong config key | load fails with the key name; nothing runs |
| unregistered dataset | `RegistryDataModule`/`VideoRegistryDataModule` refuses — no loose folders |
| duplicate zoo version | promotion refuses; bump the version |
| a real split has tens of thousands of images | `VideoRegistryDataModule.batches()` is lazy (`LazyBatches`) — decodes one batch at a time, O(batch_size) peak memory, never the whole split |

## Sprint 19 / 19.1: the first production model (YOLOX)

Sprint 19 unlocked `yolox-tiny` from Sprint 17's reservation with a
**from-scratch** `DetectorFamily` implementation. An audit — triggered by
the trained candidate performing far worse than the official COCO
checkpoint — found the custom head could not converge objectness even
when overfitting a single real training example, traced to its zero-bias
initialization versus upstream's `prior_prob`-based init. Sprint 19.1
removed the custom implementation entirely and replaced it with
`OfficialYoloxTrainer`, wrapping the real, unmodified upstream Apache-2.0
YOLOX package (`guardian_ai/training/detectors/yolox/`). Re-running the
exact same single-example overfit test against the official
implementation converges cleanly. Full detail, including the audit
findings and the "why not just fix it" reasoning:
[architecture/detector-integration.md](detector-integration.md).

`yolox-nano`/`yolox-tiny`/`yolox-s`/`yolox-m`/`yolox-l` are all now
available (configuration-only variant selection, no hardcoding);
`model.pretrained`/`model.checkpoint` in the training YAML control
COCO-pretrained transfer learning (auto-download, checksum-pinned) or a
custom checkpoint path.

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

## Sprint 20: closing the gaps before the real run

Sprint 19.1's comparison report disclosed a real gap (SGD/lr=0.01 without
warmup numerically diverges on the official YOLOX head) and recommended
trying COCO-pretrained transfer learning. Sprint 20 closes both, purely
additively — no `DetectorFamily` protocol change, no detector-specific
code outside `training/detectors/yolox/`:

- `scheduler.warmup_epochs` (`config.py`/`engine.py`): linear warmup for
  N epochs, then the existing cosine/step schedule takes over
  (`SequentialLR`). `model-v1.yaml` now sets `warmup_epochs: 5` and
  `model.pretrained: true`, matching Sprint 20's mandated recipe.
- `experiment.json` now also records `checksums.checkpoint` (whichever
  checkpoint — custom or auto-downloaded pretrained — a family's
  `build()` loaded, read via a duck-typed `checkpoint_sha256` attribute
  on the returned model so `engine.py` never needs to know which
  detector produced it) and an `environment` block (Python/PyTorch/CUDA
  versions, GPU name) plus `duration_seconds`.
- `export/compat.py` writes `guardian-validation.json` next to
  `model.onnx` — the full compatibility check result (tensors, dynamic
  shapes, batch size, manifest, license, sha256) as a durable artifact,
  not just a stdout print.

A bounded local dry run (32 images, 8 epochs, CPU, otherwise the exact
Sprint 20 recipe) confirms the warmup fix: loss goes
`97.6 → 41.2 → 11.7 → 10.4 → 11.7 → 10.5 → 10.8 → 8.8` — finite and
trending down, where the same hyperparameters without warmup produced
`inf`/`nan` in Sprint 19.1. The real 19,940-image/30-epoch T4 run itself
has not happened — see
[reports/model-v1/sprint-20-status.md](../reports/model-v1/sprint-20-status.md)
for the full handoff.

## Colab packaging: `uv`, not `pip install -e ai` — root cause

Running the real Colab bootstrap surfaced a packaging bug: plain
`pip install -e ai` reliably fails with `AssertionError: torch is
required for pre-compiling ops, please install it first` (reproduced and
confirmed in a clean venv). This is **not** a reason to vendor YOLOX —
Sprint 19.1 deliberately chose a real, unmodified upstream dependency
over a vendored copy specifically to avoid maintaining someone else's
detector code; nothing under `guardian_ai/training/detectors/yolox/` is
YOLOX's source, only Guardian's wrapper around the installed package.

The actual root cause: pinning YOLOX to an exact git commit needs two
`[tool.uv]`-only settings that plain `pip` has no equivalent for —

- `no-build-isolation-package = ["yolox"]`, because its `setup.py` needs
  `torch` importable at build time and pip's per-package build isolation
  hides it (pip only offers an all-or-nothing `--no-build-isolation`,
  which breaks unrelated packages' own build backends when tried instead
  — confirmed: it broke `guardian-ai-models`'s own `hatchling` build),
- `override-dependencies`, because YOLOX's `requirements.txt` pins
  ancient exact `onnx`/`onnxruntime` versions that conflict with the
  modern versions our own export/eval pipeline requires.

`uv sync --project ai` — the same install path local development and CI
already use — honors both settings and installs cleanly on a fresh
clone; the Colab notebook now uses it instead of plain pip (`.venv`
lands at the workspace root, which the notebook prepends to `PATH` so
every later cell's `!python`/`!pip` transparently uses it). Full
walkthrough: [docs/COLAB_SETUP.md](../docs/COLAB_SETUP.md#why-uv-not-pip-install--e-ai).

## Sprint 20.1: resume robustness (Colab disconnects)

Colab frequently kills the runtime before a 30-epoch run completes. The
engine already checkpointed every epoch and could `resume`, but three
gaps meant a disconnect could still lose or corrupt progress, and
recovery needed a manual command. Sprint 20.1 closes them — additive
only, no protocol/boundary/workflow change:

- **Complete checkpoints.** `last.pt`/`best.pt` now also carry the AMP
  `GradScaler` state (hoisted out of `_train_epoch` so it is created once
  and persists) and the full RNG state (python/numpy/torch/cuda), so a
  resumed run continues the exact optimization *and* random stream, not
  just the weights.
- **Atomic writes.** Every per-epoch artifact — checkpoints,
  `history.json`, the new `metrics.json`, `experiment.json` — is written
  to a sibling `.tmp` then `os.replace`d into place, so a disconnect
  mid-write can never truncate `last.pt` (this matters most when the run
  directory is a Google Drive FUSE mount).
- **Per-epoch flush + log.** `metrics.json` (per-epoch train loss + val
  metric + best + planned/completed epochs) is flushed every epoch, and a
  `training.log` file handler tees the run's logs to disk per record.
  With the run directory pointed at Drive (`train --output-dir`), all of
  this survives the runtime dying.
- **Auto-resume.** `train --auto-resume` finds the newest *unfinished*
  run for the config under the output dir and continues it from the next
  epoch (a completed run is left untouched, no run yet ⇒ fresh). The
  Colab notebook uses `--auto-resume --output-dir <Drive>`, so recovery
  is just **Run All again** — no manual `resume` command. See
  [docs/COLAB_SETUP.md](../docs/COLAB_SETUP.md#resuming-after-a-disconnect-sprint-201).

## Sprint 20.2: the candidate does not fit the gate, and cannot be made to

The Sprint 20 candidate was rejected on latency alone. Sprint 20.2 profiled
the inference path to find out where that latency lives; the full matrices
are in
[`reports/model-v1/inference-optimization-report.md`](../reports/model-v1/inference-optimization-report.md)
and the methodology in
[`inference-performance.md`](inference-performance.md).

What it changes about this platform:

- **`guardian_ai.training.profiling`** is the steady-state profiler the
  promotion benchmark is not. `compare.benchmark_onnx` spreads ±37% across
  identical repeats, so it can rank two models but cannot show a 20%
  improvement. The gate's own benchmark is deliberately unchanged — a
  comparator that shifts under a sprint is not a gate.
- **`load_into` had two defects that made every Guardian checkpoint
  unloadable.** It received the bare YOLOX module while training saves the
  wrapper's state dict (`yolox_model.` prefix), so none of the 462 tensors
  matched; and it dropped the head whenever `num_classes != 80`, discarding
  exactly the weights that had been trained. Both loaded silently — the
  model ran and detected nothing. Both now decide from the checkpoint rather
  than from an assumption about it. `train resume` was unaffected: it
  `torch.load`s `last.pt` directly.

What it establishes about the candidate:

- Runtime configuration is worth 33% (`intra_op_num_threads=2`) with no
  accuracy cost, but the gate is a ratio and the baseline speeds up equally.
- Resolution is not a lever. Re-exported at 416 the model passes the gate at
  exactly 1.00× and detects nothing — precision 0.000 over 3692 images.
- The gate compares a 640×640 candidate against a 416×416 baseline, which is
  2.37× the compute before any optimization. That comparison, not the model,
  is what needs an architecture decision.

Verdict: PARTIALLY OPTIMIZED, promotion REJECT.

## Testing

388 platform tests (`ai/tests/test_training_*`, `test_evaluation_*`,
`test_export_*`, `test_train_cli*.py`, `test_training_workspace.py`,
`test_official_yolox.py`, `test_video_data.py`, `test_error_analysis.py`,
`test_qualitative.py`, `test_coco_baseline.py`, `test_model_v1_notebook.py`)
cover config validation (including warmup bounds), the experiment record
(including environment/duration/checkpoint-checksum provenance),
registry-only data access (both formats), smoke training + resume + early
stopping + reproducibility (including warmup-scheduler resume), hand-
computed metrics, report artifacts, export parity + rejection, the full
compatibility contract plus its `guardian-validation.json` artifact,
PROMOTE/REJECT verdicts, the promotion gates, the official YOLOX family's
build/loss/decode/export/checkpoint-loading, lazy video batching
(including multi-worker determinism and memory bounds), error analysis,
qualitative export, COCO-baseline decode math, and the CLI end to end on
synthetic datasets. Coverage over the training/evaluation/export modules:
95 %.

## Early stopping (revised after Sprint 20)

The default metric is **`map50_95`**, not `f1`.

Sprint 20's run reached `val_f1 = 1.0` at epoch 3 and could go no higher, so
"no improvement" was true from that point on by arithmetic rather than by
the model having stopped learning. The patience counter measured the
metric's ceiling. Training loss was still falling monotonically — 15.29 to
1.88, still decreasing on the final epoch — when the run was cut at epoch
13 of a planned 30. Whether more epochs would have helped is unknown and
unknowable from that run, which is the point. mAP@50-95 averages over ten
IoU thresholds and does not saturate at this difficulty.

Two guards were added around it:

- **`min_delta`** (default 0.0, historical behaviour) — how much better
  counts as better. Above zero it stops noise-level wobble from resetting
  patience forever, which is the failure opposite to saturation and just as
  invisible in a metric plot.
- **Saturation detection.** When patience expires on a bounded metric that
  is sitting at its bound, the run logs a warning saying so and records
  `stop_reason: "metric_saturated"` rather than `"no_improvement"` in
  `metrics.json`. Those are different facts and the file used to conflate
  them; separating them took a provenance review to do by hand once, and
  should never need doing again.

A config that names its metric explicitly is unaffected by the default
change.
