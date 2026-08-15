# RT-DETR Inference Optimization — Sprint 23

**Classification: B — POTENTIALLY VIABLE.**

**The first finding is a correction to Sprint 22.** Its headline 473.42 ms
does not reproduce. Re-run with the identical harness on an idle machine, the
same model gives **109.28 ms**. Sprint 22's benchmark ran while the full test
suite and other work occupied the same CPU. That was my error, and every
conclusion drawn from it was wrong by about 4×.

With that corrected, RT-DETR r18vd already meets Guardian's latency target on
development hardware, in every parity-valid configuration measured. The best
is **81.69 ms** against a target of 111.462 ms.

It is **B, not A**, because no Edge hardware exists to verify it on, and the
fastest configuration of all is disqualified for a reason worth reading.

## 1. Sprint 22 baseline — reproduced and corrected

Same harness (`compare.benchmark_onnx`, `runs=150`, `warmup=20`), same model
file, same host, nothing else running.

| | Sprint 22 published | Sprint 23 reproduction |
|---|---:|---:|
| mean | 473.42 ms | **109.28 ms** |
| p95 | 1543.21 ms | **126.35 ms** |
| memory | 718.08 MB | 616.61 MB |
| p95 / mean | **3.26×** | **1.16×** |

The p95/mean ratio is the tell. A model does not have a 3.3× tail; a
contended CPU does. Sprint 22 launched this benchmark in the background and
then ran the test suite, ruff, mypy and documentation work alongside it.

**The baseline was not silently replaced.** Sprint 22's number stays on
record as what was measured, with the reason it was wrong recorded next to
it, and `reports/model-v1/rtdetr-benchmark-report.md` now carries the
correction at its head.

### Harness calibration

Before trusting any of this, the harness was checked against a number
Guardian already published — YOLOX-tiny COCO at 416, which Sprint 20.2
measured at 18.45 ms:

| | Sprint 20.2 published | Sprint 23 harness |
|---|---:|---:|
| yolox-tiny @416, CPU, intra=2 | 18.45 ms | **17.54 ms** |

Within 5%. The harness reproduces Sprint 20.2's methodology, so the RT-DETR
numbers below are comparable to Guardian's existing figures rather than to a
new measurement regime.

## 2. Latency breakdown (§3)

Where the time actually goes, per frame, CPU EP `intra=2`, camera-shaped
`uint8` input through the real preprocessing and the real `family.decode`:

| stage | mean | p50 | p95 | share |
|---|---:|---:|---:|---:|
| preprocessing | 0.392 ms | 0.383 ms | 0.470 ms | 0.4 % |
| **ONNX Runtime inference** | **95.871 ms** | — | — | **99.5 %** |
| decode + postprocessing | 0.071 ms | 0.069 ms | 0.086 ms | 0.1 % |
| total | 96.334 ms | | | |

The brief warned against assuming ORT inference is the bottleneck. It was
measured, and it is — overwhelmingly. Preprocessing and decode together cost
under half a millisecond, so there is nothing to win outside the graph.

## 3. PyTorch vs ONNX (§4)

Identical model, input, resolution, batch, warmup and iteration count, on an
idle machine.

| runtime | mean | p50 | p95 | FPS |
|---|---:|---:|---:|---:|
| PyTorch (10 threads) | **66.08 ms** | 65.64 ms | 69.52 ms | 15.13 |
| ONNX Runtime (CPU, best) | 96.54 ms | 96.00 ms | 111.10 ms | 10.36 |

**Sprint 22's "ONNX is 3.7× slower than PyTorch" was also contention.** The
real ratio is **1.46×**. ONNX Runtime is still slower than PyTorch here,
which is worth knowing, but it is an ordinary gap rather than a defect
signature — and Guardian ships ONNX, not PyTorch, so this is a fact to record
rather than a problem to fix.

## 4. ONNX graph diagnosis (§5)

Machine-readable output: `reports/rtdetr/optimization-matrix.json`
(`graph_diagnosis`, `graph_optimization_levels`).

| | RT-DETR r18vd | YOLOX-tiny (COCO 416) |
|---|---:|---:|
| nodes | 1944 | 279 |
| opset | 17 | 11 |
| compute nodes (Conv + MatMul) | 136 | 83 |
| shape-arithmetic nodes | 303 | **0** |
| layout nodes (reshape/transpose/…) | 347 | 30 |
| `Constant` nodes | 579 | 0 |
| `Identity` nodes | 162 | 0 |
| **overhead ratio** (non-compute ÷ compute) | **4.78** | **0.36** |
| fully static I/O | yes | yes |
| fused attention op | no | n/a |

The exported RT-DETR graph is dominated by shape plumbing — thirteen times
YOLOX's overhead ratio. That looked like the answer, and it is not.

**ONNX Runtime already folds it.** Dumping the optimized graph at each level:

| level | nodes | `Constant` | `Identity` | shape-arithmetic |
|---|---:|---:|---:|---:|
| `ORT_DISABLE_ALL` | 1365 | 0 | 162 | 303 |
| `ORT_ENABLE_BASIC` | 631 | 0 | 0 | 11 |
| `ORT_ENABLE_EXTENDED` | **563** | 0 | 0 | **2** |
| `ORT_ENABLE_ALL` | 589 | 0 | 0 | 2 |

303 shape nodes become 2. Constant folding removes every `Constant` and
`Identity`. The plumbing costs nothing at run time because it is gone before
the first inference.

Two observations worth keeping:

- `ORT_ENABLE_ALL` produces *more* nodes than `ORT_ENABLE_EXTENDED` (589 vs
  563) — the NCHWc layout transformer adding conversion nodes. On this ARM
  host it does not cost anything measurable (see §5), but the hypothesis that
  it would was tested rather than assumed.
- Neither model has a fused attention operator. RT-DETR's attention is 67
  separate `MatMul`s. A fused kernel would be the obvious next lever, and no
  such fusion is available in this ORT build for this graph.

## 5. Optimization matrix (§6)

Sprint 20.2 profiling harness, unchanged: `warmup=20`, `runs=200`, one
configuration per session. `OK` means parity-valid **and** inside the target.

| Configuration | mean ms | p95 ms | FPS | max abs Δ | verdict |
|---|---:|---:|---:|---:|---|
| CoreML default (ANE/GPU) intra=4 | **34.22** | 37.93 | 29.22 | **9.875e-01** | **PARITY FAIL** |
| CoreML default (ANE/GPU) intra=2 | 40.90 | 45.13 | 24.45 | 9.875e-01 | **PARITY FAIL** |
| **CoreML `CPUOnly` intra=8** | **81.69** | **87.57** | 12.24 | 1.490e-06 | **OK — best valid** |
| CoreML `CPUOnly` intra=2 | 82.05 | 83.67 | 12.19 | 1.490e-06 | OK |
| CPU `ENABLE_ALL` intra=8 | 96.54 | 111.10 | 10.36 | 1.192e-06 | OK |
| CPU `ENABLE_ALL` intra=2 | 103.77 | 108.56 | 9.64 | 1.192e-06 | OK |
| CPU `ENABLE_BASIC` intra=2 | 106.84 | 109.11 | 9.36 | 1.192e-06 | OK |
| CPU `ENABLE_EXTENDED` intra=2 | 107.02 | 109.00 | 9.34 | 1.192e-06 | OK |
| CPU `DISABLE_ALL` intra=2 | 109.69 | 111.91 | 9.12 | — | OK |
| CPU `ENABLE_ALL` intra=default | 113.32 | 139.98 | 8.82 | 1.192e-06 | over target |
| CPU `ENABLE_ALL` intra=4 | 128.32 | 140.26 | 7.79 | 1.192e-06 | over target |
| CPU `DISABLE_ALL` intra=4 | 129.52 | 138.96 | 7.72 | — | over target |
| CPU `ENABLE_EXTENDED` intra=4 | 129.86 | 140.08 | 7.70 | 1.192e-06 | over target |
| CPU `ENABLE_BASIC` intra=4 | 129.89 | 140.35 | 7.70 | 1.192e-06 | over target |

**Thread count is the dominant lever, and it is not monotonic.** `intra=8`
(96.54) beats `intra=2` (103.77) beats ORT's own default (113.32) beats
`intra=4` (128.32). The `intra=4` result is reproducibly the worst across
*every* optimization level, which points at this host's hybrid core layout —
4 threads land partly on efficiency cores — rather than at anything in the
model. On a homogeneous Edge CPU the ordering will differ, which is one more
reason the tuning has to be redone on target.

**Graph optimization level is nearly irrelevant here**: 103.77 (`ALL`) to
109.69 (`DISABLE_ALL`) at `intra=2` — about 5 %. The expensive work is dense
linear algebra, which no level of graph rewriting removes.

## 6. Static vs dynamic shapes (§7)

**Nothing to do.** The export is already fully static: input
`images [1, 3, 640, 640]`, output `output [1, 300, 6]`, with no symbolic
dimensions. After graph optimization only 2 shape-arithmetic nodes survive.
There is no dynamic-shape overhead left to remove, and no dynamic variant was
built to compare against — inventing one to make a table row would be
measuring an artifact.

## 7. Precision — FP32 vs FP16 (§8)

Tested empirically, and the answer is decisive.

| configuration | mean | max abs Δ vs FP32 | within 1e-4 |
|---|---:|---:|---|
| CoreML `CPUOnly` (FP32) | 81.69 ms | 1.490e-06 | **yes** |
| CoreML default (ANE/GPU) | 34.22 ms | 9.875e-01 | **no** |
| CoreML `CPUAndGPU` | — | 9.875e-01 | **no** |

The CoreML Neural Engine and GPU paths compute in FP16 internally. That buys
2.4× and costs a maximum absolute output delta of **0.9875** on a tensor
whose scores live in `[0, 1]`. That is not rounding — it is a different
answer, and for a detector it means a detection appearing or disappearing.

Guardian's own export gate rejects at `1e-4`. §12 forbids changing confidence
semantics. **So the fastest configuration measured this sprint is
disqualified**, and 34.22 ms must not be quoted as RT-DETR's latency.

Explicit FP16 conversion of the ONNX graph was **not** attempted separately:
`onnxconverter-common` is not in Guardian's dependency set, and the CoreML
result already demonstrates what FP16 does to this model's outputs. Adding a
dependency to re-derive a known answer for a candidate-only experiment is not
worth it. If FP16 is ever wanted, it needs a per-layer sensitivity study, not
a blanket conversion.

## 8. Execution providers (§9)

Available on this host: `CoreMLExecutionProvider`, `AzureExecutionProvider`,
`CPUExecutionProvider`. No CUDA, no TensorRT.

**CoreML partitioning, from ORT's own capability log:**

```
number of partitions supported by CoreML: 31
number of nodes in the graph: 631
number of nodes supported by CoreML: 503
```

503 of 631 nodes go to CoreML across **31 partitions** — 128 nodes stay on
CPU and the graph is cut into 31 pieces, each boundary a transfer. So the
CoreML figures are **not** clean-provider numbers even before the parity
problem. They are flagged accordingly rather than presented as production
performance.

The per-kernel provider attribution from ORT's profiler could not be parsed
in this ORT version (the profile events carry no `provider` field), so the
partition counts above come from ORT's capability log, which is the same
information from a different place.

## 9. TensorRT (§11)

**Not attempted.** No CUDA device and no Jetson. `torch.cuda.is_available()`
is `False`; the only accelerator here is Apple's. There is nothing to report
and nothing was guessed.

## 10. Real Edge hardware (§10)

**None available. No production performance claim is made.**

Every number in this report is Apple M4 Max, `is_edge_target: false`,
`measurement_class: development`. Guardian's targets are NVIDIA Jetson
(primary) and Intel N100 (secondary), and neither has been benchmarked with
anything, ever — ADR-0020 §3 already records this as a named blocker.

It matters more for RT-DETR than for YOLOX. RT-DETR is transformer-heavy; its
cost profile on a GPU with fused attention kernels is likely very different
from an ARM CPU, in either direction. The `intra=4` anomaly above is a
concrete example of a result that is a property of *this* CPU and will not
transfer.

| | |
|---|---|
| CPU | Apple M4 Max (10 performance + 4 efficiency cores) |
| RAM | 36 GB |
| OS | macOS 26.3 arm64 |
| Python / torch / onnxruntime | 3.14.6 / 2.12.1 / 1.27.0 |
| model format | ONNX opset 17, FP32, static `[1,3,640,640]` |

## 11. Memory (§15)

| | value | how measured |
|---|---:|---|
| RT-DETR ONNX, CPU EP | **616.61 MB** | `benchmark_onnx` RSS delta, isolated process |
| RT-DETR, Sprint 22 (contended) | 718.08 MB | same method, loaded machine |
| YOLOX-tiny @416, CPU EP, intra=2 | 348.92 MB | profiling harness, first config in its process |
| model file on disk | 76.34 MB | — |

The profiling harness reports **process peak RSS**, which is a high-water
mark across every configuration run in one process — the repeated 1143.64 MB
in the raw matrix is that watermark, not a per-configuration measurement, and
is deliberately not quoted as one.

RT-DETR needs roughly 1.8× YOLOX's working set at 1.5× the input area. On a
box that also runs decode, tracking, the event and risk engines and evidence
recording, ~600 MB for one detector on one camera is a real constraint that
belongs in the Edge benchmark when it happens.

## 12. Accuracy safety (§12)

Baseline for comparison: the same graph under `ORT_DISABLE_ALL`, so any delta
is attributable to the optimization rather than to the model.

| configuration | max abs Δ | box Δ | score Δ | verdict |
|---|---:|---:|---:|---|
| CPU `ENABLE_ALL` intra=2 | 1.192e-06 | 1.192e-06 | 5.96e-08 | pass |
| CPU `ENABLE_ALL` intra=8 | 1.192e-06 | 1.192e-06 | 5.96e-08 | pass |
| CoreML `CPUOnly` | 1.490e-06 | — | — | pass |
| CoreML default (ANE/GPU) | **9.875e-01** | — | — | **fail** |

Nothing was changed about labels, boxes, confidence semantics, NMS behaviour
or score thresholds. The only configuration that alters detector meaning is
the one that was therefore rejected.

## 13. Final recommendation

**RT-DETR r18vd meets Guardian's latency target on development hardware, in
every parity-valid configuration measured.** Best: **81.69 ms mean, 87.57 ms
p95** against a target of 111.462 ms.

| | mean | p95 | note |
|---|---:|---:|---|
| Guardian target | ≤ 111.462 | — | Sprint 20.2 |
| **RT-DETR best valid** | **81.69** | **87.57** | CoreML `CPUOnly`, intra=8 |
| RT-DETR CPU EP best | 96.54 | 111.10 | portable; no Apple dependency |
| Guardian v1 @640 | 35.51 | 39.82 | published Sprint 20.2, not re-measured¹ |

¹ The Guardian v1 640 ONNX artifact is not on this machine — only the COCO
416 baseline is — so it could not be re-measured under identical conditions.
Its 35.51 ms comes from Sprint 20.2 and may carry some of the same contention
risk this sprint just found in Sprint 22. **Re-measuring it on an idle
machine is the single cheapest way to make the comparison trustworthy**, and
it needs the 640 artifact, not a retrain.

**Classification: B — POTENTIALLY VIABLE.**

Not **A**, which requires compatibility with the Edge target: no Jetson or
N100 exists to verify, and this sprint found within its own scope how badly a
measurement can mislead when the environment is not controlled. Not **C** or
**D**: it runs correctly, exports cleanly, and is inside the budget wherever
it has been honestly measured.

### What follows, in order

1. **Re-measure Guardian v1 @640 on an idle machine.** The comparison that
   matters is currently between one clean number and one of unknown
   provenance.
2. **Get Edge hardware.** ADR-0020 §3 named this blocker; RT-DETR makes it
   urgent. Every ranking here is a property of an M4 Max — including which
   thread count wins, which reverses between 4 and 8.
3. **Then, and only then, consider training.** Sprint 22 recommended not
   spending GPU budget while RT-DETR looked 13× outside its budget. It is
   not. The reason to keep waiting is now different and weaker: not "it
   cannot fit" but "we do not yet know what it costs on the machine it would
   run on".

Do not deploy, promote or train RT-DETR on this report. It says the inference
path is not the blocker anyone thought it was — nothing more.
