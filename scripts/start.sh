#!/usr/bin/env bash
# Start Guardian Edge (refuses to start a second instance).
#
#   ./scripts/start.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_curl; need_workspace
[ -d "$GUARDIAN_HOME" ] || die "Guardian home not found: $GUARDIAN_HOME — run ./scripts/setup.sh"
model_installed || die "no detection model in $GUARDIAN_HOME/models — run ./scripts/update-model.sh"

if edge_running; then
    say "guardian-edge is already running (pid $(cat "$EDGE_PID"))"
    note "health: http://127.0.0.1:${HEALTH_PORT}/health"
    exit 0
fi

start_edge
CODE="$(pairing_code)"
note "device API: http://$(lan_ip):${DEVICE_API_PORT}   pairing code: ${CODE:-see $LOGS_DIR/device_api.log}"
note "stop with: ./scripts/stop.sh"
