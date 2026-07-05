# scripts/

Development tooling. Everything here is idempotent and safe to re-run.
Prefer `make` targets as the entry point (`make help`).

| Script | Purpose |
|---|---|
| `setup.sh` | One-shot environment setup: installs uv if missing, syncs the Python workspace, installs pre-commit hooks, fetches Dart dependencies. |
| `codegen.sh` | Regenerates clients/schemas from `contracts/` (Dart API client, pydantic event models). No-op until contracts exist; CI fails if committed generated code goes stale. |

## Rules

- Scripts orchestrate; they contain no business logic.
- Scripts never require secrets to run in their default mode.
- New recurring dev tasks get a script **and** a Makefile target, or neither.
