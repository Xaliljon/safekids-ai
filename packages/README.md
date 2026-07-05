# packages/

Internal shared libraries. Nothing here is published externally, and nothing
here may depend on any application (`mobile/`, `dashboard/`, `backend/`,
`edge/`, `ai/`) — dependencies flow from apps **into** packages, never back.

## Dart (`dart/`)

| Package | Responsibility |
|---|---|
| `guardian_core` | Shared domain entities and value objects. Pure Dart — no Flutter, no I/O. |
| `guardian_api_client` | Backend API client, **generated** from `contracts/openapi` (`scripts/codegen.sh`). Never handwritten. |
| `guardian_ui` | Design system: widgets, theme, tokens shared by mobile + dashboard. |

## Python (`python/`)

| Package | Responsibility |
|---|---|
| `guardian_common` | Event schemas generated from `contracts/events`, logging, configuration helpers. Used by `ai`, `edge`, `backend`. |

## Rule of promotion

Code enters a shared package only when a second app genuinely needs it —
promotion is a deliberate PR, not a copy-paste. Speculative sharing is
unnecessary abstraction (docs/03 §1).
