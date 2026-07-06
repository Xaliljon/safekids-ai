#!/usr/bin/env bash
# Restore a configuration backup (latest by default).
#
#   ./scripts/restore.sh                       # newest backup in $GUARDIAN_HOME/backups
#   ./scripts/restore.sh path/to/backup.zip    # a specific archive
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_workspace

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    ARCHIVE="$(ls -t "$GUARDIAN_HOME/backups"/guardian-backup-*.zip 2>/dev/null | head -1)"
    [ -n "$ARCHIVE" ] || die "no backups found in $GUARDIAN_HOME/backups — create one with ./scripts/backup.sh"
    say "restoring latest backup: $(basename "$ARCHIVE")"
else
    [ -f "$ARCHIVE" ] || die "archive not found: $ARCHIVE"
    say "restoring: $ARCHIVE"
fi

guardianctl restore "$ARCHIVE" || die "restore failed"

if edge_running; then
    say "restarting guardian-edge to apply the configuration"
    "$GUARDIAN_REPO/scripts/restart.sh"
else
    note "start the box to apply: ./scripts/start.sh"
fi
