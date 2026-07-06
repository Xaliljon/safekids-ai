# scripts/

Developer and operator tooling. Everything here is idempotent, safe to
re-run, works on macOS and Linux, validates its prerequisites, and respects
`GUARDIAN_HOME` (default `~/guardian`). Shared plumbing lives in
`lib/common.sh`. Full documentation with examples and recovery steps:
[docs/operations/SCRIPTS.md](../docs/operations/SCRIPTS.md).

The whole platform, one command: `./scripts/demo.sh`

| Script | Purpose |
|---|---|
| `setup.sh` | verify toolchain, install dependencies, create Guardian home, fetch model |
| `demo.sh` | full demo: RTSP rig + Guardian Edge; Ctrl+C stops everything |
| `demo-box.sh` | synthetic-incident box for mobile-app testing (no cameras) |
| `start.sh` / `stop.sh` / `restart.sh` | Guardian Edge lifecycle (single-instance safe) |
| `health.sh` | subsystem + host health at a glance |
| `diagnose.sh` | full diagnostics, saves and reveals the report |
| `logs.sh` | live-tail any subsystem log (menu or by name) |
| `metrics.sh` | performance gauges; `--watch` refreshes |
| `clean.sh` | remove caches/build artifacts (keeps models + config) |
| `reset.sh` | factory reset (keeps models + backups; asks first) |
| `backup.sh` / `restore.sh` | timestamped config backup / restore |
| `update-model.sh` | (re)install the detection model via the Model Zoo |
| `uninstall.sh` | remove Guardian AI, preserving backups |
| `codegen.sh` | regenerate clients/schemas from `contracts/` |

## Rules

- Scripts orchestrate; they contain no business logic.
- Scripts never require secrets to run in their default mode.
- Scripts never require manual editing — behavior changes via env vars
  (`GUARDIAN_HOME`, `RTSP_PORT`, `DEMO_VIDEO`, …).
- New recurring dev tasks get a script **and** a Makefile target, or neither.
