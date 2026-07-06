#!/usr/bin/env bash
# Gracefully stop all Guardian services (box, demo rig, demo-box).
#
#   ./scripts/stop.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

say "stopping Guardian services"
STOPPED=0

if edge_running || [ -n "$(edge_stray_pids)" ]; then
    stop_edge; STOPPED=1
fi
if pid_alive "$PUBLISHER_PID"; then
    stop_publisher; STOPPED=1
fi
if [ -f "$MEDIAMTX_MARKER" ]; then
    stop_mediamtx; STOPPED=1
fi

# demo-box.sh (synthetic-incident box), if it is running
DEMO_BOX_RUN="${DEMO_BOX_DIR:-/tmp/guardian-demo-box}"
if [ -f "$DEMO_BOX_RUN/box.pid" ] && kill -0 "$(cat "$DEMO_BOX_RUN/box.pid")" 2>/dev/null; then
    "$GUARDIAN_REPO/scripts/demo-box.sh" stop; STOPPED=1
fi

if [ "$STOPPED" -eq 0 ]; then
    note "nothing was running"
else
    say "all Guardian services stopped"
fi
