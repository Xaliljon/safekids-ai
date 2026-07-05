# ADR-0016: Operational Readiness

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** Founder, Lead Software Architect

## Context

Sprints 1–13 built the engines; Sprint 14 must put them in a kindergarten.
The deliverable is not a feature — it is a box that installs, monitors,
diagnoses and recovers **without a developer on site**. The platform
architecture is frozen: Camera Service, Vision Pipeline, Inference Runtime,
Detector, Tracker, Event Engine, Risk Engine, Notification Engine, and
Device API must not change. Everything operational has to attach from the
outside, and it has to be simple enough for a kindergarten director's IT
helper to run.

## Decision

1. **One ops layer, pure composition** (`guardian_edge/ops/`). Health,
   diagnostics, watchdog, backup, probing — all of it observes and drives
   the frozen engines exclusively through their existing public APIs
   (status methods, start/stop, consumer seams). No engine knows the ops
   layer exists; deleting `ops/` returns exactly the Sprint 13 system.

2. **One home directory** (`$GUARDIAN_HOME`, default `~/guardian`):
   `config/` (cameras), `models/`, `data/` (outbox, trusted devices),
   `logs/`, `backups/`, `reports/`. Everything a box owns lives under one
   root — backup, diagnostics, and disk monitoring all reason about the
   same tree, and re-imaging a box is "restore one directory".

3. **One production entrypoint** (`guardian_edge/main.py`, installed as
   `guardian-edge`). Until now every sprint ran demos from tools; the box
   now has a supervisor that wires cameras → detection → tracking →
   events → risk → notifications → device API, then attaches health
   server, performance monitor, and watchdog. Composition lives in
   `build_runtime()` — testable as a function, runnable as a service.

4. **One operator command** (`guardianctl`). check / wizard / add-camera /
   test-camera / diagnose / health / metrics / backup / restore / version.
   Human-readable on the terminal, machine-readable on disk
   (`reports/*.json`) — the same run serves the operator on site and the
   engineer reading an emailed report.

5. **Layered recovery, each layer simple.**
   - *In-process:* a `ServiceWatchdog` polls supervised services
     (`is_healthy`/`restart` callables) every 5s and restarts the dead
     ones. It never gives up; a crash loop (>3 restarts/5min) raises a
     health warning while retrying — degraded operation beats no
     operation on a safety device.
   - *Process-level:* systemd (`deploy/guardian-edge.service`,
     `Restart=always`) resurrects the whole runtime.
   - *Camera-level:* already existed (Sprint 2 reconnect backoff);
     the ops layer only surfaces it in `/health`.

6. **Health and metrics are LAN-plaintext JSON** (`:8790/health`,
   `/metrics`) served by stdlib `ThreadingHTTPServer` — same transport
   decision and same accepted TLS gap as the Device API (ADR-0015).
   Component status comes from provider callables the supervisor
   registers; the collector never imports engine internals.

7. **Structured logs per subsystem, rotation by construction.**
   JSON-lines via a logger-namespace → file map (vision, tracking, risk,
   notifications, device_api, installer, everything → system.log), size-
   rotated (5 MB × 3). A full disk on a safety device is an outage, so
   unbounded logs are impossible, not discouraged. Log records carry
   metadata only — the payloads themselves are image-free by ADR-0014.

8. **Backup is an allowlist, not a dump**: `config/cameras.yaml` +
   `data/trusted_devices.json`, zipped with a manifest. Models reinstall
   from the zoo, logs are ephemeral, video/images never exist on disk —
   exclusion is enforced by construction, and restore extracts only
   allowlisted paths (a hostile archive cannot escape).

9. **Install is one idempotent script** (`deploy/install.sh`): toolchain →
   dependencies → environment validation (refuses to proceed on failure,
   writes `reports/install-report.json`) → model → systemd unit. Releases
   are git tags plus `make release` artifacts (wheel, build-info.json,
   requirements-lock.txt); rollback is checkout + reinstall + restore.

## Consequences

- The box runs unattended: crashes restart, cameras reconnect, problems
  surface in `/health` and `guardianctl diagnose` with operator-actionable
  recommendations instead of stack traces.
- Frozen engines stayed frozen — the sprint's entire diff is additive
  (`ops/`, `main.py`, `cli.py`, `deploy/`, tests, docs).
- 24-hour stability is verified by accelerated simulation (17,280
  supervision cycles against a fake clock, real camera-disconnect and
  notification-backlog runs at compressed duration); the pilot itself is
  the wall-clock soak.
- Accepted pilot limitations: plaintext LAN health endpoint (trusted
  network, same as ADR-0015), single heuristic fall model with mandatory
  human review, watchdog probes are liveness- not correctness-checks.
- Next hardening candidates (post-review): TLS on LAN surfaces, remote
  log shipping opt-in, disk-pressure driven log purging, watchdog probes
  that assert end-to-end frame flow rather than thread liveness.
