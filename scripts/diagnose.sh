#!/usr/bin/env bash
# Full diagnostics: exercises cameras, AI, tracking, notifications and the
# device API, saves the machine-readable report, and reveals its location.
#
#   ./scripts/diagnose.sh
#   ./scripts/diagnose.sh --no-cameras   # skip live camera probes
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_workspace
[ -d "$GUARDIAN_HOME" ] || die "Guardian home not found: $GUARDIAN_HOME — run ./scripts/setup.sh"

# Demo cameras stream through Docker NAT and need TCP transport.
if grep -qs "127.0.0.1:${RTSP_PORT}" "$GUARDIAN_HOME/config/cameras.yaml" 2>/dev/null; then
    export OPENCV_FFMPEG_CAPTURE_OPTIONS="${OPENCV_FFMPEG_CAPTURE_OPTIONS:-rtsp_transport;tcp}"
fi

say "running guardianctl diagnose"
STATUS=0
guardianctl diagnose "$@" || STATUS=$?

REPORT="$GUARDIAN_HOME/reports/diagnostics-report.json"
if [ -f "$REPORT" ]; then
    echo
    say "report saved"
    note "$REPORT"
    if [ -t 1 ]; then
        if command -v open >/dev/null 2>&1; then open -R "$REPORT" 2>/dev/null || true
        elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$(dirname "$REPORT")" 2>/dev/null || true
        fi
    fi
else
    warn "no report was written — see the errors above"
fi
exit "$STATUS"
