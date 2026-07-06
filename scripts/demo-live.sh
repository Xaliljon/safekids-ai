#!/usr/bin/env bash
# Guardian AI — the whole platform with one command.
#
#   ./scripts/demo-live.sh            # rig + box, Ctrl+C stops everything
#   DEMO_VIDEO=people.mp4 ./scripts/demo-live.sh   # use a real clip (detections!)
#
# What runs: mediamtx (Docker) <- ffmpeg demo stream, then the real
# guardian-edge supervisor (cameras -> detection -> tracking -> risk ->
# notifications -> Device API + health). For synthetic fall incidents to
# test the mobile app, see ./scripts/demo-incidents.sh instead.
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# 1 ------------------------------------------------------ environment ----
say "checking environment"
need_uv; need_curl; need_ffmpeg; need_python; need_workspace
ok "toolchain present"

# 2/3 ------------------------------------------------- docker + mediamtx ----
need_docker
start_mediamtx

# 4 ------------------------------------------------------- demo stream ----
start_publisher

# 5 -------------------------------------------------------------- model ----
if model_installed; then
    ok "detection model present (yolox-tiny)"
else
    say "installing detection model (YOLOX-tiny)"
    (cd "$GUARDIAN_REPO" && uv run python -m guardian_edge.tools.install_yolox \
        --dest "$GUARDIAN_HOME/models") || die "model install failed — run ./scripts/setup.sh"
fi

# 6/7 ------------------------------------------- guardian home + check ----
say "validating Guardian home"
guardianctl check >/dev/null || die "environment validation failed — run: uv run guardianctl check"
ok "environment valid ($GUARDIAN_HOME)"

if ! grep -qs "id: ${DEMO_CAMERA_ID}" "$GUARDIAN_HOME/config/cameras.yaml" 2>/dev/null; then
    say "registering demo camera"
    REGISTERED=0
    for attempt in 1 2 3; do
        # A freshly started stream can stall the first OpenCV read; retry.
        if OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp" guardianctl add-camera \
            --id "$DEMO_CAMERA_ID" --name "Demo classroom" --location "Demo" \
            --url "$DEMO_RTSP_URL"; then
            REGISTERED=1; break
        fi
        warn "camera probe attempt $attempt failed; retrying"
        sleep 3
    done
    [ "$REGISTERED" -eq 1 ] || die "demo camera registration failed after 3 attempts — see $PUBLISHER_LOG"
fi

# 8 ---------------------------------------------------------- diagnose ----
say "running diagnostics"
if OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp" guardianctl diagnose; then
    ok "all diagnostics passed"
else
    warn "diagnose reported problems — the device API check passes once the box starts below"
fi

# 9 ------------------------------------------------------------- start ----
start_edge

# 10 ------------------------------------------------------------- info ----
CODE="$(pairing_code)"
IP="$(lan_ip)"
echo
say "Guardian AI demo is running"
cat <<EOF

    Guardian:       v$(guardian_version)
    Model:          yolox-tiny $(model_version)
    Device API:     http://${IP}:${DEVICE_API_PORT}  (WebSocket :${DEVICE_WS_PORT})
    Health:         http://127.0.0.1:${HEALTH_PORT}/health
    Metrics:        http://127.0.0.1:${HEALTH_PORT}/metrics
    Pairing code:   ${CODE:-check $LOGS_DIR/device_api.log}
    Guardian home:  $GUARDIAN_HOME
    Logs:           $LOGS_DIR

    Pair the SafeKids app: address ${IP} (phone) or 127.0.0.1 (simulator),
    port ${DEVICE_API_PORT}, code above.

    ${C_YELLOW}Press Ctrl+C to stop everything.${C_RESET}
EOF

cleanup() {
    echo
    say "stopping demo"
    stop_edge
    stop_publisher
    stop_mediamtx
    say "demo stopped"
    exit 0
}
trap cleanup INT TERM

while edge_running; do
    sleep 2
done
err "guardian-edge exited unexpectedly — see $EDGE_LOG"
stop_publisher
stop_mediamtx
exit 1
