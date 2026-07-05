# docker/

Container infrastructure for local development.

## Files

| File | Purpose |
|---|---|
| `compose.yaml` | Local backing services: PostgreSQL 16, Redis 7, RabbitMQ 3 (+ management UI on `:15672`). Backend service joins under the `app` profile once it has an entrypoint. |
| `.env.example` | Template for local credentials. Copy to `.env`; never commit `.env`. |

Application images live **next to their component** (`backend/Dockerfile`,
`edge/Dockerfile`) so path-filtered CI rebuilds only what changed.

## Usage

```sh
make stack-up     # start services, wait for health
make stack-logs   # tail logs
make stack-down   # stop (data volumes preserved)
```

## Notes

- Ports bind to `127.0.0.1` only — nothing is exposed to the LAN.
- Default credentials are dev-only placeholders; real environments configure everything via environment (docs/03, configuration rules).
- The edge image builds for `linux/arm64` (Jetson, L4T base via `BASE_IMAGE` build-arg) and `linux/amd64` (N100) from the same Dockerfile.
