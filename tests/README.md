# tests/

**Cross-component** end-to-end and integration tests only. Component-level
tests live inside their component (`backend/tests`, `edge/tests`, `ai/tests`,
`packages/*/…/tests`, Dart `test/` dirs) so path-filtered CI stays fast.

## What belongs here

- `e2e/` — full-flow scenarios once components exist, e.g.:
  edge emits `SafetyEvent` → backend ingests → notification fan-out → mobile client contract satisfied.
- Contract conformance suites that exercise more than one component against `contracts/` schemas.

## Markers

Cross-component tests use the pytest markers defined in the root `pyproject.toml`:

- `integration` — requires `make stack-up`
- `hardware` — requires a bench Guardian Edge Box (nightly self-hosted job)
