#!/usr/bin/env bash
# Performance metrics: host + pipeline gauges from :8790/metrics.
#
#   ./scripts/metrics.sh          # human-readable
#   ./scripts/metrics.sh --json   # raw JSON
#   ./scripts/metrics.sh --watch  # refresh every 2s (Ctrl+C to exit)
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_curl; need_python
METRICS_URL="http://127.0.0.1:${HEALTH_PORT}/metrics"

show() {
    local body
    body="$(fetch_json "$METRICS_URL")" \
        || die "metrics endpoint unreachable ($METRICS_URL) — is the box running? Try: ./scripts/start.sh"
    if [ "${1:-}" = "--json" ]; then
        echo "$body" | python3 -m json.tool
        return
    fi
    METRICS_BODY="$body" python3 <<'PY'
import json
import os

metrics = json.loads(os.environ["METRICS_BODY"])
def fmt(value, suffix=""):
    return "n/a" if value is None else f"{value}{suffix}"

print(f"  CPU:                  {fmt(metrics.get('cpu_percent'), '%')}")
print(f"  RAM:                  {fmt(metrics.get('memory_percent'), '%')} ({fmt(metrics.get('memory_used_mb'), ' MB')})")
print(f"  Temperature:          {fmt(metrics.get('temperature_c'), '°C')}")
print(f"  Uptime:               {fmt(metrics.get('uptime_seconds'), ' s')}")
print(f"  Inference FPS:        {fmt(metrics.get('inference_fps'))}")
print(f"  Detection latency:    n/a (box v0.2 gauges: FPS covers the detect stage)")
print(f"  Tracking latency:     {fmt(metrics.get('tracking_latency_ms'), ' ms')}")
print(f"  Risk latency:         n/a (in-process, sub-ms; not exported in v0.2)")
print(f"  Notification latency: {fmt(metrics.get('notification_mean_delivery_ms'), ' ms')} (mean to delivered)")
PY
}

if [ "${1:-}" = "--watch" ]; then
    trap 'exit 0' INT
    while true; do
        clear
        say "Guardian metrics ($(date '+%H:%M:%S')) — Ctrl+C to exit"
        show
        sleep 2
    done
fi
show "${1:-}"
