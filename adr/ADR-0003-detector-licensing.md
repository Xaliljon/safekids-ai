# ADR-0003: Object Detector Selection and Licensing

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Founder, Lead Software Architect

## Context

CLAUDE.md names "YOLO" in the AI stack, but the ubiquitous Ultralytics
YOLO (v5/v8/v11) is **AGPL-3.0**: shipping it inside the proprietary
Guardian Edge Box would obligate releasing our source, and buying out of
that requires a per-seat commercial license. This risk was flagged in the
Sprint 1 audit and has blocked every model integration since; the on-device
`LicensePolicy` (ADR-0009) already refuses AGPL bundles structurally.
Sprint 8 integrates the first real detector, so the decision is now due.

## Decision

1. **YOLOX is the first detector family** (Megvii, **Apache-2.0** — code
   and released weights). Anchor-free YOLO-family architecture with
   competitive accuracy/latency, official ONNX exports, a simple published
   decode, and TensorRT support for the Jetson path later. It satisfies
   the CLAUDE.md "YOLO" intent with a license we can ship.

2. **First artifact: `yolox_tiny.onnx`** from the official
   `0.1.1rc0` release (fixed 416×416 input, 80 COCO classes, ~20 MB,
   ~18 ms/frame CPU on a dev machine), registered in the model zoo as
   `yolox-tiny` v`0.1.1-rc0` with license `Apache-2.0` and pinned SHA-256
   `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7`
   (trust-on-first-use against the GitHub release, then enforced forever
   by the zoo).

3. **Pretrained COCO weights are for platform bring-up and pilot demos
   only.** SafeKids production models will be trained on our own datasets
   (ADR-0010 platform) and registered as `Proprietary-GuardianAI`. The
   `person` class is the only COCO class SafeKids consumes today.

4. Integration happens **only through existing seams**: zoo/registry →
   `ModelLoader` → `OnnxRuntimeEngine` → `EngineDetector` with a YOLOX
   `Preprocessor`/`OutputDecoder` adapter pair (ADR-0006/0008). No
   YOLOX-specific code exists above the Detector port.

## Consequences

- The AGPL question is closed without legal spend; the license gate stays
  meaningful (it allows Apache-2.0 and would still refuse an Ultralytics
  bundle).
- YOLOX's official ONNX exports are static-shape (416×416 for tiny), so
  the letterbox preprocessing owns resolution adaptation; dynamic-shape
  support in the runtime remains exercised by tests.
- We adopt YOLOX's preprocessing contract (BGR, 0–255 float, 114-padding
  letterbox, no normalization) — encoded in one adapter class, invisible
  elsewhere.
- Megvii's YOLOX is in maintenance mode; acceptable for a first family
  because the adapter surface is two small classes — successors (RT-DETR,
  D-FINE, our own trained models) plug in the same way.

## Alternatives Considered

- **Ultralytics YOLOv8/11 + commercial license:** rejected for now — a
  negotiated dependency before product revenue, for capability we do not
  yet need; revisit only if YOLO-family successors materially outperform
  on our own benchmarks.
- **RT-DETR / D-FINE (Apache-2.0):** strong candidates, heavier on CPU;
  deferred until Jetson-class hardware benchmarking, where transformer
  detectors become attractive.
- **NanoDet-Plus (Apache-2.0):** lighter but weaker ecosystem and accuracy
  headroom; unnecessary once YOLOX-tiny meets the latency budget.
- **Train from scratch immediately:** rejected — the dataset platform is
  new and empty; pretrained weights de-risk the platform end-to-end first.
