# Sprint 20.2 — Inference Optimization & Profiling

**Classification: PARTIALLY OPTIMIZED. Promotion: REJECT.**

> **These are development measurements.** Apple M4 Max, not a Guardian Edge
> target. No Jetson or N100 was available, and nothing below may be read as
> production Edge performance.

Sprint 20's candidate was rejected on one clause — mean latency 169.991 ms
against a 111.462 ms allowance. This sprint set out to find where that
latency lives and remove it. It found something more useful: the clause
cannot be satisfied by optimization, and the reason is visible only once
the benchmark is trustworthy enough to argue with.

## What was established

1. **The gate's number is model inference alone.** `compare.benchmark_onnx`
   times `session.run()` on a fixed-seed random tensor through the CPU
   execution provider. No capture, no preprocessing, no NMS, no tracking is
   inside it. Optimizing any of those stages — sections 8 and 9 of the brief
   — cannot move the number the gate reads.
2. **The existing benchmark cannot be optimized against.** Three identical
   repeats on one idle machine gave 45.4 / 52.3 / 62.1 ms: a ±37% band. A
   20% improvement is invisible inside it.
3. **The cause was thread oversubscription**, and fixing it is worth 33%.
4. **The whole latency gap is input resolution**, and resolution cannot be
   lowered — the model detects nothing below 640.

## 1. Baseline (§2)

| | Candidate | Baseline |
|---|---|---|
| ONNX sha256 | `5fe13479…a7e0` | `427cc366…b0f7` |
| Checkpoint sha256 | `9de513de…e8f0` | — |
| Input | 1×3×640×640 | 1×3×416×416 |
| Output | 1×8400×9 | 1×3549×85 |
| Size | 19.463 MB | 19.283 MB |

Host: Apple M4 Max (10 performance + 4 efficiency cores), 36 GB RAM,
macOS 26.3 arm64, Python 3.14.6, onnxruntime 1.27.0. Providers available:
CoreML, Azure, CPU.

Reproducing the gate's own method (30 runs, 5 warmups, CPU provider,
seed 0) three times over:

| | run 1 | run 2 | run 3 | spread |
|---|---|---|---|---|
| Candidate 640 | 45.4 ms | 52.3 ms | 62.1 ms | ±37% |
| Baseline 416 | 30.4 ms | 30.8 ms | 23.4 ms | — |

The absolute milliseconds differ from Colab's because the CPU differs. The
**ratio** is what the gate tests, and it reproduces the rejection: 2.66×
here, 1.83× on Colab, against a 1.20× allowance.

The ±37% spread is why this sprint added a steady-state profiler
(`guardian_ai.training.profiling`) rather than optimizing blind. The gate's
own benchmark is untouched.

## 2. Cold start vs steady state (§10)

Candidate 640, default threads, 20 warmups discarded, 200 timed runs:

| | ms |
|---|---|
| First call | 42.25 |
| First ten (mean / p95) | 56.45 / 79.94 |
| Steady state (mean / p50 / p95) | 59.76 / 56.96 / 92.06 |
| Steady-state stdev | 18.34 (±30.7%) |

The first call is **faster** than the steady mean. That is the opposite of
a normal cold start, and it was the clue: the variance is not warmup, it is
scheduling.

## 3. Runtime configuration (§5)

ONNX Runtime defaults to one intra-op thread per core. On a 14-core
heterogeneous CPU running a small model, synchronisation cost grows faster
than the parallelism it buys, and threads landing on efficiency cores
straggle.

**Candidate 640, intra-op sweep** (100 runs each):

| intra-op threads | mean ms | p50 ms | p95 ms | spread |
|---|---:|---:|---:|---:|
| default (14) | 53.70 | 51.47 | 85.50 | ±32.6% |
| 1 | 46.47 | 46.04 | 49.64 | ±3.3% |
| **2** | **35.88** | **35.37** | **40.72** | **±6.7%** |
| 4 | 40.43 | 40.99 | 53.52 | ±17.6% |
| 6 | 48.91 | 47.99 | 74.27 | ±30.3% |
| 8 | 55.71 | 54.71 | 81.10 | ±29.0% |
| 10 | 66.28 | 63.08 | 94.37 | ±27.5% |
| 12 | 70.67 | 69.45 | 105.65 | ±29.0% |
| 14 | 89.07 | 79.87 | 135.98 | ±42.3% |

**Baseline 416, same sweep:** default 25.41, 1 → 22.34, **2 → 18.83**,
4 → 20.87, 6 → 21.95, 8 → 30.09 ms.

**Graph optimization level** (candidate, intra-op 2): ENABLE_ALL 36.41,
ENABLE_EXTENDED 36.79, ENABLE_BASIC 36.91, DISABLE_ALL 37.55 ms — all four
inside measurement noise. **inter-op = 1**: 36.87 ms, no effect; the graph
has no parallel branches to schedule.

**CoreML execution provider**: 10.23 ms mean, 12.39 p95 — 3.5× the CPU
provider. Not adopted: CoreML is Apple-only and the Edge targets are Jetson
and N100. It is evidence that the model is not inherently slow and that the
CPU provider is the constraint; the equivalent levers on the real targets
are TensorRT and OpenVINO, and they must be measured there.

## 4. PyTorch vs ONNX Runtime (§4)

Identical tensor, batch 1, two threads on both, 20 warmups, 100 runs:

| runtime | mean ms | p50 ms | p95 ms | FPS |
|---|---:|---:|---:|---:|
| PyTorch | 56.52 | 55.51 | 59.74 | 17.7 |
| ONNX Runtime | 33.45 | 33.34 | 35.34 | 29.9 |

ONNX Runtime is **1.69× faster**. The export path earns its place.

## 5. FP16 (§6)

**Not applied, and it could not have helped.** `onnxconverter-common` is not
in the workspace, and more decisively the CPU execution provider — the one
the gate benchmarks — does not accelerate FP16; it converts back to FP32 to
compute. FP16 is the right lever for TensorRT on Jetson. It has to be
measured there, not inferred from a Mac.

## 6. Input resolution (§7) — the decisive result

The same checkpoint was re-exported at 416 and 512 (torch/onnxruntime
parity validated at 1e-4 on each) and evaluated over the full 3692-image
test split.

| Resolution | Precision | Recall | F1 | mAP@50 | mAP@50-95 | FP | FN | Mean ms | P95 ms | Latency gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 416 | **0.0000** | **0.0000** | 0.0000 | 0.0000 | 0.0000 | 3015 | 3692 | 18.41 | 20.34 | **pass (1.00×)** |
| 512 | 0.0256 | 0.0249 | 0.0252 | 0.0002 | 0.0000 | 3505 | 3600 | 25.10 | 27.04 | fail (1.36×) |
| 640 | 0.9902 | 0.9832 | 0.9867 | 0.2442 | 0.1399 | 36 | 62 | 35.51 | 39.82 | fail (1.92×) |

Baseline 416 measures 18.45 ms, so the gate's allowance on this host is
22.14 ms.

At 416 the model produces 3015 detections and **not one of them is right**.
The weights were trained at 640; the anchor-free head's scale priors travel
with that resolution, and re-exporting the same weights at 416 does not
retrain them.

This is the trap §7 exists to prevent. Latency was measured first, and 416
looked perfect — it passes the gate at exactly 1.00×. A recommendation made
on latency alone would have shipped a model that detects nothing.

**Lowering resolution is not available as an optimization.**

## 7. Harness validation

| | Sprint 20 report | Reproduced at 640 |
|---|---:|---:|
| Precision | 0.9858 | 0.9902 |
| Recall | 0.9805 | 0.9832 |
| F1 | 0.9832 | 0.9867 |
| mAP@50 | 0.2435 | 0.2442 |
| mAP@50-95 | 0.1269 | 0.1399 |
| FP / FN | 52 / 72 | 36 / 62 |

Close enough to confirm the evaluation path is sound. The difference is
expected and worth flagging: the checkpoint handed back is **epoch 13 of a
30-epoch configuration**, so it is not necessarily the weights that produced
the Sprint 20 report. That should be confirmed before the candidate is
discussed further.

## 8. Defects found

Two of them are why the resolution study initially returned 0.0 at *every*
resolution including 640 — the disagreement with the known Sprint 20 number
is what exposed them.

| Defect | Impact | Status |
|---|---|---|
| `load_into` loaded into the bare YOLOX module while Guardian checkpoints are saved from the wrapper (`yolox_model.` prefix) — 462 tensors unexpected, 388 missing, reported only to the log | any `model.checkpoint` in a config loaded as noise and detected nothing; upstream COCO checkpoints are bare, so it stayed invisible | fixed |
| `load_into` dropped the head whenever `num_classes != 80` — a property of the model, not the checkpoint | discarded the trained head of every Guardian checkpoint | fixed |
| `compare.benchmark_onnx` spreads ±37% across identical repeats | no 20% improvement is detectable through it | profiler added; the gate's benchmark is unchanged |

`train resume` was checked and is unaffected — it `torch.load`s `last.pt`
directly.

## 9. Accepted and rejected optimizations (§16)

**Accepted: `intra_op_num_threads = 2`.**

| | before | after | change |
|---|---:|---:|---:|
| Candidate 640 | 53.70 ms | 35.88 ms | −33% |
| Baseline 416 | 25.41 ms | 18.83 ms | −26% |
| Relative spread | ±32.6% | ±6.7% | reproducible at last |

No accuracy impact — a session option changes no numerics. It does not pass
the gate because the gate is a ratio and both models speed up: 2.11× becomes
1.92× against a 1.20× allowance. **Not applied to production**: the optimal
thread count is a property of the host, and must be re-measured on the Edge
target rather than hardcoded from a Mac.

**Rejected:**

| Optimization | Why |
|---|---|
| Lower resolution (416, 512) | accuracy collapses to 0.0 / 0.026 precision |
| FP16 | not accelerated by the CPU provider the gate benchmarks |
| Graph optimization levels | all four inside measurement noise |
| inter-op thread tuning | no effect; no parallel branches in the graph |
| CoreML provider | 3.5× but Apple-only; not an Edge target |

## 10. Promotion re-evaluation (§17)

**REJECT.** The existing promotion logic is unmodified. Accuracy passes
comfortably; mean latency remains 1.92× the baseline against a 1.20×
allowance, and the only configuration that clears it detects nothing.

## 11. Not measured

- **Full pipeline component breakdown (§3).** `StageTimer` is built and
  tested for it, but an end-to-end pipeline run was not wired. The decisive
  part of §3 was settled regardless: the gate's number contains model
  inference only, so no work on capture, preprocessing, NMS or tracking can
  move it.
- **Edge hardware (§12).** No Jetson or N100 available.

## 12. Recommendation

**Do not promote, and do not spend another sprint optimizing this gate.**

The candidate cannot be made to fit by optimization, and cannot be shrunk by
resolution without destroying it. The gate currently compares a 640×640
candidate against a 416×416 baseline — 2.37× the compute by construction —
so what needs deciding is the comparison, not the model:

1. **Re-baseline at matched resolution.** Export the COCO baseline at 640,
   or the candidate at 416 *with retraining*, so the gate compares like with
   like. This changes no promotion rule; it makes the existing one mean what
   it says.
2. **Move the latency budget onto real Edge hardware.** The product budget
   is < 1 s end to end on a Jetson or N100, not a ratio against a
   development-machine measurement. CoreML's 3.5× here says the model is not
   inherently slow and an accelerated provider is the lever — TensorRT and
   OpenVINO are already anticipated in the repo.

Both are architecture decisions. This sprint stops here for that review.
