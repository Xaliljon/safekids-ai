#!/usr/bin/env bash
# Gracefully remove Guardian AI from this machine. Backups are kept.
#
#   ./scripts/uninstall.sh          # interactive confirmation
#   ./scripts/uninstall.sh --yes    # no prompt
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

say "uninstall Guardian AI"
note "removes: guardian-edge service, demo rig, $GUARDIAN_HOME (models, config, data, logs)"
note "keeps:   $GUARDIAN_HOME/backups (moved to ~/guardian-backups), this repository"
echo

if [ "${1:-}" != "--yes" ]; then
    printf '%sType UNINSTALL to continue:%s ' "$C_YELLOW" "$C_RESET"
    read -r ANSWER
    [ "$ANSWER" = "UNINSTALL" ] || die "aborted (nothing was changed)"
fi

say "stopping services"
"$GUARDIAN_REPO/scripts/stop.sh"

# systemd unit (Linux production installs)
if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/guardian-edge.service ]; then
    say "removing systemd service (needs sudo)"
    sudo systemctl disable --now guardian-edge 2>/dev/null || true
    sudo rm -f /etc/systemd/system/guardian-edge.service
    sudo systemctl daemon-reload
    ok "systemd unit removed"
fi

if [ -d "$GUARDIAN_HOME" ]; then
    if [ -d "$GUARDIAN_HOME/backups" ] && [ -n "$(ls -A "$GUARDIAN_HOME/backups" 2>/dev/null)" ]; then
        KEEP_DIR="$HOME/guardian-backups"
        mkdir -p "$KEEP_DIR"
        mv "$GUARDIAN_HOME/backups"/* "$KEEP_DIR"/ 2>/dev/null || true
        ok "backups preserved in $KEEP_DIR"
    fi
    rm -rf "$GUARDIAN_HOME"
    ok "$GUARDIAN_HOME removed"
else
    note "no Guardian home at $GUARDIAN_HOME"
fi

say "uninstall complete"
note "the repository itself was kept — delete it manually if you want: rm -rf $GUARDIAN_REPO"
