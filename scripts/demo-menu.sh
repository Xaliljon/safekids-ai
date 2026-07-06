#!/usr/bin/env bash
# Guardian AI — pick your demo. One menu, no confusion.
#
#   ./scripts/demo-menu.sh          # interactive
#   ./scripts/demo-menu.sh live     # or jump straight in:
#   ./scripts/demo-menu.sh incidents
#   ./scripts/demo-menu.sh video [path.mp4]
#
# Live AI Demo       — the real pipeline on a synthetic RTSP camera
#                      (mediamtx + test pattern -> YOLOX -> tracking ->
#                      risk -> notifications -> Device API).
# Incident Demo      — synthetic fall incidents through the real engines
#                      every ~10s; perfect for testing the mobile app.
# Custom Video Demo  — the live pipeline fed with YOUR video file
#                      (a clip with people produces real detections).
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

SCRIPTS="$GUARDIAN_REPO/scripts"

run_live() { exec "$SCRIPTS/demo-live.sh"; }

run_incidents() {
    "$SCRIPTS/demo-incidents.sh" start
    echo
    note "stop later with: ./scripts/demo-incidents.sh stop  (or ./guardian stop)"
}

run_video() {
    local video="${1:-}"
    if [ -z "$video" ] && [ -t 0 ]; then
        printf '%s' "Path to a video file (people in it = real detections): "
        read -r video
    fi
    video="${video/#\~/$HOME}"
    [ -n "$video" ] || die "no video given — usage: $0 video path/to/clip.mp4"
    [ -f "$video" ] || die "video not found: $video"
    say "live demo with your video: $video"
    DEMO_VIDEO="$video" exec "$SCRIPTS/demo-live.sh"
}

case "${1:-}" in
    live)      run_live ;;
    incidents) run_incidents; exit 0 ;;
    video)     run_video "${2:-}" ;;
    "")        ;; # fall through to the menu
    *)         die "unknown demo '${1}' — one of: live | incidents | video" ;;
esac

say "Guardian AI demos"
cat <<EOF

     1) Live AI Demo       — full pipeline on a synthetic RTSP camera
     2) Incident Demo      — synthetic fall incidents (mobile-app testing)
     3) Custom Video Demo  — full pipeline on YOUR video file
     4) Exit

EOF
printf 'Select [1-4]: '
read -r choice || exit 0
case "$choice" in
    1) run_live ;;
    2) run_incidents ;;
    3) run_video ;;
    4|q|quit|exit) say "bye" ;;
    *) die "pick a number between 1 and 4" ;;
esac
