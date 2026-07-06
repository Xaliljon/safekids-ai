#!/usr/bin/env bash
# Demo Guardian Box for mobile-app testing (macOS/Linux) — no cameras.
#
#   ./scripts/demo-incidents.sh start    # box + health surface, prints pairing code
#   ./scripts/demo-incidents.sh status   # is it running, what code
#   ./scripts/demo-incidents.sh stop     # stop everything
#
# What runs:
#   - device_demo: the synthetic fall scenario through the REAL chain
#     (tracking -> events -> risk -> notifications -> Device API :8787/:8788)
#     — the app receives a fresh incident every ~10 seconds.
#   - demo_health: :8790/health and /metrics for the Dashboard/Cameras/
#     Health screens (CPU/RAM/disk are the machine's real numbers).
#
# For the full pipeline with a real RTSP camera, use ./scripts/demo-live.sh.
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

DEMO_BOX_DIR="${DEMO_BOX_DIR:-/tmp/guardian-demo-box}"
BOX_LOG="$DEMO_BOX_DIR/box.log"
BOX_PID="$DEMO_BOX_DIR/box.pid"
HEALTH_LOG="$DEMO_BOX_DIR/health.log"
HEALTH_PID_FILE="$DEMO_BOX_DIR/health.pid"

demo_pairing_code() {
    grep -o 'pairing code: [0-9]*' "$BOX_LOG" 2>/dev/null | tail -1 | grep -o '[0-9]*' || true
}

print_info() {
    local code ip
    code="$(demo_pairing_code)"
    ip="$(lan_ip)"
    echo
    say "demo Guardian Box is running (synthetic incidents)"
    cat <<EOF

    Pairing code:     ${code:-<search $BOX_LOG>}
    Simulator:        address 127.0.0.1, port ${DEVICE_API_PORT}
    Real phone:       address $ip, port ${DEVICE_API_PORT} (same Wi-Fi)
    Health:           http://127.0.0.1:${HEALTH_PORT}/health
    Logs:             $BOX_LOG

    Run the app:
      cd $GUARDIAN_REPO/mobile
      open -a Simulator && flutter run     # simulator
      flutter run -d <iphone-id>           # real iPhone

    In the app: "Enter manually" -> address + code -> Pair.
    Note: the pairing code is SINGLE-USE — for a fresh pairing run
    './scripts/demo-incidents.sh stop && ./scripts/demo-incidents.sh start'
    (already-paired phones keep working across restarts).
EOF
}

case "${1:-start}" in
start)
    need_uv; need_curl; need_workspace
    if pid_alive "$BOX_PID"; then
        warn "already running"
        print_info
        exit 0
    fi
    rm -rf "$DEMO_BOX_DIR"
    mkdir -p "$DEMO_BOX_DIR"

    say "starting device_demo (Device API :${DEVICE_API_PORT}/:${DEVICE_WS_PORT})"
    (
        cd "$GUARDIAN_REPO"
        nohup uv run python -m guardian_edge.tools.device_demo \
            --data-dir "$DEMO_BOX_DIR/data" > "$BOX_LOG" 2>&1 &
        echo $! > "$BOX_PID"
    )

    say "starting demo health surface (:${HEALTH_PORT})"
    (
        cd "$GUARDIAN_REPO"
        nohup uv run python -m guardian_edge.tools.demo_health > "$HEALTH_LOG" 2>&1 &
        echo $! > "$HEALTH_PID_FILE"
    )

    WAITED=0
    while [ "$WAITED" -lt 30 ] && [ -z "$(demo_pairing_code)" ]; do
        pid_alive "$BOX_PID" || { tail -5 "$BOX_LOG" >&2 || true; die "device_demo exited — see $BOX_LOG"; }
        sleep 1; WAITED=$((WAITED + 1))
    done
    [ -n "$(demo_pairing_code)" ] || die "no pairing code appeared — see $BOX_LOG"
    curl -sf "http://127.0.0.1:${HEALTH_PORT}/health" >/dev/null \
        || die "health surface :${HEALTH_PORT} not answering — see $HEALTH_LOG"
    print_info
    ;;
status)
    if pid_alive "$BOX_PID"; then
        print_info
    else
        say "not running (start with: ./scripts/demo-incidents.sh start)"
    fi
    ;;
stop)
    STOPPED=0
    pid_alive "$BOX_PID" && { stop_pid "$BOX_PID" "device_demo" 5; STOPPED=1; }
    pid_alive "$HEALTH_PID_FILE" && { stop_pid "$HEALTH_PID_FILE" "demo health surface" 5; STOPPED=1; }
    # device_demo runs through the uv wrapper; sweep its python child too.
    STRAYS="$(pgrep -f 'guardian_edge.tools.device_demo\|guardian_edge.tools.demo_health' 2>/dev/null || true)"
    if [ -n "$STRAYS" ]; then
        kill $STRAYS 2>/dev/null || true
        STOPPED=1
    fi
    [ "$STOPPED" -eq 1 ] && say "demo box stopped" || note "nothing was running"
    ;;
*)
    echo "usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
