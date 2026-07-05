# adr/

Architecture Decision Records — the memory of *why* the system is shaped the
way it is (docs/03 §9: documentation explains decisions).

## Process

1. Copy `TEMPLATE.md` to `ADR-NNNN-short-title.md` (next free number).
2. Open a PR; the decision is discussed **before** implementation.
3. Status flows: `Proposed → Accepted` (or `Superseded by ADR-XXXX` later). ADRs are never deleted or rewritten — supersede them.

## When an ADR is required

- Any decision with multi-year consequences (technology, boundary, data, security)
- Anything that changes a rule in ADR-0001
- Anything a future engineer would ask "why on earth…?" about

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001-monorepo-architecture.md) | Monorepo Architecture | Accepted |
| ADR-0002 | Dashboard technology (folded into ADR-0001 §8) | — |
| [ADR-0003](ADR-0003-detector-licensing.md) | Object Detector Selection and Licensing (YOLOX, Apache-2.0) | Accepted |
| ADR-0004 | Edge/cloud responsibility split | Planned |
| ADR-0005 | Dataset governance | **Needed before first data collection** |
| [ADR-0006](ADR-0006-vision-pipeline.md) | Vision Pipeline Architecture | Accepted |
| [ADR-0007](ADR-0007-detection-identity.md) | Detection Identity and Correlation | Accepted |
| [ADR-0008](ADR-0008-inference-runtime.md) | Inference Runtime Contracts | Accepted |
| [ADR-0009](ADR-0009-model-management.md) | Model Management and OTA Layout | Accepted |
| [ADR-0010](ADR-0010-dataset-platform.md) | Dataset Platform | Accepted |
| [ADR-0011](ADR-0011-multi-object-tracking.md) | Multi-Object Tracking (ByteTrack) | Accepted |
| [ADR-0012](ADR-0012-event-engine.md) | Event Engine (Candidate Safety Events) | Accepted |
