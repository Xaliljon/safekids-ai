# ADR-0008: Inference Runtime Contracts

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Sprint 4 builds the model runtime before any model exists. It must be
model-agnostic (fall/zone/cry models and future products all load through
it), backend-replaceable (ONNX Runtime today, TensorRT on Jetson later),
and safe: a wrong model file or wrongly-shaped tensor in a child-safety
system must fail loudly at a boundary, never silently misinfer.

## Decision

1. **The engine port speaks named tensors.** `InferenceEngine.infer` takes
   `{"input_name": tensor}` and returns `{"output_name": tensor}` — no
   positional argument lists. Names come from the manifest, so callers and
   engines can never disagree silently about tensor order. The port also
   mandates `warmup()`, `metrics()`, and `close()`: every backend must be
   measurable and warm-startable, not just runnable. The port graduated
   from `vision/ports.py` to `application/inference/` — the runtime serves
   more than vision (audio later).

2. **The manifest is the gate, checked twice.** A model loads only through
   its `manifest.json` (name, version, task, file, sha256, tensor specs).
   At load time the factory verifies the manifest against the model's
   *actual* graph I/O (names, dtypes, ranks, fixed dims) — a lying manifest
   is a `ModelLoadError`. At call time every input is validated against the
   manifest specs — a wrong tensor is a `TensorValidationError` and never
   reaches the backend. The JSON format mirrors the future contracts/models
   schema.

3. **Dynamic shapes, batch size 1.** Tensor specs use `None` for dynamic
   dimensions (resolution-independent image inputs). By convention the
   first dimension is batch, and the runtime enforces batch = 1: the vision
   pipeline processes one frame at a time (ADR-0006), and cross-camera
   batching complexity is not worth it before profiling proves the need.
   Revisiting this is a manifest/validation change below the Detector seam.

4. **Filesystem model registry** at `<root>/<name>/<version>/` holding
   `manifest.json` + artifact. The registry is the trust boundary: it
   resolves "latest" numerically, refuses missing artifacts, and verifies
   SHA-256 when the manifest declares one (and warns loudly when it does
   not). This layout is exactly what signed OTA model updates will ship
   (ADR-0001 §CD), keeping model delivery decoupled from code delivery.

5. **One blessed load path.** `ModelLoader` = registry lookup → factory
   load → warmup. Warmup runs zero-tensors through the real session so the
   first production inference does not pay allocator/graph-optimization
   cost inside the < 1 s alert budget; warmup runs are counted separately
   in metrics.

6. **Measured by default.** Every engine records per-call latency
   (last/mean/p50/p95 over a sliding window) and error counts via a shared
   recorder — the same metric surface for every backend. ONNX Runtime's
   operator-level profiler is opt-in via the factory (`profiling_dir`) for
   deep dives; its JSON trace path is logged at `close()`.

## Consequences

- Any future backend (TensorRT) implements one protocol and inherits the
  loader, registry, validation, and metrics unchanged; ADR-0003 (detector
  licensing) stays open and nothing here depends on it.
- Manifest authoring becomes mandatory workflow for `ai/export` — no
  manifest, no load, by design.
- Checksum verification hashes the artifact on every `get()`; acceptable at
  load frequency (models load rarely), revisit only if hot-reload appears.
- Batch size 1 leaves accelerator throughput on the table when many cameras
  share one box; that trade is documented and deliberately deferred until
  profiling on target hardware says otherwise.

## Alternatives Considered

- **Positional tensor I/O (lists):** rejected — silent reordering bugs are
  exactly the class of failure a safety system cannot tolerate.
- **Trust the model file, skip manifest verification:** rejected — the
  manifest *is* the contract; an artifact that disagrees with it is either
  a packaging bug or tampering, and both must stop the load.
- **Validate inputs only in debug builds:** rejected — validation cost is
  microseconds next to inference; correctness is not a build flavor.
- **A model server process (e.g. Triton):** rejected at this scale — an
  in-process runtime keeps the < 1 s budget simple and the box dependency-
  light; revisit if multi-process isolation becomes a real requirement.
