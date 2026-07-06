#!/usr/bin/env bash
# Guardian AI — shared library for the operations scripts (macOS + Linux).
#
# Every script sources this file. It provides colors, logging, prerequisite
# checks, the GUARDIAN_HOME layout, process management for the supervisor
# and the demo camera rig, and small HTTP/JSON helpers.
#
# Conventions:
#   - GUARDIAN_HOME overrides the box home (default: ~/guardian).
#   - Runtime state (pids, service logs) lives in $GUARDIAN_HOME/run.
#   - Functions either succeed or `die` with a human-readable message.

set -euo pipefail

# ----------------------------------------------------------------- paths ----

# Repository root, regardless of where the script is invoked from.
GUARDIAN_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARDIAN_HOME="${GUARDIAN_HOME:-$HOME/guardian}"
export GUARDIAN_HOME  # guardianctl/guardian-edge subprocesses must see it
RUN_DIR="$GUARDIAN_HOME/run"
LOGS_DIR="$GUARDIAN_HOME/logs"

# Service ports (ADR-0015/0016). RTSP_PORT is host-side for the demo rig;
# 18554 by default because VM stacks (qemu/colima) often squat on 8554.
DEVICE_API_PORT="${DEVICE_API_PORT:-8787}"
DEVICE_WS_PORT="${DEVICE_WS_PORT:-8788}"
HEALTH_PORT="${HEALTH_PORT:-8790}"
RTSP_PORT="${RTSP_PORT:-18554}"

MEDIAMTX_CONTAINER="guardian-mediamtx"
DEMO_CAMERA_ID="demo-classroom"
DEMO_RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${DEMO_CAMERA_ID}"

EDGE_PID="$RUN_DIR/guardian-edge.pid"
EDGE_LOG="$RUN_DIR/guardian-edge.log"
PUBLISHER_PID="$RUN_DIR/rtsp-publisher.pid"
PUBLISHER_LOG="$RUN_DIR/rtsp-publisher.log"
MEDIAMTX_MARKER="$RUN_DIR/mediamtx.started-by-us"

# ---------------------------------------------------------------- output ----

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'
    C_YELLOW=$'\033[1;33m'; C_BLUE=$'\033[1;34m'; C_DIM=$'\033[2m'
else
    C_RESET=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_BLUE=''; C_DIM=''
fi

say()  { printf '%s==>%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
note() { printf '    %s\n' "$*"; }
ok()   { printf '    %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '    %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
err()  { printf '%sERROR:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
die()  { err "$*"; exit 1; }

# --------------------------------------------------------- prerequisites ----

# need_cmd <command> <how to install / why it is needed>
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' not found. $2"
}

need_uv()     { need_cmd uv "Install: curl -LsSf https://astral.sh/uv/install.sh | sh (or run ./scripts/setup.sh)"; }
need_curl()   { need_cmd curl "Install curl via your package manager."; }
need_ffmpeg() { need_cmd ffmpeg "Install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)."; }
need_python() { need_cmd python3 "Install Python 3.10+ (https://www.python.org)."; }

need_docker() {
    need_cmd docker "Install Docker Desktop (macOS) or docker-ce (Linux) — the demo RTSP server runs in Docker."
    docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker and retry."
}

need_workspace() {
    [ -f "$GUARDIAN_REPO/pyproject.toml" ] || die "not a Guardian repo: $GUARDIAN_REPO"
    [ -d "$GUARDIAN_REPO/.venv" ] || die "Python workspace not synced. Run: ./scripts/setup.sh"
}

guardianctl() { (cd "$GUARDIAN_REPO" && uv run guardianctl "$@"); }

# ------------------------------------------------------------- processes ----

# pid_alive <pid-file>
pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

# stop_pid <pid-file> <name> [grace-seconds]
stop_pid() {
    local pid_file="$1" name="$2" grace="${3:-10}"
    if ! pid_alive "$pid_file"; then
        rm -f "$pid_file"
        return 0
    fi
    local pid; pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null || true
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$grace" ]; do
        sleep 1; waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        warn "$name did not stop in ${grace}s; killing"
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    ok "$name stopped"
}

edge_running() { pid_alive "$EDGE_PID"; }

# The daemon runs the venv entrypoint DIRECTLY (never `uv run`): the uv
# wrapper is a separate process, and killing it can orphan the real box.
EDGE_BIN="$GUARDIAN_REPO/.venv/bin/guardian-edge"

# Any guardian-edge process from this repo, pid-file-tracked or stray.
edge_stray_pids() { pgrep -f "$EDGE_BIN" 2>/dev/null || true; }

start_edge() {
    mkdir -p "$RUN_DIR"
    [ -x "$EDGE_BIN" ] || die "guardian-edge entrypoint missing ($EDGE_BIN) — run ./scripts/setup.sh"
    if edge_running; then
        warn "guardian-edge is already running (pid $(cat "$EDGE_PID")) — not starting another instance"
        return 0
    fi
    local strays; strays="$(edge_stray_pids)"
    [ -z "$strays" ] || die "a guardian-edge process is already running outside our control (pid $strays) — stop it with ./scripts/stop.sh"
    # The demo camera streams through Docker NAT; OpenCV must read over TCP.
    if [ -z "${OPENCV_FFMPEG_CAPTURE_OPTIONS:-}" ] \
        && grep -qs "127.0.0.1:${RTSP_PORT}" "$GUARDIAN_HOME/config/cameras.yaml" 2>/dev/null; then
        export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"
    fi
    say "starting guardian-edge (home: $GUARDIAN_HOME)"
    (
        cd "$GUARDIAN_REPO"
        # NOTE: `&` must background ONLY the daemon — chaining with && would
        # background the whole chain and leave a shell as the daemon's parent.
        nohup "$EDGE_BIN" > "$EDGE_LOG" 2>&1 &
        echo $! > "$EDGE_PID"
    )
    local waited=0
    while [ "$waited" -lt 30 ]; do
        if curl -sf "http://127.0.0.1:${HEALTH_PORT}/health" >/dev/null 2>&1; then
            ok "guardian-edge is up (health :${HEALTH_PORT} answering)"
            return 0
        fi
        edge_running || { tail -5 "$EDGE_LOG" >&2 || true; die "guardian-edge exited during startup — see $EDGE_LOG"; }
        sleep 1; waited=$((waited + 1))
    done
    die "guardian-edge did not become healthy in 30s — see $EDGE_LOG"
}

stop_edge() {
    stop_pid "$EDGE_PID" "guardian-edge" 15
    # Sweep strays (e.g. a box started manually or by an older script).
    local strays; strays="$(edge_stray_pids)"
    if [ -n "$strays" ]; then
        warn "stopping stray guardian-edge process(es): $strays"
        kill $strays 2>/dev/null || true
        sleep 2
        for pid in $strays; do
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        done
    fi
}

# The last pairing code the box logged (a new one is minted after each pair).
pairing_code() {
    { grep -h -o 'pairing code: [0-9]\{4,8\}' \
        "$LOGS_DIR/device_api.log" "$EDGE_LOG" 2>/dev/null || true; } \
        | tail -1 | grep -o '[0-9]\{4,8\}' || true
}

lan_ip() {
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null \
        || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1"
}

# --------------------------------------------------------------- demo rig ----

mediamtx_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$MEDIAMTX_CONTAINER"
}

start_mediamtx() {
    mkdir -p "$RUN_DIR"
    if mediamtx_running; then
        ok "mediamtx already running (:${RTSP_PORT})"
        return 0
    fi
    say "starting mediamtx RTSP server (:${RTSP_PORT})"
    docker rm -f "$MEDIAMTX_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$MEDIAMTX_CONTAINER" -p "${RTSP_PORT}:8554" \
        bluenviron/mediamtx >/dev/null \
        || die "could not start mediamtx (is port ${RTSP_PORT} free? override with RTSP_PORT=...)"
    touch "$MEDIAMTX_MARKER"
    sleep 2
    ok "mediamtx up"
}

stop_mediamtx() {
    if [ -f "$MEDIAMTX_MARKER" ] && mediamtx_running; then
        docker rm -f "$MEDIAMTX_CONTAINER" >/dev/null 2>&1 || true
        rm -f "$MEDIAMTX_MARKER"
        ok "mediamtx stopped"
    fi
}

start_publisher() {
    mkdir -p "$RUN_DIR"
    if pid_alive "$PUBLISHER_PID"; then
        ok "demo RTSP stream already publishing ($DEMO_RTSP_URL)"
        return 0
    fi
    say "starting demo RTSP stream ($DEMO_RTSP_URL)"
    if [ -n "${DEMO_VIDEO:-}" ]; then
        [ -f "$DEMO_VIDEO" ] || die "DEMO_VIDEO does not exist: $DEMO_VIDEO"
        nohup ffmpeg -re -stream_loop -1 -i "$DEMO_VIDEO" \
            -c:v libx264 -preset ultrafast -tune zerolatency \
            -f rtsp -rtsp_transport tcp "$DEMO_RTSP_URL" \
            > "$PUBLISHER_LOG" 2>&1 & echo $! > "$PUBLISHER_PID"
    else
        # Synthetic pattern: exercises capture/inference end to end without
        # any video file. Point DEMO_VIDEO at a people clip for detections.
        nohup ffmpeg -re -f lavfi -i "testsrc2=size=768x576:rate=10" \
            -c:v libx264 -preset ultrafast -tune zerolatency \
            -f rtsp -rtsp_transport tcp "$DEMO_RTSP_URL" \
            > "$PUBLISHER_LOG" 2>&1 & echo $! > "$PUBLISHER_PID"
    fi
    local waited=0
    while [ "$waited" -lt 15 ]; do
        if ffprobe -v error -rtsp_transport tcp -select_streams v \
            -show_entries stream=codec_name -of csv=p=0 "$DEMO_RTSP_URL" >/dev/null 2>&1; then
            ok "demo stream is live"
            return 0
        fi
        pid_alive "$PUBLISHER_PID" || { tail -5 "$PUBLISHER_LOG" >&2 || true; die "publisher exited — see $PUBLISHER_LOG"; }
        sleep 1; waited=$((waited + 1))
    done
    die "demo stream did not come up in 15s — see $PUBLISHER_LOG"
}

stop_publisher() {
    pid_alive "$PUBLISHER_PID" && stop_pid "$PUBLISHER_PID" "demo RTSP stream" 5 || rm -f "$PUBLISHER_PID"
}

# ------------------------------------------------------------- http/json ----

# fetch_json <url> — prints body or fails silently (caller decides message).
fetch_json() { curl -sf --max-time 5 "$1"; }

# json_get <python-expression over d> — reads JSON from stdin.
json_get() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

model_installed() { [ -d "$GUARDIAN_HOME/models/yolox-tiny" ]; }

# -------------------------------------------------------------- versions ----

guardian_version() {
    grep -o '__version__ = "[^"]*"' "$GUARDIAN_REPO/edge/guardian_edge/__init__.py" 2>/dev/null \
        | cut -d'"' -f2 || echo "?"
}

model_version() {
    find "$GUARDIAN_HOME/models/yolox-tiny" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
        -exec basename {} \; | sort | tail -1 || true
}
