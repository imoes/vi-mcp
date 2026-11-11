#!/bin/sh
# Shared by Debian and RPM. Usage: nach-installation.sh system | menue
case "$1" in
system)
    install -d -o vi-mcp -g vi-mcp -m 0700 /var/lib/vi-mcp
    install -d -o root -g vi-mcp -m 0750 /etc/vi-mcp
    install -d -o vi-p2p -g vi-p2p -m 0700 /var/lib/vi-p2p
    install -d -o root -g vi-p2p -m 0750 /etc/vi-p2p
    if [ ! -e /etc/vi-mcp/config.json ]; then
        # port at first installation: VI_MCP_PORT=9000 apt install ./vi-mcp_….deb (later: vi-mcp port 9000)
        port="${VI_MCP_PORT:-8765}"
        case "$port" in ''|*[!0-9]*) port=8765 ;; esac
        if [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then port=8765; fi
        umask 027
        cat > /etc/vi-mcp/config.json <<JSON
{
  "bind": "127.0.0.1",
  "port": $port,
  "db": "/var/lib/vi-mcp/vi.db",
  "instances": {},
  "ttl": {},
  "origins": ["http://localhost", "http://127.0.0.1"]
}
JSON
        chown root:vi-mcp /etc/vi-mcp/config.json
        chmod 0640 /etc/vi-mcp/config.json
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable vi-mcp.service >/dev/null 2>&1 || true
    # 0.53.1: the memory first, then the network services (they ask the memory at their first round). The key is "instances" since
    # 0.51.0 ("instanzen" before): checking only the old name left vi-mcp stopped after the update to 0.53.0 (production, 11.11.2026).
    if python3 -c "import json,sys; c=json.load(open('/etc/vi-mcp/config.json')); sys.exit(0 if c.get('instances') or c.get('instanzen') else 1)"; then
        systemctl restart vi-mcp.service >/dev/null 2>&1 || true
        # wait until it answers (at most 20 s): the network services ask it at their first round
        python3 - <<'PY' || true
import json, time, urllib.request
port = json.load(open("/etc/vi-mcp/config.json")).get("port", 8765)
for _ in range(40):
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{port}/gesund", timeout=1).close()
        break
    except OSError:
        time.sleep(0.5)
PY
    fi
    # prerm stops the network service during an upgrade; try-restart would not start it again
    if systemctl is-enabled --quiet vi-p2p.service 2>/dev/null; then systemctl restart vi-p2p.service >/dev/null 2>&1 || true; fi
    # 0.39.0: further networks (vi-p2p@<netz>), each with /etc/vi-p2p/<netz>.json
    for f in /etc/vi-p2p/*.json; do
        n=$(basename "$f" .json); [ "$n" = config ] && continue
        if systemctl is-enabled --quiet "vi-p2p@$n.service" 2>/dev/null; then systemctl restart "vi-p2p@$n.service" >/dev/null 2>&1 || true; fi
    done
    ;;
wiki)
    # 0.47.0: a new installation joins the public wiki network vi-wiki.org (free network, outgoing only). Opt out: VI_MCP_KEIN_WIKI=1.
    # The AI tells the user about it and switches it off on request (vi_net_switch); the administrator: vi-mcp net wiki off.
    if [ -n "$VI_MCP_KEIN_WIKI" ]; then
        echo "vi-mcp: wiki network not joined (VI_MCP_KEIN_WIKI); later: sudo vi-mcp net wiki on"
        exit 0
    fi
    if [ ! -e /etc/vi-p2p/wiki.json ]; then
        /usr/bin/vi-mcp net wiki on >/dev/null 2>&1 && echo "vi-mcp: joined the public wiki network vi-wiki.org (off: sudo vi-mcp net wiki off)" \
            || echo "vi-mcp: joining the wiki network failed; later: sudo vi-mcp net wiki on"
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
