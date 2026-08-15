# RT-DETR Benchmark Report — Sprint 22

**Result: integrated, licence-clear, converging — and 13.3× slower than
Guardian v1 at matched input on the same host. Accuracy is unmeasured
because the Guardian dataset is not on this machine.**

## 1. Executive summary

Sprint 21 stopped at YOLOv12's AGPL licence. RT-DETR was the reserved
Apache-2.0 alternative, and Sprint 22 asked whether it offers a better
accuracy/performance trade-off than Guardian v1.

The licence gate passed, cleanly and with a choice to make between three
permissive implementations. The adapter went in behind `DetectorFamily`
without changing the protocol, and it converges on a single overfit example
— the bar Sprint 19 failed and the reason that check exists.

Then the benchmark answered a large part of the question on its own. At the
same 640 input, same runtime, same host, RT-DETR r18vd — the **smallest**
variant — runs at **473.42 ms mean** against Guardian v1's **35.51 ms**.
That is 13.3×, and 4.2× over Sprint 20.2's own 111.462 ms allowance.

Accuracy could not be measured: `ai/training/datasets/` is empty on this
machine and there is no CUDA GPU. So this report cannot say RT-DETR is less
accurate. It says the latency gap is large enough that accuracy would have
to be dramatically better *and* the gap would have to close by more than an
order of magnitude on the actual Edge target for the trade to make sense.

## 2. Licence audit (§2 — run before any download)

| Implementation | Licence | Verdict |
|---|---|---|
| `lyuwenyu/RT-DETR` — paper authors | **Apache-2.0** | compliant, not packaged |
| `PaddlePaddle/PaddleDetection` | **Apache-2.0** | compliant |
| `huggingface/transformers` — `RTDetrForObjectDetection` | **Apache-2.0** | **selected** |
| `ultralytics` RTDETR | **AGPL-3.0** | must never be used |
| Weights `PekingU/rtdetr_r18vd`, `…_r50vd` | **apache-2.0** | compliant |

Every line was fetched, not recalled; the commands are in §17.

**Why `transformers` and not the paper authors' own code:**
`lyuwenyu/RT-DETR` has no `setup.py` and no `pyproject.toml` — both 404. It
is research code, not a package, so depending on it means vendoring a copy,
which is exactly what `detector-integration.md` step 2 ("never a fork")
exists to prevent. `transformers` is the only *packaged* permissive RT-DETR.
It is a heavy dependency for one detector and that cost is accepted
deliberately.

**The trap worth naming:** RT-DETR also ships inside Ultralytics. Reaching
for `from ultralytics import RTDETR` would reintroduce Sprint 21's blocker
under a name that looks approved. A test asserts the AGPL families stay
blocked.

## 3. Source / version

| Field | Value |
|---|---|
| Package | `transformers` 5.15.0 (Apache-2.0) |
| Class | `RTDetrForObjectDetection` |
| Weights source | `PekingU/rtdetr_{r18vd,r34vd,r50vd,r101vd}` |
| Variant benchmarked | `r18vd` (smallest viable, §17) |
| Parameters | **20.07 M** |
| Input resolution | 640 |
| Checkpoint SHA-256 | not recorded — pretrained weights were not downloaded (see §16) |

## 4. Architecture integration

```
Guardian training engine
        ↓  DetectorFamily protocol — unchanged
RtDetrTrainer  ──  RtDetrWrapper  ──  transformers.RTDetrForObjectDetection
```

`guardian_ai/training/detectors/rtdetr/` mirrors `detectors/yolox/`: variant
table, target adapter, calling-convention wrapper, family, package init.

**The protocol was not modified** (§3). RT-DETR computes its loss inside its
own forward pass, exactly like YOLOX, so `RtDetrWrapper` bridges it the same
way `OfficialYoloxWrapper` does — cache images in `forward`, run the
gradient-carrying pass in `compute_loss`. One extra forward per training
step, same accepted cost, same reason.

**Two architectural differences, disclosed rather than smoothed over (§14):**

1. **No NMS.** One-to-one Hungarian matching suppresses duplicates in the
   loss. Running NMS anyway would move the comparison against YOLOX in one
   direction or the other for no principled reason.
2. **Boxes already normalized.** RT-DETR predicts in `[0,1]`; copying the
   YOLOX family's divide-by-`input_size` would shrink every box to nothing.
   A test pins this.

## 5. Training configuration

**Not run.** See §16.

## 6. Dataset

`guardian-fall-detection-v1@1.0.0` was **not modified, not re-split, and not
read** — it is not present on this machine.

## 7. Training result — convergence proof

Full training did not run, but `detector-integration.md` step 5 requires
overfitting a single real example before an adapter is trusted, because
Sprint 19 shipped a detector that trained without error and could not
converge objectness on one.

RT-DETR r18vd, random init, one 320×320 image, one box at
`[0.5, 0.5, 0.2, 0.4]`, AdamW `lr=1e-4`:

| step | loss | decoded best box | score |
|---:|---:|---|---:|
| 0 | 610.674 | `[0.975 0.975 0.100 0.100]` | 0.628 |
| 100 | 19.765 | `[0.509 0.194 0.198 0.460]` | 0.057 |
| 200 | 14.160 | `[0.510 0.476 0.207 0.450]` | 0.430 |
| **300** | **12.204** | **`[0.497 0.499 0.200 0.399]`** | **0.982** |
| 800 | 10.446 | `[0.500 0.502 0.200 0.403]` | 0.986 |

**The adapter converges.** Recorded honestly: a first attempt stopped at 120
steps with the box at `[0.829 0.865 …]` and looked like a defect. It was
under-training — DETR-style models converge slowly from random init — and
stopping there would have produced a confident wrong answer.

## 8. Accuracy metrics

**Not measured.** No dataset, no GPU. See §14 and §16.

## 9. Error analysis

**Not produced** — error analysis requires predictions on a real test split.

## 10. PyTorch benchmark

Development hardware, Apple M4 Max, `warmup=20`, `runs=150`, input `1×3×640×640`.

| | mean | p50 | p95 | FPS |
|---|---:|---:|---:|---:|
| RT-DETR r18vd | **127.68 ms** | 66.77 ms | 314.29 ms | 7.83 |

The mean is nearly double the median. That skew is real and is reported
rather than smoothed: a minority of iterations run several times slower than
typical, which on a 718 MB working set points at memory pressure rather than
at the model's steady-state cost.

## 11. ONNX benchmark

Sprint 20.2 methodology, unchanged — CPU execution provider, `warmup=20`,
`runs=150`, same host, same input shape as Guardian v1's own figure.

| | mean | p95 | memory | size | FPS |
|---|---:|---:|---:|---:|---:|
| RT-DETR r18vd | **473.42 ms** | 1543.21 ms | 718.08 MB | 76.34 MB | 2.11 |
| Guardian v1 @640 | 35.51 ms | 39.82 ms | — | 19.46 MB | 28.2 |

**ONNX is 3.7× slower than PyTorch for the same model**, which is backwards
from the usual result and should not be taken as RT-DETR's floor. The likely
cause is an unfused attention graph in the export; investigating it is real
work that this sprint did not do. Even at the PyTorch median of 66.77 ms —
the most favourable number available anywhere in this report — RT-DETR is
still 1.9× Guardian v1's ONNX mean, and comparing across runtimes is exactly
what ADR-0020 forbids.

The like-for-like comparison is ONNX against ONNX at 640 on one host:
**13.3×**.

## 12. ONNX export

**Passed**, through Guardian's existing `export_onnx` — structural check and
PyTorch↔ONNX numerical parity gate included, tolerance untouched.

| | |
|---|---|
| Export | OK, 1 s |
| Structural check (`onnx.checker`) | pass |
| Parity (PyTorch vs ONNX Runtime) | **pass** |
| SHA-256 | `72e051d80e654e4e…` |
| Size | 76.343 MB |

FP16 was not attempted.

## 13. Edge / development benchmark

**DEVELOPMENT HARDWARE — not production Edge.**

| | |
|---|---|
| CPU | Apple M4 Max (10 performance + 4 efficiency cores) |
| RAM | 36 GB |
| OS | macOS 26.3 arm64 |
| Runtime | onnxruntime 1.27.0, torch 2.12.1 |
| Execution provider | CPUExecutionProvider |
| `is_edge_target` | **false** |

No Jetson and no N100 were available. ADR-0020 §3 stands: the product's
budget is an absolute millisecond figure on the target, and nothing has
measured it. This matters more than usual here — RT-DETR is transformer-heavy
and parallelises differently from a convolutional detector, so a CPU result
may transfer poorly to Jetson's GPU in either direction.

## 14. Guardian v1 comparison

Guardian v1's column is the existing Sprint 20.2 measurement, **not re-run**.
Both models: 640 input, ONNX Runtime, CPU EP, Apple M4 Max.

| Metric | Guardian v1 | RT-DETR r18vd |
|---|---:|---:|
| Precision | 0.9902 | not measured |
| Recall | 0.9832 | not measured |
| F1 | 0.9867 | not measured |
| mAP@50 | 0.2442 | not measured |
| mAP@50-95 | 0.1399 | not measured |
| FP | 36 | not measured |
| FN | 62 | not measured |
| Model size | **19.463 MB** | 76.343 MB |
| Parameters | ~5 M | 20.07 M |
| Mean latency (ONNX) | **35.51 ms** | 473.42 ms |
| P95 latency (ONNX) | **39.82 ms** | 1543.21 ms |
| FPS (ONNX) | **28.2** | 2.11 |
| Memory | 73.58 MB¹ | 718.08 MB |

¹ Guardian v1's memory figure comes from the Colab CPU EP run, not this host,
and is **not a like-for-like comparison**. It is shown for completeness and
should not be used as a ratio.

Two standing caveats on the left column, neither introduced here: its
precision and recall describe four rooms rather than generalization (scene
leakage, candidate provenance review), and its latency is development
hardware.

## 15. Promotion gate result

**Not run.** The gate compares two *evaluated* models and RT-DETR has no
evaluation.

Had it run on latency alone, the outcome is not in doubt: 473.42 ms against a
baseline of 35.51 ms is 13.3×, past the gate's 20 % slack by a wide margin,
and 4.2× over Sprint 20.2's 111.462 ms allowance. ADR-0020's mismatched-shape
refusal does not apply — both were measured at 640.

**RT-DETR is technically ineligible for promotion** on the measured evidence,
and it stays candidate-only regardless (§16 of the brief). Nothing was
deployed and no production configuration changed.

## 16. Limitations

- **The Guardian dataset is not on this machine.** `ai/training/datasets/` is
  empty and there is no CUDA GPU (MPS only). Training, accuracy evaluation,
  error analysis, qualitative images and the promotion gate all need the
  Sprint 20.1 Colab workflow.
- **Benchmarked weights are randomly initialised.** Latency depends on
  architecture and tensor shapes, not weight values, so the timings are valid
  for cost — and say nothing about accuracy.
- **Only `r18vd` was benchmarked.** It is the smallest variant (§17), so the
  others are slower; measuring them to confirm a worse result would spend
  budget to reach the same conclusion.
- **The ONNX result is probably improvable.** 3.7× slower than PyTorch is
  backwards and suggests an unoptimised export graph. Treating 473.42 ms as
  RT-DETR's floor would be unfair to it.
- **CPU is not the Edge target.** A transformer detector may close much of
  this gap on a GPU. It would have to close more than an order of magnitude.
- `ai/training/configs/training.yaml` still names the non-family `rt-detr`
  and was deliberately left alone — changing a production training config is
  outside an evaluation sprint.

## 17. Final recommendation

**Do not replace Guardian v1 with RT-DETR on this evidence. Keep it as a
candidate; do not spend Colab budget training it until the latency question
is settled on real hardware.**

Answering the brief's seven questions directly:

| Question | Answer |
|---|---|
| 1. Legally compatible? | **Yes** — Apache-2.0 end to end, via `transformers` |
| 2. Technically compatible? | **Yes** — integrates behind `DetectorFamily` unchanged, exports to ONNX, passes the parity gate, converges on an overfit example |
| 3. More accurate? | **Unknown** — not measured |
| 4. Faster? | **No** — 13.3× slower at matched input, same runtime, same host |
| 5. More memory efficient? | **No** — 718 MB vs Guardian v1's 73.58 MB (not like-for-like; directionally clear) |
| 6. Passes the promotion gate? | **Not run**; on latency alone it would not |
| 7. Improvement large enough to justify replacing v1? | **No, on current evidence** |

The order of work that follows from this, if RT-DETR is worth pursuing:

1. **Fix the ONNX export path first.** 3.7× slower than PyTorch is a defect
   in the export, not a property of the model, and every later number
   inherits it.
2. **Then benchmark on the actual Edge target.** ADR-0020 §3 already makes
   this a named blocker for the absolute budget clause. RT-DETR is the case
   that makes it urgent rather than tidy.
3. **Only then train.** Spending Colab budget on a model that is currently
   13× outside its latency budget buys an accuracy number nobody can act on.

### Decision matrix

| Criterion | Guardian v1 | RT-DETR r18vd | Winner |
|---|---:|---:|---|
| Precision | 0.9902 | not measured | — |
| Recall | 0.9832 | not measured | — |
| F1 | 0.9867 | not measured | — |
| mAP@50 | 0.2442 | not measured | — |
| mAP@50-95 | 0.1399 | not measured | — |
| FP | 36 | not measured | — |
| FN | 62 | not measured | — |
| Mean latency | 35.51 ms | 473.42 ms | **Guardian v1** |
| P95 latency | 39.82 ms | 1543.21 ms | **Guardian v1** |
| FPS | 28.2 | 2.11 | **Guardian v1** |
| Model size | 19.463 MB | 76.343 MB | **Guardian v1** |
| Memory | 73.58 MB¹ | 718.08 MB | **Guardian v1** |
| Licence | Apache-2.0 | Apache-2.0 | tie |

**Classification: D — no meaningful improvement demonstrated.**

The six categories assume both models were measured on both axes, and this
one was not. D is the nearest honest fit: on every axis actually measured,
Guardian v1 wins, and nothing demonstrates an improvement. It is **not** E
(integration succeeded), **not** B or F (no accuracy claim can be made), and
**not** C (RT-DETR is slower, not faster).

## Reproducing this report

```bash
curl -sSL https://raw.githubusercontent.com/lyuwenyu/RT-DETR/main/LICENSE | head -3
curl -sSL -o /dev/null -w '%{http_code}\n' https://raw.githubusercontent.com/lyuwenyu/RT-DETR/main/pyproject.toml
curl -sSL https://huggingface.co/api/models/PekingU/rtdetr_r18vd | grep -o 'license:[^"]*'
```

```bash
python -m pytest ai/tests/test_rtdetr_family.py -q
```
