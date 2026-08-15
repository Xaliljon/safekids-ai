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
| [ADR-0005](ADR-0005-dataset-governance.md) | Dataset Governance (minors, consent, withdrawal) | **Proposed** |
| [ADR-0006](ADR-0006-vision-pipeline.md) | Vision Pipeline Architecture | Accepted |
| [ADR-0007](ADR-0007-detection-identity.md) | Detection Identity and Correlation | Accepted |
| [ADR-0008](ADR-0008-inference-runtime.md) | Inference Runtime Contracts | Accepted |
| [ADR-0009](ADR-0009-model-management.md) | Model Management and OTA Layout | Accepted |
| [ADR-0010](ADR-0010-dataset-platform.md) | Dataset Platform | Accepted |
| [ADR-0011](ADR-0011-multi-object-tracking.md) | Multi-Object Tracking (ByteTrack) | Accepted |
| [ADR-0012](ADR-0012-event-engine.md) | Event Engine (Candidate Safety Events) | Accepted |
| [ADR-0013](ADR-0013-risk-engine.md) | Risk Engine (Safety Incidents) | Accepted |
| [ADR-0014](ADR-0014-notification-architecture.md) | Notification Architecture (Local-First) | Accepted |
| [ADR-0015](ADR-0015-device-api-and-mobile.md) | Device API and Mobile Integration | Accepted |
| [ADR-0016](ADR-0016-operational-readiness.md) | Operational Readiness (Pilot Deployment) | Accepted |
| [ADR-0017](ADR-0017-evidence-management.md) | Evidence Management (Incident Clips) | Accepted |
| [ADR-0018](ADR-0018-safe-area-zones.md) | Safe-Area Zones and Zone-Exit Candidates | Accepted |
| [ADR-0019](ADR-0019-evidence-storage-bounds.md) | Evidence Storage Bounds (extends ADR-0017) | **Proposed** |
| [ADR-0020](ADR-0020-promotion-latency-gate.md) | What the Promotion Latency Gate Compares | **Proposed** |
