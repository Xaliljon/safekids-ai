# Guardian AI — Operations Scripts

- **Date:** 2026-07-06 (Sprint 15.1)
- **Audience:** developers and pilot operators
- **Platforms:** macOS and Linux

Everything lives in `scripts/`, shares one library (`scripts/lib/common.sh`),
validates its prerequisites, prints colored progress, and fails with a
human-readable message and a non-zero exit code. All scripts respect
`GUARDIAN_HOME` (default `~/guardian`) and never need editing.

The whole platform, one command:

```bash
./guardian          # interactive menu over everything below
./guardian demo     # or non-interactive, straight to the demo
```

`./guardian` (repo root) is the front door: an interactive menu (setup /
demo / health / logs / metrics / backup / restore / stop / clean) with a
dependency overview at launch and a first-run setup offer. Every menu item
maps 1:1 to a script below and is also available as `./guardian <command>`.

## Quick reference

| Script | Purpose |
|---|---|
| `setup.sh` | verify toolchain, install dependencies, create home, fetch model |
| `demo-menu.sh` | interactive demo picker: live AI / incidents / custom video |
| `demo-live.sh` | full demo: RTSP rig + Guardian Edge, Ctrl+C stops everything |
| `demo-incidents.sh` | synthetic-incident box for mobile-app testing (no cameras) |
| `start.sh` / `stop.sh` / `restart.sh` | Guardian Edge lifecycle |
| `health.sh` | subsystem + host health at a glance |
| `diagnose.sh` | full diagnostics, saves and reveals the report |
| `logs.sh` | live-tail any subsystem log |
| `metrics.sh` | performance gauges (`--watch` refreshes) |
| `clean.sh` | remove caches/build artifacts (keeps models + config) |
| `reset.sh` | factory reset (keeps models + backups; asks first) |
| `backup.sh` / `restore.sh` | timestamped config backup / restore latest |
| `update-model.sh` | (re)install the detection model via the Model Zoo |
| `uninstall.sh` | remove Guardian AI, preserving backups |

Environment overrides: `GUARDIAN_HOME`, `RTSP_PORT` (default 18554 —
VM stacks often squat on 8554), `DEMO_VIDEO` (a clip for the demo camera;
default is a synthetic test pattern), `HEALTH_PORT`, `DEVICE_API_PORT`.

---

## setup.sh

Verifies Python ≥ 3.10, uv (installs it if missing), git, ffmpeg, Docker
(warn-only), Flutter (warn-only); syncs the Python workspace; verifies
OpenCV imports; installs git hooks; fetches Dart packages; creates and
validates `GUARDIAN_HOME` (via `guardianctl check`, which also writes
`reports/install-report.json`); downloads YOLOX-tiny if missing.

```bash
./scripts/setup.sh
GUARDIAN_HOME=/data/guardian ./scripts/setup.sh
```

Expected tail: `==> setup complete` with home/model/report paths.
**Recovery:** every failed check names the missing tool and how to install
it; fix and re-run (idempotent).

## demo-menu.sh

The demo picker (`./guardian demo` opens it):

```
 1) Live AI Demo       — full pipeline on a synthetic RTSP camera
 2) Incident Demo      — synthetic fall incidents (mobile-app testing)
 3) Custom Video Demo  — full pipeline on YOUR video file
 4) Exit
```

Non-interactive: `demo-menu.sh live | incidents | video [clip.mp4]`.

## demo-live.sh

The one command. Steps: environment check → Docker → mediamtx (`:18554`) →
demo RTSP stream (synthetic pattern, or `DEMO_VIDEO=clip.mp4` for real
detections) → model check → home validation → demo camera registration
(3 probe attempts — a freshly started stream can stall the first read) →
`guardianctl diagnose` → `guardian-edge` → prints Device API / Health /
Metrics URLs, the pairing code, home and log paths, then waits.
**Ctrl+C stops everything** (box, stream, mediamtx).

```bash
./scripts/demo-live.sh
DEMO_VIDEO=~/clips/people.mp4 ./scripts/demo-live.sh   # = Custom Video Demo
```

**Recovery:** if the stream fails, see `$GUARDIAN_HOME/run/rtsp-publisher.log`;
if the box fails, `$GUARDIAN_HOME/run/guardian-edge.log`; port busy → set
`RTSP_PORT`. For mobile-app testing with a stream of incidents, use
`./scripts/demo-incidents.sh start` instead.

## start.sh / stop.sh / restart.sh

`start.sh` refuses a second instance (pid file **and** a stray-process
sweep), waits until `:8790/health` answers, prints the pairing code.
`stop.sh` gracefully stops the box (SIGTERM, 15 s grace), the demo stream,
mediamtx (only if these scripts started it) and a running incident demo.
`restart.sh` restarts only the box — the camera rig keeps running; paired
phones stay paired.

```bash
./scripts/start.sh && ./scripts/health.sh
./scripts/stop.sh
```

**Recovery:** "already running outside our control (pid N)" → `./scripts/stop.sh`
sweeps it. Startup failure prints the last supervisor log lines.

## health.sh

Camera / AI / Tracking / Risk / Notification status plus CPU, RAM, disk,
temperature, FPS and latency — colored, one screen. `--json` for the raw
payload.

```
  System:        OK   (box v0.2.0)
  Camera        OK  (1/1 healthy)
  ...
  CPU:           27.7%   FPS: 9.2
```

**Recovery:** "health endpoint unreachable" → the box is down; `./scripts/start.sh`.

## diagnose.sh

Runs `guardianctl diagnose` (exercises cameras, AI, tracking,
notifications, device API with synthetic input), saves
`$GUARDIAN_HOME/reports/diagnostics-report.json`, and reveals it in
Finder/file manager when run interactively. `--no-cameras` skips live
probes. Exit code mirrors the diagnosis.

## logs.sh

```bash
./scripts/logs.sh              # interactive menu
./scripts/logs.sh vision       # tail one subsystem
./scripts/logs.sh --list       # what exists, with sizes
```

Subsystems: system, vision, tracking, risk, notifications, device_api,
installer, supervisor (the process log under `run/`). Ctrl+C exits.

## metrics.sh

CPU, RAM, temperature, uptime, inference FPS, tracking latency,
notification delivery latency. Detection/risk latency are labeled `n/a` —
box v0.2 does not export them (FPS covers the detect stage; risk is
in-process sub-ms). `--watch` refreshes every 2 s; `--json` for raw.

## clean.sh

Removes repo caches (`__pycache__`, `.pytest_cache`, `.ruff_cache`,
`.mypy_cache`, `dist`, coverage, `mobile/build`) and Guardian-home
temporaries (rotated log generations, stale pid files). **Keeps** models,
configuration, data, backups, current logs, and `.venv`.

## reset.sh

Factory reset: removes `config/`, `data/` (trusted devices, notification
outbox), `logs/`, `reports/`, `run/`. **Keeps** `models/` and `backups/`.
Stops the box first. Asks for the literal word `RESET` (`--yes` skips, for
automation). Phones must pair again afterwards.

## backup.sh / restore.sh

`backup.sh` → `guardianctl backup` → timestamped
`backups/guardian-backup-YYYYMMDD-HHMMSS.zip` (cameras + trusted devices;
never models/video/logs — ADR-0016). `restore.sh` restores the newest
backup (or a given path) and restarts the box if it is running.

```bash
./scripts/backup.sh
./scripts/restore.sh                          # latest
./scripts/restore.sh backups/guardian-backup-20260706-000354.zip
```

## update-model.sh

Installs/replaces the detection model through the existing Model Zoo
pipeline (manifest, license gate, SHA256, atomic install — ADR-0009),
lists installed models and versions, and reminds you to
`./scripts/restart.sh` if the box is running.

## uninstall.sh

Stops everything, removes the systemd unit on Linux (sudo), moves
`$GUARDIAN_HOME/backups` to `~/guardian-backups`, deletes
`$GUARDIAN_HOME`. The repository is kept. Asks for the literal word
`UNINSTALL` (`--yes` skips).

---

## Exit codes

`0` success · `1` operational failure (message explains) · `2` usage error.
`diagnose.sh` propagates the diagnosis result so it can gate CI/cron.
