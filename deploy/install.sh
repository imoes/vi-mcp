#!/usr/bin/env bash
# Installiert vi-mcp als systemd-User-Dienst. Idempotent. Legt beim ersten Mal eine Instanz an.
#   deploy/install.sh [instanzname]     (Standard: $USER, mit Reflex-Recht)
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:-$USER}"
cfg="${VI_MCP_CONFIG:-$HOME/.config/vi-mcp/config.json}"
tokdatei="$HOME/.config/vi-mcp/token-$name"
if ! python3 -c "import json,sys; sys.exit(0 if '$name' in json.load(open('$cfg')).get('instanzen',{}) else 1)" 2>/dev/null; then
  umask 077
  python3 -m vi_mcp instanz "$name" --reflexe | tail -1 > "$tokdatei"
  chmod 600 "$tokdatei"
  echo "Instanz $name angelegt; Token in $tokdatei (0600)"
fi
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 deploy/vi-mcp.service "$HOME/.config/systemd/user/vi-mcp.service"
systemctl --user daemon-reload
systemctl --user enable --now vi-mcp.service
systemctl --user restart vi-mcp.service
sleep 1
systemctl --user --no-pager --lines=5 status vi-mcp.service
curl -fsS http://127.0.0.1:8765/gesund
