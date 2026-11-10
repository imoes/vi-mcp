#!/bin/sh
# Shared by Debian and RPM. Usage: nach-installation.sh system | menue
case "$1" in
system)
    install -d -o vi-mcp -g vi-mcp -m 0700 /var/lib/vi-mcp
    install -d -o root -g vi-mcp -m 0750 /etc/vi-mcp
    install -d -o vi-p2p -g vi-p2p -m 0700 /var/lib/vi-p2p
    install -d -o root -g vi-p2p -m 0750 /etc/vi-p2p
    if [ ! -e /etc/vi-mcp/config.json ]; then
        umask 027
        cat > /etc/vi-mcp/config.json <<'JSON'
{
  "bind": "127.0.0.1",
  "port": 8765,
  "db": "/var/lib/vi-mcp/vi.db",
  "instanzen": {},
  "ttl": {},
  "origins": ["http://localhost", "http://127.0.0.1"]
}
JSON
        chown root:vi-mcp /etc/vi-mcp/config.json
        chmod 0640 /etc/vi-mcp/config.json
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable vi-mcp.service >/dev/null 2>&1 || true
    # prerm stops the network service during an upgrade; try-restart would not start it again
    if systemctl is-enabled --quiet vi-p2p.service 2>/dev/null; then systemctl restart vi-p2p.service >/dev/null 2>&1 || true; fi
    if python3 -c "import json,sys; sys.exit(0 if json.load(open('/etc/vi-mcp/config.json')).get('instanzen') else 1)"; then
        systemctl restart vi-mcp.service >/dev/null 2>&1 || true
    fi
    ;;
menue)
    hinweis="vi-mcp: set up Claude Code, Codex and Hermes:  sudo vi-mcp setup"
    # Unattended runs (Ansible, CI, image builds) must never wait for a key press
    if [ -n "$VI_MCP_KEIN_MENUE" ] || [ "$DEBIAN_FRONTEND" = "noninteractive" ] || ! (: </dev/tty) 2>/dev/null; then
        echo "$hinweis"
        exit 0
    fi
    /usr/bin/vi-mcp setup --idle 120 </dev/tty >/dev/tty 2>&1 || echo "$hinweis"
    ;;
esac
exit 0
