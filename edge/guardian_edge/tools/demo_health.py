"""Demo health surface for mobile-app testing (:8790).

device_demo has no cameras, so this sidecar serves the health surface the
SafeKids app polls — using the genuine ops classes (SystemHealthCollector,
HealthServer, PerformanceMonitor). Host metrics (CPU/RAM/disk) are the
real machine's psutil numbers; cameras and pipeline gauges are scripted.

Usage:
    uv run python -m guardian_edge.tools.demo_health [--port 8790]
"""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from guardian_edge.ops.monitoring import (
    DEFAULT_HEALTH_PORT,
    HealthServer,
    PerformanceMonitor,
    SystemHealthCollector,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_HEALTH_PORT)
    args = parser.parse_args(argv)

    collector = SystemHealthCollector(
        providers={
            "cameras": lambda: {
                "status": "ok",
                "cameras": {"classroom-1": "healthy", "playground": "healthy"},
                "fps": {"classroom-1": 6.1, "playground": 5.8},
            },
            "inference": lambda: {
                "status": "ok",
                "cameras": {
                    "classroom-1": {
                        "fps": 6.1,
                        "processed": 18423,
                        "dropped": 12,
                        "detector_errors": 0,
                        "tracker_errors": 0,
                    },
                    "playground": {
                        "fps": 5.8,
                        "processed": 17651,
                        "dropped": 8,
                        "detector_errors": 0,
                        "tracker_errors": 0,
                    },
                },
            },
            "tracking": lambda: {"status": "ok", "last_latency_ms": 0.4},
            "risk": lambda: {"status": "ok", "open_incidents": 1},
            "notifications": lambda: {"status": "ok", "delivered": 27, "queue": 0},
        },
        disk_path=Path("/"),
        version="0.2.0",
    )
    monitor = PerformanceMonitor(
        gauges={
            "inference_fps": lambda: 11.9,
            "tracking_latency_ms": lambda: 0.4,
            "notification_mean_delivery_ms": lambda: 14.0,
        },
        disk_path=Path("/"),
    )
    server = HealthServer(collector, monitor.latest, port=args.port)
    server.start()
    monitor.start()
    print(f"demo health surface on :{server.port} (/health, /metrics)", flush=True)  # noqa: T201

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    server.stop()
    monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
