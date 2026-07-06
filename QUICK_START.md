# Guardian AI — Quick Start

From `git clone` to a running platform in **under ten minutes**.

## 1. Clone and launch

```bash
git clone https://github.com/Xaliljon/guardian-ai.git
cd guardian-ai
./guardian
```

That is the whole quick start. `./guardian` opens an interactive menu:

```
 1) Setup      — verify tools, install dependencies, fetch the model
 2) Run Demo   — the whole platform (camera rig + Guardian Edge)
 3) Health     — subsystem + host status at a glance
 4) Logs       — live-tail a subsystem log
 5) Metrics    — performance gauges
 6) Backup     — save cameras + trusted devices
 7) Restore    — bring the latest backup back
 8) Stop       — gracefully stop all Guardian services
 9) Clean      — remove caches and temporary files
10) Exit
```

On first launch it checks your tools (Python 3.10+, uv, git, ffmpeg;
Docker for the demo camera; Flutter only for the mobile app) and offers
to run Setup. Pick **1) Setup** (~2–5 minutes: dependencies + the
YOLOX-tiny model), then **2) Run Demo**.

## 2. What "Run Demo" gives you

A real end-to-end box on your machine: an RTSP test camera (mediamtx in
Docker + ffmpeg stream), the YOLOX detector, tracking, event/risk engines,
notifications and the Device API — then a summary like:

```
==> Guardian AI demo is running

    Guardian:       v0.2.0
    Model:          yolox-tiny 0.1.1-rc0
    Device API:     http://192.168.1.7:8787  (WebSocket :8788)
    Health:         http://127.0.0.1:8790/health
    Metrics:        http://127.0.0.1:8790/metrics
    Pairing code:   821517
    Guardian home:  ~/guardian
    Logs:           ~/guardian/logs

    Press Ctrl+C to stop everything.
```

**Ctrl+C stops everything** — box, stream, Docker container.

## 3. Pair the SafeKids app (optional)

```bash
cd mobile
open -a Simulator && flutter run    # or: flutter run -d <your-iphone>
```

In the app: *Enter manually* → the address and pairing code from the
summary (simulator: `127.0.0.1`; real phone: the LAN address, same Wi-Fi).

Want a stream of demo incidents to click through? Run
`./guardian demo-box` instead of the full demo — it feeds a synthetic
fall scenario through the real engines every ~10 seconds.

## 4. Everyday commands

Every menu item also works directly, scriptable and CI-friendly:

```bash
./guardian demo        # the whole platform
./guardian health      # one-screen status
./guardian logs vision # live-tail a subsystem
./guardian metrics     # gauges (add --watch)
./guardian backup      # timestamped config backup
./guardian stop        # graceful stop, everywhere
./guardian deps        # dependency check only
```

Full script reference with recovery steps: [docs/operations/SCRIPTS.md](docs/operations/SCRIPTS.md).

## Platform notes

| Platform | Notes |
|---|---|
| macOS | works out of the box (Docker Desktop for the demo camera) |
| Ubuntu / Intel N100 | `apt install ffmpeg docker.io`; production installs use `deploy/install.sh` (systemd) |
| NVIDIA Jetson (JetPack 6) | system Python 3.10 is supported; TensorRT backend is on the roadmap — ONNX Runtime runs today |

Real deployments (kindergarten pilot): see [PILOT_GUIDE.md](PILOT_GUIDE.md)
and [deploy/README.md](deploy/README.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker: command not found` / not running | install/start Docker, or skip the demo camera and use `./guardian demo-box` |
| port 8554/18554 busy | `RTSP_PORT=28554 ./guardian demo` |
| demo camera probe fails | the script retries 3×; if it still fails, see `~/guardian/run/rtsp-publisher.log` |
| "already running outside our control" | `./guardian stop` sweeps strays |
| box unreachable from the phone | phone must be on the same Wi-Fi; check `./guardian health` |
| start over completely | `./guardian stop && ./scripts/reset.sh` (models and backups survive) |
