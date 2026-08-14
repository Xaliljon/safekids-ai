# Inference Performance

- **Date:** 2026-08-14 (Sprint 20.2)
- **Reflects:** ADR-0008 (inference runtime contracts), ADR-0009 (model management)
- **Scope:** how Guardian measures inference latency, and what the measurements so far actually say

## The latency budget, and what the gate measures

The product budget is the charter's: an alert reaches a director in under a
second, with detection latency under 500 ms, **on an Edge box**. The
promotion gate does not measure that. It measures one thing:

```python
session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
# 5 warmups, then 30 timed session.run() calls on a fixed-seed random tensor
```

`compare.benchmark_onnx` times **model inference alone**. There is no frame
capture in it, no preprocessing, no letterboxing, no NMS, no tracking. It is
a comparator between two models, not a measurement of the pipeline.

That distinction is worth stating loudly, because it decides what
optimization work can possibly pay off: no amount of preprocessing or
postprocessing work moves the number the gate reads.

## Profiling architecture

`guardian_ai.training.profiling` exists because the gate's benchmark cannot
be optimized against. Three identical repeats of it on one idle machine gave
45.4 / 52.3 / 62.1 ms — a ±37% band, inside which a 20% improvement is
invisible.

| Piece | Responsibility |
|---|---|
| `LatencyStats` | mean, p50, p95, min, max, stdev, **relative spread**, sample count. A mean without its spread cannot be reproduced or disputed. |
| `RuntimeConfig` | one session configuration under test — provider, graph optimization level, intra/inter-op threads. Defaults match the gate's, so "before" means the gate's before. |
| `profile_inference` | separates first call, first ten, and steady state (§10 of the sprint brief). |
| `StageTimer` | per-stage accounting. A stage nobody measured is **absent, not zero** — zero reads as "free". |
| `host_provenance` | machine, cores, runtime, providers, and `measurement_class` / `is_edge_target`, so a development number can never be quietly read as an Edge one. |

The gate's own `compare.benchmark_onnx` is deliberately unchanged. Making
the comparator agree with itself across releases matters more than making it
precise, and a benchmark that shifts under a sprint is not a gate.

## What the measurements say

All figures below are **Apple M4 Max — development hardware**. No Jetson or
N100 measurement exists yet. See
[`reports/model-v1/inference-optimization-report.md`](../reports/model-v1/inference-optimization-report.md)
for the full matrices.

### Thread count is the one runtime lever that matters

ONNX Runtime defaults to one intra-op thread per core. On a 14-core
heterogeneous CPU running YOLOX-tiny, synchronisation grows faster than the
parallelism it buys and threads on efficiency cores straggle:

| intra-op threads | candidate 640 | spread |
|---|---:|---:|
| default (14) | 53.70 ms | ±32.6% |
| **2** | **35.88 ms** | **±6.7%** |
| 14 (explicit) | 89.07 ms | ±42.3% |

Two threads is 33% faster than the default *and* is what makes the
measurement reproducible at all. Graph optimization level made no difference
beyond noise; inter-op threads made none at all.

**This is not hardcoded.** The optimal count is a property of the host, and
must be re-measured on the Edge target rather than carried over from a Mac.

### ONNX Runtime earns its place

PyTorch 56.52 ms vs ONNX Runtime 33.45 ms on the same tensor at the same
thread count — **1.69×**.

### Resolution is not a latency lever

The candidate trains at 640. Re-exporting the same weights at 416 passes the
latency gate at exactly 1.00× and detects **nothing**: 3015 detections, none
correct, precision 0.000. At 512 it reaches 0.026. The anchor-free head's
scale priors belong to the training resolution and do not survive being
re-exported at another one.

Lower resolution is available only *with retraining*, which is a model
decision, not an optimization.

### An accelerated provider is the real lever — and it is untested on target

CoreML runs the same model at 10.23 ms, 3.5× the CPU provider. That is not a
recommendation: CoreML is Apple-only and the Edge targets are Jetson and
N100. It is evidence of two things — the model is not inherently slow, and
the CPU execution provider is the constraint. TensorRT (Jetson) and OpenVINO
(N100) are the equivalents, both already anticipated, neither yet measured.

## Known limitations

- **No Edge measurement exists.** Everything here is development hardware.
  The gate's ratio and the product's millisecond budget are different
  questions, and only the first has been answered.
- **The gate compares mismatched configurations.** A 640×640 candidate
  against a 416×416 baseline is 2.37× the compute by construction. Until
  that is resolved, the latency clause tests resolution, not efficiency.
- **The pipeline breakdown is unbuilt.** `StageTimer` is ready for it; no
  end-to-end run has been wired through it, so capture, preprocessing, NMS
  and tracking costs remain unmeasured on the training side. (The edge
  runtime reports its own per-stage figures through `/health`.)
- **FP16 is unmeasured on target.** It cannot help the CPU provider the gate
  benchmarks; it is likely to help TensorRT considerably.

## Future opportunities, in the order worth trying

1. Benchmark on a Jetson and an N100. Every number on this page is a proxy.
2. TensorRT export for Jetson, with FP16 — the combination CoreML's result
   suggests is worth several-fold.
3. Re-baseline the promotion comparison at matched input resolution, so the
   latency clause measures what it claims to.
4. Wire `StageTimer` through a full pipeline run, so the product's real
   end-to-end budget is measured rather than assumed from the model alone.
