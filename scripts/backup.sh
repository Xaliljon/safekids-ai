#!/usr/bin/env bash
# Create a timestamped configuration backup (cameras + trusted devices).
# Models, video and logs are never included — by construction (ADR-0016).
#
#   ./scripts/backup.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

need_uv; need_workspace
[ -d "$GUARDIAN_HOME" ] || die "Guardian home not found: $GUARDIAN_HOME — run ./scripts/setup.sh"

say "creating backup"
guardianctl backup || die "backup failed"
LATEST="$(ls -t "$GUARDIAN_HOME/backups"/guardian-backup-*.zip 2>/dev/null | head -1)"
[ -n "$LATEST" ] && note "restore later with: ./scripts/restore.sh   (latest: $(basename "$LATEST"))"
