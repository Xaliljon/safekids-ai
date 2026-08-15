# RT-DETR Evaluation — Sprint 22

- **Date:** 2026-08-15
- **Status:** integrated as a **candidate**; nothing promoted, nothing deployed
- **Governed by:** ADR-0003 (detector licensing), ADR-0010 (dataset platform),
  ADR-0020 (what the latency gate compares)

## Why RT-DETR was selected

Sprint 21 audited YOLOv12 and stopped: its official implementation is a fork
of Ultralytics under AGPL-3.0, and the model is the framework, so there is no
weights-only path. RT-DETR was already reserved in the family table as the
Apache-2.0 alternative, and it answers the same underlying question — is
there a better detector for Guardian than YOLOX-tiny — without a licence
purchase.

## Licence audit (Sprint 22 §2, run before any download)

| Implementation | Licence | Verdict |
|---|---|---|
| `lyuwenyu/RT-DETR` — the paper authors' code | **Apache-2.0** (fetched `LICENSE`) | compliant, but see below |
| `PaddlePaddle/PaddleDetection` — the original | **Apache-2.0** (fetched, `develop`) | compliant |
| `huggingface/transformers` — `RTDetrForObjectDetection` | **Apache-2.0** (fetched; PyPI metadata agrees) | **selected** |
| `ultralytics` RTDETR | **AGPL-3.0** | **must never be used** |
| Weights `PekingU/rtdetr_r18vd`, `…_r50vd` | **apache-2.0** (HF model metadata) | compliant |

**Selected: `transformers`.** Not because the other permissive options are
non-compliant — they are — but because of a packaging fact:
`lyuwenyu/RT-DETR` ships **no `setup.py` and no `pyproject.toml`** (both
return 404). It is research code, not a package, so depending on it would
mean vendoring a copy into Guardian. `architecture/detector-integration.md`
step 2 requires "the real package as a workspace dependency, pinned to a
commit or release (never a fork)", and a vendored copy is the thing that
rule exists to prevent.

`transformers` is therefore the only *packaged* permissive RT-DETR. It is a
large dependency for one detector, and that cost is accepted deliberately
rather than overlooked.

**The trap worth naming:** RT-DETR also ships inside Ultralytics. Reaching
for `from ultralytics import RTDETR` would reintroduce exactly the blocker
Sprint 21 stopped on, under a name that looks approved. A test asserts the
AGPL families stay blocked so this cannot drift.

## Integration

```
Guardian training engine
        ↓  DetectorFamily protocol (unchanged)
RtDetrTrainer  ──  RtDetrWrapper  ──  transformers.RTDetrForObjectDetection
```

`guardian_ai/training/detectors/rtdetr/` mirrors the five responsibilities
of `detectors/yolox/`: variant table, target adapter, calling-convention
wrapper, family implementation, package init.

**The protocol was not changed** (§3). RT-DETR computes its loss inside its
own forward pass, exactly like YOLOX, and `RtDetrWrapper` bridges it the same
way `OfficialYoloxWrapper` does: cache the images in `forward`, run the real
gradient-carrying pass inside `compute_loss`. That costs one extra forward
per training step. Solving it identically twice is deliberate — a second
solution would be a second thing to understand, and the protocol is not
deficient just because two upstreams share a convention Guardian does not.

**Output contract is identical** to every other family: one
`(batch, queries, 5 + num_classes)` tensor of
`[cx, cy, w, h, objectness, class_scores…]`. RT-DETR is DETR-style and has
no objectness head, so that column is a constant 1.0 and the whole score
lives in the class probabilities — `decode` multiplies them exactly as the
YOLOX family does and needs no special case downstream.

**Two architectural differences, disclosed rather than smoothed over (§14):**

1. **No NMS.** RT-DETR is trained with one-to-one Hungarian matching, so
   duplicate suppression is the loss's job. Running NMS anyway would change
   the YOLOX comparison in one direction or the other for no principled
   reason.
2. **Boxes are already normalized.** RT-DETR predicts in `[0,1]`; the YOLOX
   family divides by `input_size` because YOLOX decodes to pixels. Copying
   that division here would shrink every box to nothing, and a test pins it.

## Configuration

```yaml
model:
  family: rtdetr-r18vd     # or r34vd / r50vd / r101vd
  input_size: 640
```

Variants resolve through the same table pattern as YOLOX. An unknown variant
raises `TrainingConfigurationError` naming the real ones. The bare `rt-detr`
name — which was never a family — now fails with a message pointing at the
four real ones instead of a stale "scheduled after YOLOX-tiny".

`ai/training/configs/training.yaml` still names `rt-detr` and was **left
untouched**: changing a production training config is outside an evaluation
sprint (§24).

## Convergence proof

`detector-integration.md` step 5 requires overfitting a single real example
before trusting an adapter, because Sprint 19 shipped a detector that trained
without error and could not converge objectness on one. RT-DETR r18vd, random
init, one 320×320 image with one box at `[0.5, 0.5, 0.2, 0.4]`, AdamW
`lr=1e-4`:

| step | loss | decoded best box | score |
|---:|---:|---|---:|
| 0 | 610.674 | `[0.975 0.975 0.100 0.100]` | 0.628 |
| 100 | 19.765 | `[0.509 0.194 0.198 0.460]` | 0.057 |
| 200 | 14.160 | `[0.510 0.476 0.207 0.450]` | 0.430 |
| **300** | **12.204** | **`[0.497 0.499 0.200 0.399]`** | **0.982** |
| 800 | 10.446 | `[0.500 0.502 0.200 0.403]` | 0.986 |

**The adapter converges.** Worth recording honestly: a first run of 120 steps
stopped with the box at `[0.829 0.865 …]` and looked like a failure. It was
under-training, not a defect — DETR-style models are slow to converge from
random init, and stopping at 120 steps would have produced a wrong
conclusion in either direction.

## Methodology

- **Evaluation:** Guardian's existing evaluator. No separate implementation
  was written for RT-DETR (§5).
- **Benchmark:** Sprint 20.2's methodology unchanged — `runs=150`,
  `warmup=20`, CPU execution provider, same host, same input resolution.
- **Export:** Guardian's existing `export_onnx`, including its structural
  check and its PyTorch↔ONNX parity gate. The tolerance was not touched.

## Limitations

- **The Guardian dataset is not present on this machine.**
  `ai/training/datasets/` is empty and there is no CUDA GPU (MPS only), so
  training, accuracy evaluation, error analysis and the promotion gate could
  not run here. They need the Colab workflow of Sprint 20.1.
- **Every latency figure is development hardware** (Apple M4 Max),
  `is_edge_target: false`. ADR-0020 §3 stands: the product's budget is an
  absolute millisecond figure on Jetson or N100, and nothing has measured it.
- **Benchmarked weights are randomly initialised.** Latency depends on
  architecture and tensor shapes rather than weight values, so the numbers
  are valid for cost; they say nothing about accuracy.
- Licence texts were read on 2026-08-15. This is an engineering reading of
  published licence files, not legal advice.

## Result

See `reports/model-v1/rtdetr-benchmark-report.md`. RT-DETR is **candidate
only**: integrated, licence-clear, converging, exportable — and unmeasured
on accuracy until it trains on the Guardian dataset.
