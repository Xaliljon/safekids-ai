#!/usr/bin/env bash
# Live-tail Guardian logs, per subsystem.
#
#   ./scripts/logs.sh              # interactive menu
#   ./scripts/logs.sh vision       # tail one subsystem directly
#   ./scripts/logs.sh --list       # show available logs
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

declare -a NAMES=(system vision tracking risk notifications device_api installer supervisor)

log_file() {
    case "$1" in
        supervisor) echo "$EDGE_LOG" ;;
        *) echo "$LOGS_DIR/$1.log" ;;
    esac
}

[ -d "$LOGS_DIR" ] || die "no logs yet at $LOGS_DIR — start the box first: ./scripts/start.sh"

if [ "${1:-}" = "--list" ]; then
    say "available logs"
    for name in "${NAMES[@]}"; do
        file="$(log_file "$name")"
        if [ -f "$file" ]; then
            ok "$name ($(du -h "$file" | cut -f1 | tr -d ' '))"
        else
            note "$name (empty)"
        fi
    done
    exit 0
fi

CHOICE="${1:-}"
if [ -z "$CHOICE" ]; then
    say "which log? (live tail, Ctrl+C to exit)"
    select CHOICE in "${NAMES[@]}"; do
        [ -n "${CHOICE:-}" ] && break
    done
fi

FILE="$(log_file "$CHOICE")"
[ -n "$FILE" ] && [[ " ${NAMES[*]} " == *" $CHOICE "* ]] \
    || die "unknown log '$CHOICE' — one of: ${NAMES[*]}"
[ -f "$FILE" ] || die "no entries yet for '$CHOICE' ($FILE) — is the box running?"

say "tailing $CHOICE — Ctrl+C to exit"
exec tail -f "$FILE"
