# RT-DETR Inference Performance

- **Date:** 2026-08-15 (Sprint 23)
- **Reflects:** ADR-0020 (what the latency gate compares), ADR-0008
  (inference runtime contracts), ADR-0003 (detector licensing)
- **Scope:** the RT-DETR inference path only. No training, no accuracy, no
  promotion.
- **Verdict:** **B — potentially viable.** Meets Guardian's latency target on
  development hardware in every parity-valid configuration; unverified on the
  Edge target.

## The correction this document exists to record

Sprint 22 published RT-DETR at **473.42 ms** mean and concluded it was 13.3×
slower than Guardian v1. That number does not reproduce. Re-run with the
identical harness on an idle machine: **109.28 ms**.

The benchmark had been launched in the background while the full test suite,
ruff, mypy and documentation work ran on the same CPU. The p95/mean ratio was
**3.26×** — a model does not have a tail like that, a contended machine does
— and the signal was there to read at the time.

Two rules come out of it, and they are cheap:

1. **A latency benchmark gets the machine to itself.** Nothing else runs.
2. **p95/mean is a validity check, not a statistic.** Above roughly 1.5× on a
   steady-state loop, suspect the environment before the model.

## Methodology

Sprint 20.2's profiling harness, unchanged: `warmup=20`, `runs=200`, one
configuration per session, fixed-seed synthetic input.

**The harness was calibrated before it was trusted.** YOLOX-tiny COCO at 416,
which Sprint 20.2 published at 18.45 ms, measured **17.54 ms** here — within
5 %. That makes every RT-DETR figure comparable to Guardian's existing
numbers rather than to a new regime.

## Where the time goes

Per frame, CPU EP `intra=2`, real preprocessing and real `family.decode`:

| stage | mean | share |
|---|---:|---:|
| preprocessing | 0.392 ms | 0.4 % |
| **ONNX Runtime inference** | **95.871 ms** | **99.5 %** |
| decode + postprocessing | 0.071 ms | 0.1 % |

There is nothing to win outside the graph. Preprocessing and decode together
cost under half a millisecond.

## ONNX graph findings

The exported graph looks alarming and is not the problem.

| | RT-DETR r18vd | YOLOX-tiny |
|---|---:|---:|
| nodes | 1944 | 279 |
| compute nodes (Conv + MatMul) | 136 | 83 |
| shape-arithmetic nodes | 303 | 0 |
| layout nodes | 347 | 30 |
| overhead ratio | **4.78** | **0.36** |

Thirteen times YOLOX's overhead ratio — and ORT folds essentially all of it
before the first inference:

| optimization level | nodes | shape-arithmetic |
|---|---:|---:|
| `ORT_DISABLE_ALL` | 1365 | 303 |
| `ORT_ENABLE_BASIC` | 631 | 11 |
| `ORT_ENABLE_EXTENDED` | 563 | **2** |
| `ORT_ENABLE_ALL` | 589 | 2 |

Measured contribution of graph optimization to latency: **about 5 %**
(103.77 ms at `ALL` vs 109.69 ms at `DISABLE_ALL`, `intra=2`). The expensive
work is dense linear algebra, which graph rewriting does not remove.

`ORT_ENABLE_ALL` emits *more* nodes than `ORT_ENABLE_EXTENDED` — the NCHWc
layout transformer, which targets x86. The hypothesis that it would cost
something on ARM was tested and did not hold.

Neither model has a fused attention operator; RT-DETR's attention is 67
separate `MatMul`s. A fused kernel is the obvious remaining lever and none is
available in this ORT build for this graph.

## Provider behaviour

Available: `CoreMLExecutionProvider`, `AzureExecutionProvider`,
`CPUExecutionProvider`. No CUDA, no TensorRT.

CoreML takes **503 of 631 nodes across 31 partitions** (from ORT's capability
log). 128 nodes stay on CPU and every partition boundary is a transfer, so
CoreML numbers are not clean-provider numbers even before precision enters.

**And precision does enter.** This is the sprint's second finding:

| CoreML compute units | mean | max abs Δ vs FP32 | verdict |
|---|---:|---:|---|
| default (ANE/GPU) | **34.22 ms** | **9.875e-01** | **rejected** |
| `CPUAndGPU` | — | 9.875e-01 | rejected |
| `CPUOnly` | 81.69 ms | 1.490e-06 | accepted |

The Neural Engine and GPU paths compute in FP16. That buys 2.4× and changes
the output by up to **0.9875** on a tensor whose scores live in `[0,1]` —
not rounding, a different answer, and on a detector that means a detection
appearing or disappearing.

Guardian's export gate rejects at `1e-4`. **The fastest configuration
measured is therefore disqualified, and 34.22 ms must never be quoted as
RT-DETR's latency.** This doubles as the FP16 answer: FP16 is unsafe for this
model without a per-layer sensitivity study.

## Thread behaviour

The dominant CPU lever, and **not monotonic**:

| intra_op_threads | mean |
|---|---:|
| 8 | **96.54 ms** |
| 2 | 103.77 ms |
| ORT default | 113.32 ms |
| 4 | 128.32 ms |

`intra=4` is reproducibly the worst across *every* optimization level. That
points at this host's hybrid core layout — 4 threads landing partly on
efficiency cores — rather than at anything in the model, and it will not
transfer to a homogeneous Edge CPU. It is a good example of why the tuning
has to be redone on target rather than carried over.

## Results

Target: **mean ≤ 111.462 ms** (Sprint 20.2).

| configuration | mean | p95 | parity | verdict |
|---|---:|---:|---:|---|
| CoreML default (ANE/GPU) | 34.22 ms | 37.93 ms | 9.875e-01 | **rejected** |
| **CoreML `CPUOnly` intra=8** | **81.69 ms** | **87.57 ms** | 1.49e-06 | **best valid** |
| CPU `ENABLE_ALL` intra=8 | 96.54 ms | 111.10 ms | 1.19e-06 | best portable |
| CPU `ENABLE_ALL` intra=2 | 103.77 ms | 108.56 ms | 1.19e-06 | pass |
| PyTorch (reference) | 66.08 ms | 69.52 ms | n/a | not shipped |
| Guardian v1 @640 | 35.51 ms | 39.82 ms | — | published, not re-measured |

ONNX vs PyTorch is **1.46×**, not the 3.7× Sprint 22 reported — that gap was
contention too.

Memory: **616.61 MB** for RT-DETR against 348.92 MB for YOLOX-tiny @416,
measured as an RSS delta in isolated processes. (The profiling harness's
`peak_rss_mb` is a process high-water mark across configurations and is not a
per-configuration figure.)

## Known limitations

- **No Edge hardware.** Every number is Apple M4 Max,
  `is_edge_target: false`. ADR-0020 §3 already names this blocker; RT-DETR
  makes it urgent, because a transformer detector's cost on a GPU with fused
  attention may differ substantially in either direction.
- **TensorRT untested** — no CUDA device.
- **Guardian v1 @640 was not re-measured.** That artifact is not on this
  machine, only the COCO 416 baseline. Its 35.51 ms may carry the same
  contention risk this sprint just found. Re-measuring it on an idle machine
  is the cheapest way to make the comparison trustworthy.
- **Static shapes needed no work** — the export is already
  `[1,3,640,640] → [1,300,6]` with no symbolic dimensions, and no dynamic
  variant was built to compare against, because inventing one to fill a table
  row would be measuring an artifact.
- Randomly initialised weights. Latency depends on architecture and tensor
  shapes rather than values, so the timings are valid for cost and say
  nothing about accuracy.

## Viability decision

**B — potentially viable.**

Not **A**: A requires compatibility with the Edge target and no Jetson or
N100 exists to verify it on. Not **C** or **D**: RT-DETR runs correctly,
exports cleanly, passes parity on every accepted configuration, and is inside
the latency budget wherever it has been honestly measured.

The inference path is not the blocker Sprint 22 believed it was. What remains
is a hardware question, not a model question.
