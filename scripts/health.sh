#!/usr/bin/env bash
# Live system health: subsystems, host metrics, FPS and latency.
#
#   ./scripts/health.sh          # human-readable
#   ./scripts/health.sh --json   # raw /health JSON
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_curl; need_python

HEALTH_URL="http://127.0.0.1:${HEALTH_PORT}/health"
METRICS_URL="http://127.0.0.1:${HEALTH_PORT}/metrics"

BODY="$(fetch_json "$HEALTH_URL")" \
    || die "health endpoint unreachable ($HEALTH_URL) — is the box running? Try: ./scripts/start.sh"

if [ "${1:-}" = "--json" ]; then
    echo "$BODY" | python3 -m json.tool
    exit 0
fi

METRICS="$(fetch_json "$METRICS_URL" || echo '{}')"

GREEN="$C_GREEN" RED="$C_RED" YELLOW="$C_YELLOW" RESET="$C_RESET" \
HEALTH_BODY="$BODY" METRICS_BODY="$METRICS" python3 <<'PY'
import json
import os

green, red, yellow, reset = (os.environ[k] for k in ("GREEN", "RED", "YELLOW", "RESET"))
health = json.loads(os.environ["HEALTH_BODY"])
metrics = json.loads(os.environ["METRICS_BODY"] or "{}")

def paint(status):
    color = green if status == "ok" else yellow if status in ("degraded", "warning") else red
    return f"{color}{status.upper()}{reset}"

overall = health.get("status", "unknown")
print(f"  System:        {paint(overall)}   (box v{health.get('version', '?')})")
print()
names = {"cameras": "Camera", "inference": "AI", "tracking": "Tracking",
         "risk": "Risk", "notifications": "Notification"}
components = health.get("components", {})
for key, label in names.items():
    component = components.get(key, {})
    status = component.get("status", "missing") if isinstance(component, dict) else "?"
    extra = ""
    if key == "cameras" and isinstance(component, dict):
        cams = component.get("cameras", {}) or {}
        healthy = sum(1 for value in cams.values() if value == "healthy")
        extra = f"  ({healthy}/{len(cams)} healthy)" if cams else "  (none configured)"
    if key == "notifications" and isinstance(component, dict):
        extra = f"  (delivered {component.get('delivered', 0)}, queue {component.get('queue', 0)})"
    print(f"  {label:<14}{paint(status)}{extra}")

host = health.get("host", {})
def fmt(value, suffix=""):
    return "n/a" if value is None else f"{value}{suffix}"
print()
print(f"  CPU:           {fmt(host.get('cpu_percent'), '%')}")
print(f"  RAM:           {fmt(host.get('memory_percent'), '%')}  ({fmt(host.get('memory_used_mb'), ' MB used')})")
print(f"  Disk:          {fmt(host.get('disk_percent'), '%')}  ({fmt(host.get('disk_free_gb'), ' GB free')})")
print(f"  Temperature:   {fmt(host.get('temperature_c'), '°C')}")
print(f"  FPS:           {fmt(metrics.get('inference_fps'))}")
print(f"  Latency:       tracking {fmt(metrics.get('tracking_latency_ms'), ' ms')}, "
      f"notification delivery {fmt(metrics.get('notification_mean_delivery_ms'), ' ms')}")

warnings = health.get("warnings", {})
if warnings:
    print()
    for source, message in warnings.items():
        print(f"  {yellow}! {source}: {message}{reset}")
PY
