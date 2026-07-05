# contracts/

Single source of truth for every interface between Guardian AI components.
This directory is what keeps AI, Edge, Backend, Mobile, and Dashboard loosely
coupled: they share schemas, never code.

## Layout

| Path | Contents |
|---|---|
| `openapi/v1/` | Backend REST API specifications (OpenAPI 3.1). Versioned; v1 is never broken, only extended. |
| `events/` | JSON Schemas for cross-component events: `SafetyEvent`, `DeviceHealth`, telemetry. |
| `models/` | AI model manifest schema — name, version, task, input/output spec, evaluation metrics (incl. FP/FN rates per docs/04_AI_ETHICS.md). |

## Rules

- Interface changes start **here**, are reviewed **here**, and only then get implemented.
- Consumers use **generated** code (`scripts/codegen.sh`) — handwritten copies of these schemas are forbidden.
- Backward compatibility is mandatory for published versions (docs/03, API principles). CI will gate breaking changes once specs exist.
- No logic lives here. Schemas only.
