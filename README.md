# Guardian AI

Privacy-preserving Edge AI platform for child safety.
First product: **SafeKids** — an AI early-warning system for kindergartens,
running on the **Guardian Edge Box** (NVIDIA Jetson / Intel N100).

> We do not build surveillance systems. We build early warning systems.
> AI detects potential safety events; humans review and decide. Video stays
> on the customer's premises. — [Project Charter](docs/00_PROJECT_CHARTER.md)

## Repository map

| Directory | Purpose |
|---|---|
| [`docs/`](docs/) | Governing documents: charter, vision, values, engineering principles, AI ethics. **Read these first** (CLAUDE.md read order). |
| [`adr/`](adr/) | Architecture Decision Records. Start with [ADR-0001](adr/ADR-0001-monorepo-architecture.md). |
| [`architecture/`](architecture/) | System diagrams (C4, data flow, alert pipeline). |
| [`contracts/`](contracts/) | Single source of truth for all interfaces: OpenAPI, event schemas, model manifests. |
| [`ai/`](ai/) | Model development: datasets code, training, evaluation, export (PyTorch → ONNX). |
| [`edge/`](edge/) | Guardian Edge Box runtime: camera ingest, local inference, risk engine. Offline-capable. |
| [`backend/`](backend/) | FastAPI services: aggregation, auth, notification fan-out. Never touches raw video. |
| [`mobile/`](mobile/) | SafeKids Flutter app — director alert review flow. |
| [`dashboard/`](dashboard/) | Flutter Web dashboard — multi-branch overview, device health. |
| [`packages/`](packages/) | Shared internal libraries (Dart: core/api_client/ui; Python: guardian_common). |
| [`hardware/`](hardware/) · [`firmware/`](firmware/) | Edge Box physical design; OS image, provisioning, OTA. |
| [`datasets/`](datasets/) · [`research/`](research/) | DVC pointers (raw data never in git); experiments. |
| [`docker/`](docker/) · [`scripts/`](scripts/) · [`tests/`](tests/) | Local dev stack; tooling; cross-component E2E tests. |

## Quick start

```sh
make setup       # install toolchain, sync workspaces, install git hooks
make lint        # ruff + mypy + dart analyze, everything
make test        # all Python and Dart tests
make stack-up    # local PostgreSQL / Redis / RabbitMQ
make help        # everything else
```

Requirements: [uv](https://docs.astral.sh/uv/) (installed by `make setup`),
Flutter ≥ 3.22, Docker.

## How development works

1. **Documentation first** — features start in `docs/`, decisions in `adr/`.
2. **Contracts second** — interface changes are reviewed in `contracts/` before implementation.
3. **Then code**, inside one component, with tests, on a `feature/*` branch off `develop`.
4. PRs answer: *Why necessary? What problem? Respects principles? Could it be simpler?*

Branch model: `main ← develop ← feature/*` — never commit to `main` directly.
Commits: [Conventional Commits](https://www.conventionalcommits.org) with component scope, e.g. `feat(edge): …`.

## Status

Engineering foundation only — no application logic, AI models, or APIs yet.
Current phase: completing product discovery docs (`15–20`) and foundational ADRs
(detector licensing, dataset governance) before feature work begins.
