#!/usr/bin/env bash
# Factory reset: remove configuration, trusted devices, notifications,
# logs, reports and caches. Keeps models and backups. Asks first.
#
#   ./scripts/reset.sh          # interactive confirmation
#   ./scripts/reset.sh --yes    # no prompt (automation)
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

[ -d "$GUARDIAN_HOME" ] || die "Guardian home not found: $GUARDIAN_HOME — nothing to reset"

say "factory reset of $GUARDIAN_HOME"
note "removes: config/ (cameras), data/ (trusted devices, notification outbox),"
note "         logs/, reports/, run/"
note "keeps:   models/, backups/"
echo

if [ "${1:-}" != "--yes" ]; then
    printf '%sType RESET to continue:%s ' "$C_YELLOW" "$C_RESET"
    read -r ANSWER
    [ "$ANSWER" = "RESET" ] || die "aborted (nothing was changed)"
fi

if edge_running; then
    say "stopping guardian-edge first"
    stop_edge
fi

for dir in config data logs reports run; do
    if [ -e "$GUARDIAN_HOME/$dir" ]; then
        rm -rf "${GUARDIAN_HOME:?}/$dir"
        ok "$dir/ removed"
    fi
done

say "factory reset complete"
note "kept: $GUARDIAN_HOME/models, $GUARDIAN_HOME/backups"
note "next: ./scripts/setup.sh (recreate layout), or ./scripts/restore.sh (bring a backup back)"
note "phones must pair again: previous trusted devices are gone"
