# Detector Integration (Sprint 19.1)

- **Date:** 2026-07-07
- **Reflects:** ADR-0001 (monorepo boundaries), ADR-0003 (detector licensing),
  ADR-0008/0009 (inference runtime, model management)
- **Scope:** architecture correction — not an accuracy sprint

## Why Guardian does not own detector implementations

Guardian AI is an Edge Safety Platform. Its intelligence lives in the
dataset platform, evidence pipeline, tracking, risk reasoning,
explainability, notification and model-management layers — the parts of
the system that encode *product* judgment about child safety. Object
detection is a commodity, extensively researched capability that
detector vendors (Megvii, the RT-DETR/DETR authors, Ultralytics, etc.)
build, benchmark and maintain full-time. Re-implementing one from
scratch means re-owning:

- the target-assignment algorithm (SimOTA-class dynamic matching),
- numerically stable losses tuned against months of ablation,
- initialization schemes that matter more than they look (see below),
- every future architecture refinement the original authors ship.

None of that is Guardian-specific. Maintaining it is pure cost with no
product differentiation — exactly the kind of complexity ENGINEERING.md's
engineering principles warn against ("avoid unnecessary complexity",
"could it be simpler?").

## What Sprint 19 got right and wrong

Sprint 19 built the first *real* training run end to end — registry-only
data access, multi-object targets, error analysis, qualitative export,
validated ONNX export, a COCO-pretrained comparison, gated candidate
promotion. All of that is architecture, and all of it is unchanged by
this sprint.

What Sprint 19 got wrong was reimplementing YOLOX-Tiny from scratch
(`training/yolox_tiny.py`, now deleted). It was not a small bug — an
audit (prompted by the trained candidate performing dramatically worse
than the official COCO checkpoint on the same images) traced the failure
to the detector implementation itself:

1. **Data, labels and letterbox math were verified correct** — a real
   training image's ground-truth box, checked by hand, matched exactly
   what the model was trained against.
2. **Target assignment was verified correct** — ten sensible anchors,
   clustered tightly around the real object, were selected for a real
   box.
3. **The decisive test:** overfitting a *single real training example*
   for 200 gradient steps. Classification converged almost perfectly
   (≈0.9999 confidence at the assigned anchors). Objectness at those
   *same* anchors stayed at 0.02–0.04 — lower than several unrelated
   background anchors (up to 0.16). Decoding the result produced 400
   detections scattered across the image, none near the real object.

The custom head initialized every bias at zero, so objectness started
at `sigmoid(0) = 0.5` *everywhere* — the optimizer had to push ~8,390
background anchors down and ~10 real anchors up, from the same flat
starting point, sharing a branch with box regression under a 5× loss
weight. The official implementation calls
`head.initialize_biases(prior_prob=1e-2)`, which sets the objectness and
classification biases so every anchor starts confidently predicting
*background* (`sigmoid(bias) ≈ 0.01`) — training only has to raise
confidence at the few real positives, a dramatically easier optimization
landscape. Re-running the **exact same single-example overfit test**
against the official implementation: 5 detections after 200 steps, the
top one at `(0.941, 0.752, 0.060, 0.294)` against a ground truth of
`(0.942, 0.738, 0.059, 0.275)` — a correct, tightly-localized match.

This is precisely the kind of hard-won, non-obvious tuning that belongs
to a detector's own maintainers, not to a platform team building it
"technically correctly" once. That is the case for this sprint, in one
sentence: **the custom implementation was not fixed because the fix was
"stop implementing detectors."**

## The detector lifecycle

```
 configuration (YAML)              DetectorFamily (port)
 ─────────────────────             ───────────────────────
 model.family: yolox-tiny   ──▶    build(num_classes, input_size,
 model.pretrained: true            pretrained, checkpoint) -> nn.Module
 model.checkpoint: null     ──▶    loss(outputs, targets) -> Tensor
                             ──▶    decode(outputs) -> list[Prediction]
                             ──▶    input_name() / output_name()
                                          │
                                          ▼
                        guardian_ai/training/detectors/<vendor>/
                        (variants, checkpoints, target-format adapter,
                         calling-convention wrapper — ALL vendor-specific
                         code lives here, nothing leaks outside)
                                          │
                                          ▼
                     Trainer (engine.py) — unchanged: seeded epochs,
                     checkpoints, resume, early stopping, evaluation,
                     error analysis, qualitative export, ONNX export +
                     validation, benchmark, compare, gated promotion
```

A detector family is infrastructure behind a port. Everything above the
port — the workflow in `train/__init__.py`'s CLI, `engine.py`'s training
loop, `evaluation/`, `export/`, `promote.py` — has never needed to change
across three different detector implementations (tiny-ssd, the deleted
custom YOLOX-Tiny, official YOLOX) and is not expected to change for the
next one.

## `guardian_ai/training/detectors/yolox/` — how one vendor is wrapped

The real `megvii-basedetection/yolox` package (Apache-2.0) is installed
as an ordinary dependency — pinned to a specific commit
(`[tool.uv.sources]` in the workspace root `pyproject.toml`), never
forked, never copied, never edited. This package only *adapts*:

| File | Job |
|---|---|
| `variants.py` | depth/width/depthwise per size (nano/tiny/s/m/l) — copied from the five numbers in upstream's own `exps/default/*.py`, not imported (those files pull in COCO-dataset training scaffolding we don't want) |
| `checkpoints.py` | automatic download of the documented COCO checkpoint (`torch.hub`, upstream's own release URLs), trust-on-first-use SHA-256 pinning, custom checkpoint loading, backbone-only transfer when `num_classes != 80` |
| `targets.py` | Guardian's per-image `(boxes, labels)` list → YOLOX's own padded `(batch, max_boxes, 5)` pixel-space tensor |
| `wrapper.py` | bridges calling conventions (below) |
| `family.py` | `OfficialYoloxTrainer` — the actual `DetectorFamily` |

### Bridging the calling convention

Guardian's engine always calls `outputs = model(images)`, then separately
`loss = family.loss(outputs, targets)`. Upstream YOLOX computes the loss
*inside* one combined `model(images, targets)` call — it needs internal
grid/stride tensors that never leave that call. `OfficialYoloxWrapper`
resolves the mismatch without touching either side: in train mode,
`forward()` runs one throwaway `no_grad` pass (so `engine.py` gets a
same-shaped tensor to discard) and caches the input image batch;
`loss()` re-invokes the real upstream model *with* targets against the
cached input, and that second, gradient-carrying pass is what
`.backward()` walks. One extra forward pass per training step is the
accepted, documented cost of reusing upstream's unmodified training path
instead of reimplementing it — on the real spec run (Colab T4, 30
epochs), this is a minor fraction of total training time next to the
loss computation itself.

## Evaluation, export, promotion — genuinely unchanged

`OfficialYoloxTrainer.decode()` produces the same
`list[Prediction]` shape every family produces; `evaluate_detections`,
`error_analysis.py`, `qualitative.py`, `onnx_export.py`,
`compat.py`, `compare.py` and `promote.py` never import anything
detector-specific and did not change for this sprint. The exported ONNX
graph is still validated the same way: structural check, torch/ONNX
Runtime parity (≤ 1e-4), batch=1, named tensors, dynamic-shape support,
Guardian compatibility contract — a broken export is rejected identically
regardless of which family produced it.

## How to add another detector (RT-DETR, YOLOv8, YOLO11, YOLO12)

1. Confirm the license (ADR-0003) — RT-DETR is Apache-2.0 and already
   reserved for this; YOLOv8/YOLO11/YOLOv12 stay AGPL-blocked until a
   compliant path exists. **Step 1 is a gate, not a formality**: Sprint 21
   ran it for YOLOv12 and the sprint ended there. See below.
2. Add the real package as a workspace dependency, pinned to a commit or
   release (never a fork).
3. Create `guardian_ai/training/detectors/<vendor>/` with the same five
   responsibilities as `yolox/`: variant table, checkpoint handling, a
   target-format adapter, a calling-convention wrapper if the upstream
   API doesn't already match `build → outputs → loss/decode`, and one
   `DetectorFamily` implementation.
4. Register it in `families.py` (one factory closure per variant, same
   pattern as the five `yolox-*` entries) — no changes anywhere else.
5. Prove convergence the same way this sprint did: overfit a single real
   example and confirm the decoded prediction lands on the real box
   before trusting a full training run's numbers.

### RT-DETR — integrated as a candidate (Sprint 22)

RT-DETR is the first family added by following this list end to end, and it
is worth recording which steps did real work.

**Step 1 (licence) chose the implementation, not just approved it.** Three
permissive RT-DETRs exist — the paper authors' `lyuwenyu/RT-DETR`, Paddle's
original, and `transformers` — all Apache-2.0, plus an AGPL one inside
Ultralytics that must never be used. `transformers` was selected because
`lyuwenyu/RT-DETR` ships no `setup.py` and no `pyproject.toml`: it is
research code, not a package, so depending on it would mean vendoring a copy
— which is what step 2's "never a fork" exists to prevent.

**Step 3 needed no new pattern.** RT-DETR computes its loss inside its own
forward pass, exactly like YOLOX, so `RtDetrWrapper` bridges it the same way
`OfficialYoloxWrapper` does. The `DetectorFamily` protocol was not changed.

**Step 5 earned its place.** The adapter looked broken at 120 overfit steps
(box at `[0.83, 0.87]` against a target of `[0.5, 0.5]`) and converged
cleanly by step 300 (`[0.497, 0.499, 0.200, 0.399]`, score 0.982). DETR-style
models converge slowly from random init; stopping early would have produced
a confident wrong answer in either direction.

Two architectural differences are disclosed rather than hidden: RT-DETR runs
**no NMS** (one-to-one Hungarian matching suppresses duplicates in the loss),
and its boxes are **already normalized** (copying YOLOX's divide-by-input_size
would shrink every box to nothing). Both are pinned by tests.

Full audit: `architecture/rtdetr-evaluation.md`.

### YOLOv12 — audited and blocked (Sprint 21)

Sprint 21 set out to benchmark YOLOv12 against Guardian v1 and stopped at
step 1. The full audit is `architecture/yolov12-evaluation.md`; the report
is `reports/model-v1/yolov12-benchmark-report.md`. Two facts matter for
anyone reading this list later.

**The licence is AGPL-3.0**, like YOLOv8 and YOLO11 — but with one fewer way
out. The official implementation (`sunsmarterjie/yolov12`) is a fork of
Ultralytics whose `pyproject.toml` declares `name = "ultralytics"`. It is
not a model with an AGPL dependency that could be swapped for a permissive
runtime; the model *is* the framework, so there is no weights-only path.

**Step 2 excludes it independently.** "Pinned to a commit or release (never
a fork)" — YOLOv12's official implementation *is* a fork of another
project's package, published under that package's name. Even with the
licence resolved, integrating it as written would violate the rule that
exists so Guardian never depends on someone's patched copy of someone
else's detector.

`get_family("yolov12")` now refuses with the reason rather than an unknown-
family error, so this finding is where the next person will meet it. Nothing
here says YOLOv12 is technically worse than YOLOX — it was never measured,
and that stays true until the licence question has an answer.

## Consequences

- Guardian never again ships a from-scratch detector loss/assignment
  implementation without first checking whether the upstream, actively
  maintained version can be wrapped instead.
- The one real cost is the double forward pass in `loss()` — acceptable
  on GPU, and isolated entirely inside `detectors/yolox/wrapper.py`
  should a cheaper bridge become worth building later.
- `yolox`'s own dependencies (`pycocotools`, `scikit-image`,
  `tensorboard`, `onnx-simplifier`, …) are now part of the `ai/`
  environment even though only `yolox.models` is ever imported — dead
  weight we accept rather than fork the package to trim it.
- Old Sprint 19 experiment records stay readable (their `model.family`
  string now resolves to the official implementation); their saved
  *checkpoints* cannot resume under the new architecture, since the two
  implementations' parameter shapes/names differ. This is an inherent
  property of swapping detector implementations, not a migration gap —
  see requirement #10 in the sprint spec ("no migration of
  experiment.json should be required": confirmed — old records load and
  their evaluation/report artifacts still work).

## Alternatives considered

- **Fix the custom implementation's initialization/assignment instead of
  removing it:** rejected — even fixed, it would still be a detector
  implementation Guardian owns and must keep re-validating against every
  future upstream improvement. The audit's finding is a symptom; the
  sprint's actual goal is not carrying that maintenance burden at all.
- **Vendor (copy) the upstream source into the repo:** rejected —
  indistinguishable from a fork in practice; pins us to one commit
  forever and blocks trivially picking up upstream fixes.
- **Call upstream's own `Trainer`/`Exp` training loop directly instead of
  wrapping `DetectorFamily`:** rejected — would require adopting YOLOX's
  COCO-dataset assumptions (`COCODataset`, JSON annotations, its own
  augmentation pipeline) in place of the registry-only Guardian dataset
  platform (ADR-0010), the opposite of "Training Platform remains
  unchanged."
