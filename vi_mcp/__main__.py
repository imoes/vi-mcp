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
  python3 -m vi_mcp port [PORT]           show the server port, or set it (1024–65535) and restart the service; the local
                                          network service (vi-p2p) follows. Clients and proxies (nginx) keep their URL: adjust them.
  python3 -m vi_mcp embed setup|status|remove [--port N] [--cpu] [--model-file F] [--no-switch]
                                          own embedding service (llama.cpp + bge-m3, Vulkan or CPU) for the vectors
  python3 -m vi_mcp merge-repeats INSTANCE REGEX [--apply]
                                          merge the instance's insights whose text gives the same key (REGEX group 1) into one object
                                          per key, earlier texts in its history; without --apply it only counts. Stop the service first.
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
    default = (os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "vi-mcp", "freigabe-token") if os.name == "nt"
               else "/etc/vi-mcp/freigabe-token")
    token = open(os.environ.get("VI_MCP_FREIGABE_TOKEN_FILE", default)).read().strip()
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


def _port(value: str | None) -> int:
    """0.27.0: show or set the server port (Linux and Windows); the local network service follows, the service is restarted."""
    import json
    if value is None:
        print(config.load().port)
        return 0
    try:
        old = config.set_port(int(value))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    new = int(value)
    print(f"port {old} → {new} in {config.fpath()}")
    if sys.platform == "linux":  # the network service calls the server at 127.0.0.1:<port>
        from . import net_service as ns
        p = ns.fpath()
        if p.exists():
            raw = json.loads(p.read_text())
            url = raw.get("mcp_url") or ns.NetConfig().mcp_url
            if url.startswith(("http://127.0.0.1:", "http://localhost:")):
                raw["mcp_url"] = f"http://127.0.0.1:{new}/mcp"
                from . import net_cli
                net_cli._write(p, raw)
                print(f"network service: mcp_url → {raw['mcp_url']}")
    from . import setup
    reason = setup._restart()
    if reason:
        print(f"restart failed: {reason} — restart the service by hand", file=sys.stderr)
        return 1
    if sys.platform == "linux":
        import subprocess
        subprocess.run(["systemctl", "try-restart", "vi-p2p"], capture_output=True, timeout=45)
    print(f"service restarted; clients use http://127.0.0.1:{new}/mcp (a reverse proxy such as nginx must be adjusted by hand)")
    return 0


def _cli(argv: list[str]) -> int:
    if not argv:
        server.main()
        return 0
    command = _ALIASES.get(argv[0], argv[0])
    if command == "net":
        if sys.platform != "linux":  # 0.27.0
            print("The network service (vi-p2p) needs Linux with systemd; it is not available on this system.", file=sys.stderr)
            return 2
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
    if command == "embed":
        from . import embed_service
        return embed_service.main(argv[1:])
    if command == "port" and len(argv) in (1, 2):
        return _port(argv[1] if len(argv) == 2 else None)
    if command == "merge-repeats" and len(argv) in (3, 4) and argv[3:] in ([], ["--apply"]):
        import json
        import re
        from . import memory as g
        rx = re.compile(argv[2], re.S)
        g.open_db(config.load().db)
        try:
            r = g.merge_by_key(argv[1], lambda t: (m.group(1).strip() if (m := rx.search(t)) else None), who="admin",
                               reason=f"merge-repeats {argv[2]}", apply="--apply" in argv)
        finally:
            g.close_db()
        print(json.dumps(r))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


sys.exit(_cli(sys.argv[1:]))
