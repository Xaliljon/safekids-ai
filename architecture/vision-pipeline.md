# Vision Pipeline

- **Date:** 2026-07-05 (Sprint 3)
- **Reflects:** ADR-0001 (Clean Architecture), ADR-0006 (vision pipeline decisions)
- **Scope:** vision infrastructure only — no real models, no tracking, no risk engine

## Purpose

Turns the camera service's frame stream into `DetectionResult`s and optional
annotated overlay frames. Today it runs the deterministic `DummyDetector`;
real detectors replace it behind the same port without touching the pipeline.

## Component view

```mermaid
flowchart LR
    subgraph camera [Camera Service]
        CS[CameraService]
    end
    subgraph vision-app [Vision Application]
        VP[VisionPipeline<br/>1-slot mailbox per camera<br/>single worker thread]
        DP[[Detector port]]
        IE[[InferenceEngine port<br/>application/inference, ADR-0008]]
        OP[[OverlayRenderer port]]
    end
    subgraph vision-infra [Vision Infrastructure]
        DD[DummyDetector<br/>deterministic]
        OV[OpenCvOverlayRenderer]
    end
    RC([DetectionConsumer<br/>future risk engine])
    AC([AnnotatedFrameConsumer<br/>debug / future dashboard])

    CS -- "FrameConsumer: on_frame()" --> VP
    VP --> DP
    DD -. implements .-> DP
    DD -. "future detectors compose" .-> IE
    VP --> OP
    OV -. implements .-> OP
    VP -- DetectionResult --> RC
    VP -- AnnotatedFrame --> AC
```

The **only** coupling to the camera service is `pipeline.on_frame` passed as
its `FrameConsumer`; capture has no knowledge of AI. The **only** outbound
coupling is the consumer callables; vision has no knowledge of the risk
engine (ADR-0006 §4).

## Data flow and threading

```
capture thread (per camera)          vision worker (one thread)
────────────────────────────         ─────────────────────────────
frame ──> on_frame():                loop:
            mailbox[cam] = frame       frame = pop next pending camera
            (replaces unprocessed      result = detector.detect(frame)
             frame; drop counted)      detection_consumer(result)
            return immediately         overlay? render -> annotated_consumer
```

- **Latest-frame-wins:** a newer frame replaces an unprocessed older one;
  drops are counted in `PipelineStats`, never silent. Real-time monitoring
  analyzes the present, not a backlog.
- **Failure isolation:** a crashing detector skips that frame (counted as
  `detector_errors`); a crashing consumer loses that result only; the worker
  never dies. Overlay failures never cost detection results.
- `process_once()` allows deterministic, threadless processing in tests.

## Domain model

| Type | Meaning |
|---|---|
| `BoundingBox` | Normalized `[0,1]` geometry, top-left origin; `to_pixels()` maps to a frame (ADR-0006 §2) |
| `Detection` | label + confidence (validated `[0,1]`) + box, **plus full identity** (ADR-0007): `detection_id`, `frame_id`, `camera_id`, `captured_at`, `correlation_id` — self-contained for tracking, risk, analytics, notifications |
| `DetectionResult` | everything concluded about one frame: detections, `ModelDescriptor` (name + version — every result is traceable to a model, docs/04), inference latency; rejects detections whose identity disagrees with its own |
| `ModelDescriptor` | model identity carried on every result |

### Identity & correlation (ADR-0007)

`frame_id` and `correlation_id` are minted **at capture** in the `Frame`
constructor; `detection_id` is minted by the detector. Downstream stages
propagate ids, never regenerate them. `correlation_id` is the trace token
of the whole causal chain (capture → detections → tracks → risk events →
notifications → analytics), so any alert can be traced back to the exact
frame that caused it.

## Detector abstraction (Sprint 5)

`EngineDetector` implements the Detector port for **any** object detection
model by composing pluggable stages around an `InferenceEngine` (ADR-0008):

```
preprocess ──> infer ──> decode ──> confidence filter ──> NMS ──> map
(Preprocessor) (engine)  (OutputDecoder)  (DetectorConfig)  (NonMaxSuppression)  (DetectionResultMapper)
```

- **A model family contributes exactly two adapters** — a `Preprocessor`
  (frame → named tensors + geometry `meta`) and an `OutputDecoder` (output
  tensors + `meta` → normalized `RawDetection`s). Everything else —
  thresholds, suppression, capping, label resolution, identity stamping —
  is inherited. The detector core never inspects `meta`; it flows opaquely
  from a family's preprocessor to its decoder.
- **`DetectorConfig`** holds labels + thresholds (confidence, NMS IoU,
  max detections). `DetectorConfig.from_manifest()` reads them from the
  model's own manifest `metadata` (labels required), with per-deployment
  keyword overrides winning — thresholds tune without touching models.
- **`GreedyNms`** is the default `NonMaxSuppression`: class-aware greedy
  IoU suppression (pure Python; replaceable behind the port). IoU lives on
  `BoundingBox.intersection_over_union` — tracking will reuse it.
- **`DetectionResultMapper`** is the single place model-space candidates
  become domain detections: label indices resolve to names (out-of-range
  fails loudly — never guess a safety label), and every detection is
  stamped per ADR-0007.
- **Generic infrastructure adapters:** `ImagePreprocessor` (BGR uint8 →
  float32 NCHW [0,1], fixed-size resize or dynamic) and `TensorRowDecoder`
  (`[1, N, 6]` rows `(x, y, w, h, confidence, class)`), used by the
  **dummy ONNX detector** (`create_dummy_onnx_detector`) — a synthetic
  constant-output graph loaded through the real registry → loader → ONNX
  Runtime path, proving the whole abstraction end-to-end with no YOLO and
  no real model. A real family later = registry entry + its adapter pair.

## Overlay renderer

`OpenCvOverlayRenderer` draws on a **copy** of the frame buffer (the original
is never mutated — other consumers see original pixels): per-label stable
colors (CRC-indexed palette), label + confidence caption per box (confidence
is always visible, docs/04), FPS top-left, frame timestamp (UTC) bottom-left.

## DummyDetector

Deterministic synthetic detections — a pure function of frame sequence, so
identical frames yield identical results across runs. Boxes sweep the frame
so the flow is visibly alive in development. It never ships to production;
it exists so pipeline, overlay, tests, and future consumers work before any
model does.

## Observability

`VisionPipeline.stats()` per camera: frames received / processed / dropped,
detector errors, processing FPS (10 s window). Complements the camera
service's `CameraHealth`.

## Out of scope (later sprints)

Model backends implementing `InferenceEngine` (ONNX Runtime, TensorRT),
real detectors, tracking, pose estimation, risk engine, evidence clips.
Their seams exist: `InferenceEngine`, `Detector`, `DetectionConsumer`.
