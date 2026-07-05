# backend/

Guardian AI cloud/on-prem services (Python, FastAPI): multi-site aggregation,
authentication (JWT), user & device management, notification fan-out, event
history. PostgreSQL + Redis + RabbitMQ (see `docker/compose.yaml` for local dev).

## Clean Architecture layout

| Layer | Path | Responsibility |
|---|---|---|
| Domain | `app/domain/` | Entities and business rules — zero framework imports. |
| Application | `app/application/` | Use cases and ports (interfaces). |
| Infrastructure | `app/infrastructure/` | PostgreSQL, Redis, RabbitMQ, push-notification adapters implementing the ports. |
| Presentation | `app/api/` | Versioned REST routers, auth middleware. Thin — no business logic. |
| — | `migrations/` | Alembic migrations (initialized with the first model; production DBs are never edited manually). |

## Boundary rules

- **Never receives or stores raw video streams.** Metadata and human-approved short evidence clips only — the privacy architecture depends on this.
- The edge must keep working when this backend is unreachable; nothing here may become a hard dependency of on-device safety detection.
- Public API changes go through `contracts/openapi` first; v1 is never broken, only extended.
- Business logic never lives in routers (docs/03, separation of concerns).
