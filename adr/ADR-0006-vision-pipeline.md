# ADR-0006: Vision Pipeline Architecture

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

Sprint 3 builds the vision infrastructure before any real model exists. The
pipeline must integrate with the camera service without coupling capture to
AI, stay real-time on single-accelerator edge hardware (< 1 s alert budget),
and leave clean seams for model backends (ONNX Runtime/TensorRT), tracking,
and the risk engine — none of which exist yet. Four decisions shape it.

## Decision

1. **Two-level AI abstraction: `Detector` above `InferenceEngine`.**
   The pipeline drives the task-level `Detector` port (frame in,
   `DetectionResult` out) and knows nothing else. Real detectors will
   compose the runtime-level `InferenceEngine` port (load/infer/close) with
   pre/post-processing. Backends become swappable below the Detector seam
   without touching pipeline code (docs/03: AI is a subsystem, models
   replaceable).

2. **Normalized bounding-box coordinates.** All detection geometry is
   fractions of frame size in `[0, 1]`, top-left origin. Results stay valid
   across stream resolutions and are independent of any model's input size;
   pixel mapping happens only at render time (`BoundingBox.to_pixels`).

3. **Latest-frame-wins handoff, single inference worker.**
   `VisionPipeline.on_frame` satisfies the camera service's `FrameConsumer`
   contract by writing into a one-slot-per-camera mailbox and returning —
   capture threads never wait on inference. One worker thread serializes
   detector calls (edge boxes have one accelerator; concurrency belongs
   inside the engine later, e.g. batching). When inference is slower than
   capture, older unprocessed frames are **dropped and counted** —
   real-time safety monitoring must analyze the present, not a backlog.
   Unbounded queues would trade staleness for memory growth; both are
   unacceptable on a safety device.

4. **Consumers are the only outbound coupling.** Results leave via
   `DetectionConsumer`, rendered overlays via `AnnotatedFrameConsumer`.
   The future risk engine attaches as a detection consumer; the vision
   package has no knowledge of it — mirroring how the camera service does
   not know vision exists.

Additionally: `DummyDetector` (deterministic synthetic detections, pure
function of frame sequence) ships in infrastructure so the whole edge flow
runs end-to-end before any model lands, and every `DetectionResult` carries
a `ModelDescriptor` so downstream decisions stay traceable to a named,
versioned model (docs/04, transparency).

## Consequences

- Frame drops are normal, visible in `PipelineStats`, and by design;
  consumers must not assume they see every captured frame.
- Per-camera fairness is round-robin over pending mailboxes; a slow detector
  degrades FPS uniformly rather than starving one camera.
- The single-worker assumption is revisited when a backend supports batched
  or multi-stream inference — that change stays below the Detector port.
- The overlay renderer copies each frame it draws on; the debug/annotated
  path costs one buffer copy and is disabled by simply not wiring a consumer.

## Alternatives Considered

- **Synchronous inference on capture threads:** rejected — violates the
  FrameConsumer contract ("fast, never block"), couples capture health to
  model latency, and multiplies detector state across threads.
- **Bounded FIFO queue per camera:** rejected — under sustained overload a
  FIFO serves the *oldest* frame first, maximizing staleness; safety
  monitoring needs the newest evidence.
- **One worker thread per camera:** rejected for now — serializing a single
  accelerator adds context switching without throughput, and multiplies
  detector instances (model memory) per camera.
- **Pixel-space detection coordinates:** rejected — ties results to a
  specific stream resolution and breaks silently when a camera's stream
  profile changes.
