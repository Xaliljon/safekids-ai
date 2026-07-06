# Guardian Model v1 — Training Report (Sprint 19)

**Recommendation: KEEP COCO. Do not promote this run.**

This report covers the **local validation run** executed in this
session — not the full spec run. Read [Scope](#scope-what-actually-ran-here)
before the numbers below; they describe a deliberately small run whose
job was to prove the platform is real and correct, not to produce a
production model.

## Scope: what actually ran here

Sprint 19 mandates training on the complete `guardian-fall-detection-v1`
dataset (357 videos, 24,901 boxes; **19,940** training images after
frame extraction — clip counts and image counts are different things,
see [Known weaknesses](#known-weaknesses--corrections-made-this-sprint))
for 30 epochs on a Colab T4 GPU. That is the run
`ai/training/configs/model-v1.yaml` and
`ai/training/notebooks/model-v1-training.ipynb` are built for, and
neither this repository's dev machine nor this session has a GPU or the
hours of wall-clock a full run needs.

What ran here instead, for real, on the real dataset, through the real
registry (no synthetic data anywhere in this report):

| | Local validation run | Full spec (Colab) |
|---|---|---|
| Images | 256 (first 256 of each split, `dataset.max_samples`) | 19,940 train / 1,269 val / 3,692 test |
| Epochs | 6 | 30 |
| Device | CPU | T4 GPU |
| Mixed precision | off | on |
| Purpose | prove the pipeline | produce a candidate |

Every number below is a real measurement from that 256-image/6-epoch
run — not fabricated, not a placeholder. It is expected to be weak, and
it is.

## What this proves

- The registry-only data path resolves `guardian-fall-detection-v1@1.0.0`
  through `VideoDatasetRegistry.get()` (checksum-verified against
  50,885 real files) and trains on real letterboxed 640×640 frames with
  real multi-object YOLO-format labels.
- YOLOX-Tiny (backbone → PAFPN-lite neck → decoupled head, from-scratch
  PyTorch, Apache-2.0 in spirit — see `ai/guardian_ai/training/yolox_tiny.py`)
  builds, trains (`loss_curve.png`: 6.16 → 4.60, monotonically decreasing
  loss), backpropagates, checkpoints, resumes, evaluates, and exports to
  a validated ONNX artifact (structural check + torch/onnxruntime parity
  ≤ 1e-4) — the entire Sprint 17/18/19 pipeline, end to end, on real data.
- Error analysis, qualitative export, benchmarking, and the
  COCO-pretrained comparison all ran against real predictions from a
  real checkpoint — see below.

## Metrics (test split, 256 images)

| Metric | Value |
|---|---|
| Precision | 0.0001 |
| Recall | 0.0156 |
| F1 | 0.0001 |
| mAP@50 | 0.0000 |
| mAP@50-95 | 0.0000 |
| False positives | 71,885 |
| False negatives | 252 |

Full metrics: [`evaluation.json`](evaluation.json). Charts:
[`charts/loss_curve.png`](charts/loss_curve.png),
[`charts/confusion_matrix.png`](charts/confusion_matrix.png),
[`charts/pr_curve.png`](charts/pr_curve.png).

These numbers are exactly what 256 images and 6 epochs on a randomly
initialized detector should produce: the loss curve shows real learning
happening, but nowhere near enough of it to suppress the ~8,400
per-image anchor candidates down to a handful of confident detections.
`worst_confidence_false_positives` in
[`error-analysis.json`](error-analysis.json) shows the model is
already *somewhat* selective — its most confident false positive is at
0.81 confidence with only 0.005 IoU against the nearest real box — but
6 epochs is not enough to teach objectness suppression at scale.

## Error analysis highlights

Full detail: [`error-analysis.json`](error-analysis.json).

- **Worst false-positive image**: 292 spurious boxes on one frame
  (`le2i-coffee-room-01-video-36-000100.png`) — a single real person,
  swarmed.
- **Worst localization among true positives**: IoU 0.52 (barely over
  the 0.5 threshold) — even "correct" detections are loosely boxed.
- **Most confused classes**: none recorded — the model essentially
  never reaches a *correctly localized* detection to misclassify; its
  failure mode at this stage is pure over-prediction, not confusion
  between `person`/`child`/`adult`/`unknown`.

## Qualitative samples

20 random validation predictions rendered with ground truth (green) and
predictions (cyan, with confidence) at
[`ai/training/runs/.../reports/qualitative/`](../../ai/training/runs)
(6 copied into [`qualitative-samples/`](qualitative-samples) here). They
visually confirm the metrics: the green ground-truth box is correctly
placed on the real person in every sample checked, while cyan prediction
boxes blanket the frame — the model has not yet learned to be quiet.

## ONNX export & benchmark

- Export: validated (structural check + torch/onnxruntime parity,
  max |Δ| ≤ 1e-4) — `model.onnx`, SHA-256
  `6f1961991bc89f8aefde0692f0988137a3e5ee493041afe14701960a2fd5bf3f`.
- Benchmark (ONNX Runtime, CPU, 20 runs): **21.4 ms** mean latency,
  22.1 ms p95, 17.8 MB on disk, ~170 MB peak measured memory.

## COCO-pretrained comparison — the mandated recommendation

Full detail: [`coco-comparison.json`](coco-comparison.json). Baseline is
the **real, official Apache-2.0 YOLOX-Tiny COCO checkpoint**
(`yolox-tiny` v`0.1.1-rc0`, pinned SHA-256 per ADR-0003), fetched through
the existing, already-reviewed `edge/guardian_edge/tools/install_yolox.py`
installer and evaluated with our own harness, filtered to the `person`
class, on the identical 256 test images:

| | COCO-pretrained (real) | Guardian v1 (this run) |
|---|---|---|
| Precision | 0.4749 | 0.0001 |
| Recall | 0.9609 | 0.0156 |
| False positives | 272 | 71,885 |
| Latency (CPU) | 14.7 ms | 21.7 ms |

**Verdict: REJECT.** A general-purpose pretrained detector — never shown
one frame of this dataset — already finds real people far better than
our 6-epoch, 256-image candidate. This is the expected, honest outcome
at this scale, not a flaw in the platform: it is exactly why the full
spec calls for 19,940 images and 30 epochs on a GPU, not 256 images and
6 epochs on a laptop CPU.

## Known weaknesses & corrections made this sprint

- **Clip count ≠ image count.** `guardian-fall-detection-v1`'s manifest
  reports splits in *videos* (282/40/35), but the training export
  extracts one image per *annotated frame* — the real counts are
  19,940 / 1,269 / 3,692 images. The original local run attempt tried
  to eagerly load the full split into memory (a pattern copied from
  Sprint 17's tiny dummy-dataset module) and was OOM-killed. Fixed by
  making `VideoRegistryDataModule.batches()` lazy (`LazyBatches`,
  decodes one batch at a time, O(batch_size) peak memory) — see
  `ai/guardian_ai/training/video_data.py`. This is a platform fix, not
  a training-run artifact.
- **Target assignment is simplified SimOTA**, not the published
  paper's optimal-transport formulation — a center-region + nearest-k
  heuristic (documented in `yolox_tiny.py`'s module docstring). Likely
  to under-perform the real SimOTA on convergence speed; worth
  revisiting if the full Colab run's precision plateaus below
  expectations.
- **No SPP block, no "Focus" stem** — a deliberately smaller backbone
  than the published YOLOX-tiny. Revisit if recall on small/occluded
  people is insufficient after full training.
- **This run's weak metrics are a sample-size artifact, not necessarily
  a ceiling.** No conclusion about the architecture's real ceiling can
  be drawn from 256 images/6 epochs; only the full run can answer that.

## Future improvements

1. **Run the full spec on Colab** — `ai/training/notebooks/model-v1-training.ipynb`,
   Run All, T4 GPU, 19,940 images, 30 epochs, mixed precision. Re-run
   `error-analysis`, `qualitative`, `benchmark`, and `coco-compare`
   against that checkpoint before any promotion discussion.
2. If precision still trails COCO after full training, consider
   initializing from COCO weights (fine-tuning) rather than training
   from scratch — the platform's `DetectorFamily.build()` seam supports
   this without any engine changes.
3. Revisit the simplified target assignment (real SimOTA) and consider
   adding the SPP block if small-object recall is the bottleneck.
4. Background (no-person) frames are currently skipped entirely
   (`RegistryDataModule`/`VideoRegistryDataModule` both drop
   zero-annotation samples) — training on hard negatives may reduce the
   false-positive rate directly.

## Status

`status: candidate`, `not_production: true` — recorded in
[`experiment.json`](experiment.json). **Not installed into any model
zoo.** Promotion remains a separate, later, human decision, gated on a
full Colab run producing metrics that beat the COCO baseline above.
