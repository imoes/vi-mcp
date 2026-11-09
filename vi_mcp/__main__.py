"""Aufruf:
  python3 -m vi_mcp                       Server starten (Konfiguration: $VI_MCP_CONFIG oder ~/.config/vi-mcp/config.json)
  python3 -m vi_mcp instanz NAME [--reflexe]
                                          Instanz anlegen bzw. Token erneuern; gibt das Token EINMAL aus
  python3 -m vi_mcp netz …                Netz: einrichten, einladen, ausschliessen, id, status
  python3 -m vi_mcp einrichten [--hilfe]  vi-mcp in Claude Code, Codex CLI und Hermes Agent eintragen (ANSI-Menü)
  python3 -m vi_mcp p2p-schluessel PFAD    Ed25519-Seed anlegen (0600), gibt den öffentlichen Schlüssel aus
  python3 -m vi_mcp netz-token NAME       Netz-Token einer Instanz anzeigen, falls es verloren ging (nur mit Zugriff auf die Datenbank)
  python3 -m vi_mcp freigeben ID "GRUND"   heiklen Import freigeben; liest das Token aus /etc/vi-mcp/freigabe-token
  python3 -m vi_mcp loesche-instanz NAME "GRUND"
                                          alle privaten Daten einer Instanz löschen (Gespräche → Grabsteine);
                                          bei laufendem Dienst vorher stoppen (ein Schreiber)
"""
import sys

from . import config, server


def _approve(oid: str, reason: str) -> int:
    """Eigener HTTP-Aufruf an den laufenden Dienst: es bleibt bei einem Schreiber."""
    import json
    import os
    import urllib.request
    k = config.load()
    token = open(os.environ.get("VI_MCP_FREIGABE_TOKEN_FILE", "/etc/vi-mcp/freigabe-token")).read().strip()
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{k.port}/mcp"

    def post(req_body, sid=None):
        header = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **({"Mcp-Session-Id": sid} if sid else {})}
        with op.open(urllib.request.Request(url, data=json.dumps(req_body).encode(), headers=header), timeout=30) as a:
            return a.headers.get("Mcp-Session-Id"), json.loads(a.read() or b"{}")
    sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "vi-mcp-freigeben"}}})
    _, a = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "vi_release", "arguments": {"id": oid, "grund": reason}}}, sid)
    print(a["result"]["content"][0]["text"])
    return 1 if a["result"]["isError"] else 0


def _cli(argv: list[str]) -> int:
    if not argv:
        server.main()
        return 0
    if argv[0] == "netz":
        from . import net_cli
        return net_cli.main(argv[1:])
    if argv[0] == "einrichten":
        from . import setup
        return setup.main(argv[1:])
    if argv[0] == "instanz" and len(argv) >= 2:
        token = config.create_instance(argv[1], reflexes="--reflexe" in argv[2:], release="--freigabe" in argv[2:], human="--mensch" in argv[2:])
        print(f"Instanz {argv[1]} in {config.fpath()} angelegt (Reflex-Recht: {'ja' if '--reflexe' in argv[2:] else 'nein'}).")
        print(f"Token (wird nicht gespeichert, nur sein SHA-256):\n{token}")
        return 0
    if argv[0] == "p2p-schluessel" and len(argv) == 2:
        from pathlib import Path
        from . import p2p
        print(p2p.generate_keys(Path(argv[1])))
        return 0
    if argv[0] == "netz-token" and len(argv) == 2:
        from . import memory as g, p2p
        g.open_db(config.load().db)
        try:
            t = p2p.show_token(argv[1])
        finally:
            g.close_db()
        print(t or f"Instanz {argv[1]} hat kein Netz-Token")
        return 0 if t else 1
    if argv[0] == "freigeben" and len(argv) == 3:
        return _approve(argv[1], argv[2])
    if argv[0] == "loesche-instanz" and len(argv) >= 3:
        from . import memory as g, session
        k = config.load()
        g.open_db(k.db)
        try:
            r = session.delete_instance_data(argv[1], argv[2])
        finally:
            g.close_db()
        print(f"Instanz {argv[1]}: {r['gespraeche']} Gespräche → Grabsteine, {r['objekte']} private Objekte gelöscht. Geteiltes Wissen bleibt.")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


sys.exit(_cli(sys.argv[1:]))
