#!/usr/bin/env bash
# Restart Guardian Edge (the demo camera rig, if any, keeps running).
#
#   ./scripts/restart.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_curl; need_workspace

say "restarting guardian-edge"
edge_running && stop_edge || note "guardian-edge was not running"
start_edge
CODE="$(pairing_code)"
note "pairing code: ${CODE:-see $LOGS_DIR/device_api.log} (unchanged devices stay paired)"
