"""Usage (German command names are accepted as aliases):
  python3 -m vi_mcp                       start the server (configuration: $VI_MCP_CONFIG or ~/.config/vi-mcp/config.json)
  python3 -m vi_mcp instance NAME [--reflexes] [--release] [--human]
                                          create an instance or renew its token; prints the token ONCE
  python3 -m vi_mcp net …                 network: setup, invite, exclude, invitation, join, run, peers, id, status
  python3 -m vi_mcp setup [--help]        register vi-mcp in Claude Code, Codex CLI and Hermes Agent (ANSI menu)
  python3 -m vi_mcp p2p-key PATH          create an Ed25519 seed (0600), prints the public key
  python3 -m vi_mcp net-token NAME        show an instance's network token if it was lost (needs access to the database)
  python3 -m vi_mcp release ID "REASON"   release a sensitive import; reads the token from /etc/vi-mcp/freigabe-token
  python3 -m vi_mcp delete-instance NAME "REASON"
                                          delete all private data of an instance (conversations → tombstones);
                                          stop a running service first (one writer)
"""
import sys

from . import config, server

#: English command → German alias (accepted as well)
COMMANDS = {"setup": "einrichten", "net": "netz", "instance": "instanz", "net-token": "netz-token", "p2p-key": "p2p-schluessel",
            "release": "freigeben", "delete-instance": "loesche-instanz"}
_ALIASES = {de: en for en, de in COMMANDS.items()}


def _approve(oid: str, reason: str) -> int:
    """Own HTTP call to the running service: there stays one writer."""
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
    _, a = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "vi_release", "arguments": {"id": oid, "reason": reason}}}, sid)
    print(a["result"]["content"][0]["text"])
    return 1 if a["result"]["isError"] else 0


def _cli(argv: list[str]) -> int:
    if not argv:
        server.main()
        return 0
    command = _ALIASES.get(argv[0], argv[0])
    if command == "net":
        from . import net_cli
        return net_cli.main(argv[1:])
    if command == "setup":
        from . import setup
        return setup.main(argv[1:])
    if command == "instance" and len(argv) >= 2:
        opts = argv[2:]
        reflexes = "--reflexes" in opts or "--reflexe" in opts
        token = config.create_instance(argv[1], reflexes=reflexes, release="--release" in opts or "--freigabe" in opts,
                                       human="--human" in opts or "--mensch" in opts)
        print(f"Instance {argv[1]} created in {config.fpath()} (reflex right: {'yes' if reflexes else 'no'}).")
        print(f"Token (not stored, only its SHA-256):\n{token}")
        return 0
    if command == "p2p-key" and len(argv) == 2:
        from pathlib import Path
        from . import p2p
        print(p2p.generate_keys(Path(argv[1])))
        return 0
    if command == "net-token" and len(argv) == 2:
        from . import memory as g, p2p
        g.open_db(config.load().db)
        try:
            t = p2p.show_token(argv[1])
        finally:
            g.close_db()
        print(t or f"Instance {argv[1]} has no network token")
        return 0 if t else 1
    if command == "release" and len(argv) == 3:
        return _approve(argv[1], argv[2])
    if command == "delete-instance" and len(argv) >= 3:
        from . import memory as g, session
        k = config.load()
        g.open_db(k.db)
        try:
            r = session.delete_instance_data(argv[1], argv[2])
        finally:
            g.close_db()
        print(f"Instance {argv[1]}: {r['gespraeche']} conversations → tombstones, {r['objekte']} private objects deleted. Shared knowledge stays.")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


sys.exit(_cli(sys.argv[1:]))
