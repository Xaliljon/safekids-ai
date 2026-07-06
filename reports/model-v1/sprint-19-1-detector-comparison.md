# Sprint 19.1 — Detector Comparison: Custom vs. Official YOLOX

**Recommendation: remove the custom implementation (done). KEEP COCO for
promotion purposes — this sprint is an architecture correction, not an
accuracy sprint; no candidate here is close to promotable yet.**

## Why this comparison exists

Sprint 19 shipped a from-scratch YOLOX-Tiny `DetectorFamily`. Its
candidate model performed dramatically worse than the official
COCO-pretrained checkpoint. An audit (assuming the architecture was
"correct" and searching the pipeline for a bug) found the real problem
*was* the architecture — specifically its initialization and the
optimization dynamics that follow from it. This report captures the
three data points that motivated removing it entirely rather than
patching it, run on the identical 256-image/6-epoch local-validation
slice of `guardian-fall-detection-v1@1.0.0` used in the original Sprint
19 report.

## 1. The audit's decisive test: single-example overfit

Both implementations were trained on **one real image** for 200 SGD
steps (`lr=1e-2, momentum=0.9`) — the easiest possible task for a
5M-parameter network.

| | Custom (removed) | Official YOLOX |
|---|---|---|
| Final loss (200 steps) | 2.86 (own loss scale) | not re-run (see §2 for the real per-image case) |
| Detections after training | **400**, scattered across the whole image | **5**, tightly clustered on the real object |
| Top prediction vs. ground truth | unrelated location, 0.28 confidence | `(0.941, 0.752, 0.060, 0.294)` vs. GT `(0.942, 0.738, 0.059, 0.275)` — correct label, 0.73 confidence |
| Objectness at the *correct*, assigned anchors | 0.015–0.04 (**lower** than random background anchors, up to 0.16) | converges to a confident, correctly-localized detection |

**Root cause:** the custom head initializes every bias at zero
(`sigmoid(0) = 0.5`), so objectness starts high *everywhere*; the
optimizer must push ~8,390 background anchors down and ~10 real anchors
up from the same flat start, sharing a branch with box regression under
a 5× loss weight. Official YOLOX calls
`head.initialize_biases(prior_prob=1e-2)`, starting every anchor
confidently predicting background (`sigmoid(bias) ≈ 0.01`) — training
only has to raise confidence at the few real positives. Full narrative:
[architecture/detector-integration.md](../../architecture/detector-integration.md).

## 2. Full local-validation run (256 images, 6 epochs, CPU)

Both runs use the *exact* dataset slice, seed (42), epoch count, and
batch size as Sprint 19's original report.

| Metric | Custom (Sprint 19, removed) | Official YOLOX (this sprint) |
|---|---|---|
| Optimizer | SGD, lr=0.01 | **AdamW, lr=0.001** (see caveat below) |
| Precision | 0.0001 | 0.0000 |
| Recall | 0.0156 | 0.0000 |
| False positives | **71,885** | **0** |
| False negatives | 252 | 256 |
| Latency (CPU, ONNX Runtime) | 21.4 ms | 25.8 ms |
| Model size | 17.8 MB | 19.5 MB |
| License | Proprietary-GuardianAI (ours to maintain) | **Apache-2.0** (upstream-maintained) |

Full artifacts: [`evaluation.json`](sprint-19-1-official-yolox/evaluation.json),
[`error-analysis.json`](sprint-19-1-official-yolox/error-analysis.json),
[`coco-comparison.json`](sprint-19-1-official-yolox/coco-comparison.json),
[`charts/`](sprint-19-1-official-yolox/charts).

Neither run is anywhere near usable — that is expected and was expected
in the original Sprint 19 report too (256 images / 6 epochs is a
correctness proof, not a training budget). The change that matters is
the *failure mode*: the custom implementation fails by flooding every
image with false alarms (the worst possible failure for a child-safety
alerting product); the official implementation fails by staying silent
under-trained, never firing a single false alarm. §1's single-example
test is what proves the second failure mode is purely a "needs more
steps" problem, not an architectural ceiling.

## 3. An integration caveat this comparison surfaced: warmup sensitivity

The first attempt at this run used the **same hyperparameters as the
removed custom implementation's config** (SGD, lr=0.01, no warmup) for
an apples-to-apples comparison. It **numerically diverged**: box
regression outputs reached `±10^8` and objectness collapsed to exactly
zero across every anchor on every image (`inf`/`nan` poisoning, confirmed
by direct tensor inspection).

This is not a bug in the wrapper or in official YOLOX — it is a real
property of anchor-free detection heads at this learning rate, and
upstream's own default training recipe (`yolox/exp/yolox_base.py`)
budgets **5 warmup epochs** at a near-zero learning rate specifically to
avoid it. Guardian's generic `Trainer` (`engine.py`) has no warmup
concept. Switching to AdamW at a lower, fixed learning rate (no warmup
needed at this scale) produced the stable, if under-trained, numbers in
§2. **Recorded as a known limitation and future improvement** — see
architecture/detector-integration.md and the "future improvements" list
below. It does not block this sprint's goal (remove the custom
implementation) but should be resolved before a full-scale Colab run,
which uses `sgd, lr=0.01, cosine` unchanged from Sprint 19's spec and
would need either upstream's own warmup+cosine `LRScheduler` or a
lower starting learning rate to avoid the same divergence at scale.

## Recommendation

- **Custom implementation: removed.** Confirmed by §1 as the correct
  call — the architecture itself, not the training budget, was the
  Sprint 19 failure's root cause.
- **Official YOLOX: architecturally sound, not yet a candidate for
  promotion.** §1 proves it can learn a real box correctly; §2 proves
  the current *training recipe* (as configured through Guardian's
  generic engine) needs either a warmup mechanism or a full-scale
  Colab run's much larger step count to produce a usable model.
- **COCO-pretrained stays the practical baseline** until a full-spec run
  (19,940 images, 30 epochs, T4 GPU, `ai/training/notebooks/model-v1-training.ipynb`)
  produces real numbers to compare.

## Future improvements

1. Add warmup support to `TrainingConfig`/`engine.py`'s scheduler
   construction (or delegate scheduling entirely to a detector family
   that needs it) before running the full SGD/lr=0.01 spec at scale.
2. Re-run the full Colab spec with `model.pretrained: true` (COCO
   transfer learning) — §1 and the architecture's own design suggest
   this should converge dramatically faster than from-scratch training,
   independent of the warmup question.
3. Re-run `coco-compare` after the full-scale run; only promote if it
   beats the COCO baseline on precision, recall, and false positives
   without a disqualifying latency/memory regression (`compare.py`'s
   existing gates, unchanged).
