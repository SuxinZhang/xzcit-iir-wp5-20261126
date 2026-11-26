#!/usr/bin/env bash
set -euo pipefail
: "${IIR_DEPLOY_DIR:?}"
for unit in "$IIR_DEPLOY_DIR"/systemd/*; do
    installed="$HOME/.config/systemd/user/$(basename "$unit")"
    cmp -s "$unit" "$installed" || { printf 'Changed or missing unit: %s\n' "$installed" >&2; exit 1; }
done
systemctl --user disable --now iir.target
for unit in "$IIR_DEPLOY_DIR"/systemd/*; do
    rm "$HOME/.config/systemd/user/$(basename "$unit")"
done
systemctl --user daemon-reload
