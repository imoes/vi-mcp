"""Usage (German command names are accepted as aliases):
  python3 -m vi_mcp                       start the server (configuration: $VI_MCP_CONFIG or ~/.config/vi-mcp/config.json)
  python3 -m vi_mcp instance NAME [--reflexes] [--release] [--human]
                                          create an instance or renew its token; prints the token ONCE
  python3 -m vi_mcp net …                 network: setup, invite, exclude, invitation, join, run, peers, id, status
  python3 -m vi_mcp setup [--help]        register vi-mcp in Claude Code, Codex CLI and Hermes Agent (ANSI menu)
  python3 -m vi_mcp p2p-key PATH          create an Ed25519 seed (0600), prints the public key
  python3 -m vi_mcp net-token NAME        show an instance's network token if it was lost (needs access to the database)
  python3 -m vi_mcp quarantine [N]       what waits in quarantine, with the check results (as administrator / sudo)
  python3 -m vi_mcp release ID "REASON" [--discard]   release (or discard) a held entry as a person; uses the token in
                                         /etc/vi-mcp/freigabe-token (made on first use)
  python3 -m vi_mcp delete-instance NAME "REASON"
                                          delete all private data of an instance (conversations → tombstones);
                                          stop a running service first (one writer)
  python3 -m vi_mcp port [PORT]           show the server port, or set it (1024–65535) and restart the service; the local
                                          network service (vi-p2p) follows. Clients and proxies (nginx) keep their URL: adjust them.
  python3 -m vi_mcp embed setup|auto|compare|status|remove [--backend auto|cuda|vulkan|rocm|cpu] [--rerank auto|force|off]
                                          [--port N] [--model-file F] [--no-switch]
                                          own embedding service and reranker (llama.cpp + bge-m3 + bge-reranker-v2-m3); the GPU is
                                          detected (CUDA, Vulkan, CPU). auto = what the packages run: never replaces an external service
  python3 -m vi_mcp index list|move ID INDEX|rename OLD NEW|backfill [--apply]|train INDEX   (--reason for move/rename)
  python3 -m vi_mcp index import-code REPO --index X [--url URL --token-file F] [--dry-run]
  python3 -m vi_mcp index export INDEX FILE | import FILE --as INDEX | compare INDEX [--dry-run]   (0.62.0)
  python3 -m vi_mcp classify [--limit N] [--dry-run]  label knowledge for the AI language (which question it answers); sleep
                                          does it when config classify names a model (0.62.0)
  python3 -m vi_mcp web internal [on|off] [--base PATH]  internal knowledge search with sign-in under /intern (0.62.0)
  python3 -m vi_mcp dataset export DIR [--index X]  training data (qa/kto/dpo .jsonl, DATASHEET.md) to fine-tune a model (0.62.0)
  python3 -m vi_mcp incubator status [--index X] | hatch DIR [--index X] [--force]  maturity of a VI for fine-tuning (0.62.0)
  python3 -m vi_mcp finetune guide | plan | kit DIR [--base M] [--force] | record DIR  fine-tune an AI with this VI (0.62.0)
  python3 -m vi_mcp redteam [--json]       memory-poisoning test in a throw-away memory: how often planted knowledge reaches an agent (0.62.0)
                                          the code of a git repository into an index (only changed files; removed ones archived)
                                          indexes (0.61.0): projects and special VIs — every object belongs to one; a project's
                                          index comes first in search and hints; an index with enough data trains its own model
  python3 -m vi_mcp family INSTANCE [FAMILY|-]
                                          show or declare the model family of an instance (claude, gpt, qwen …); confirmations and
                                          refutations of one family count as one independent line. "-" removes it. Restarts the service.
  python3 -m vi_mcp visibility FILTER shared|internal REASON [--apply]
                                          switch the objects of FILTER between shared and internal (through the running service, release
                                          token); without --apply it only counts. Private objects are never switched.
  python3 -m vi_mcp stdio [--socket PATH]  MCP over stdio for clients on the server host (claude mcp add vi-mcp -- vi-mcp stdio):
                                          a bridge to the running service's local socket — no token, the kernel names the user
  python3 -m vi_mcp local [USER [INSTANCE|-]]
                                          show or allow which local user reaches the VI over stdio as which instance; restarts the service
  python3 -m vi_mcp image FILE --text T --hashtags a:b,c:d --source S [--content-file F|-] [--regions F.json] [--visibility shared|internal]
                                          put an image with its description (and regions in SAM 3 format) into memory, through the
                                          server the clients use; "image get ID OUTFILE" fetches it back
  python3 -m vi_mcp configure [--new]       ANSI menu: server, networks, web page and instances, language model (Debian: dpkg-reconfigure
                                          vi-mcp); --set KEY=VALUE …, --env (VI_MCP_<KEY> from the environment, as at installation)
  python3 -m vi_mcp db status | db migrate --to postgresql://USER@HOST/DB [--from FILE --schema NAME]
                                          the database: SQLite file (default) or PostgreSQL (optional, psycopg 3); migrate copies the
                                          memory and its archive (or one network logbook with --from) into an empty schema and compares
                                          every table's row count; then vi-mcp configure --set db=URL
  python3 -m vi_mcp web [on|off] [--base PATH]
                                          the read-only web page of the free and open networks (search, wiki, forum, knowledge) under
                                          /web; --base = the path the browser sees behind the reverse proxy (e.g. /vi-mcp/web); restarts
  python3 -m vi_mcp merge-repeats INSTANCE REGEX [--apply]
                                          merge the instance's insights whose text gives the same key (REGEX group 1) into one object
                                          per key, earlier texts in its history; without --apply it only counts. Stop the service first.
"""
import os
import sys

# 0.60.0: on Windows verify TLS through the system (truststore, as pip does). Python only sees root certificates already in the store, and
# Windows fetches a missing root only when its own TLS stack asks — on a fresh Windows 11 every download of `vi-mcp embed auto` failed with
# CERTIFICATE_VERIFY_FAILED until something else had connected (test VM, 12.11.2026: default context failed, truststore succeeded, after
# that the default context succeeded too). Optional: without the package the default context stays.
if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

from . import config, server  # noqa: E402

#: English command → German alias (accepted as well)
COMMANDS = {"setup": "einrichten", "image": "bild", "local": "lokal", "net": "netz", "instance": "instanz", "net-token": "netz-token", "p2p-key": "p2p-schluessel",
            "release": "freigeben", "delete-instance": "loesche-instanz", "web": "webseite", "quarantine": "quarantaene",
            "configure": "konfigurieren"}
_ALIASES = {de: en for en, de in COMMANDS.items()}


def _approve(oid: str, reason: str, discard: bool = False) -> int:
    return _local_tool("vi_release", {"id": oid, "reason": reason, **({"action": "verwerfen"} if discard else {})})


#: 0.62.1: the local instance whose token `vi-mcp release` / `vi-mcp visibility` use — made on first use, a person at the console
RELEASE_CLI = "release-cli"


def release_token_path() -> str:
    import os
    default = (os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "vi-mcp", "freigabe-token") if os.name == "nt"
               else "/etc/vi-mcp/freigabe-token")
    return os.environ.get("VI_MCP_FREIGABE_TOKEN_FILE", default)


def _make_release_token(path: str) -> str | None:
    """No installer ever wrote the release token file (found on Windows, 13.11.2026: `vi-mcp release` ended in FileNotFoundError).
    Made here on first use: the instance `release-cli` with the release right, marked as a person (the administrator at the console),
    its token in the file readable by the administrators only, then the service restarted once — it reads instances only at start.
    Returns None on success, otherwise what to do."""
    import os
    from . import setup
    try:
        token = config.create_instance(RELEASE_CLI, release=True, human=True)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # on Windows the folder's ACL (SYSTEM, Administrators) applies
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
    except PermissionError as e:
        return (f"no permission to create the release token ({e.filename or e}) — run this command as administrator (Windows) or with sudo "
                "(Linux)")
    print(f"created the local release instance {RELEASE_CLI!r} and its token file {path} (readable by administrators only); "
          "restarting the service once so it knows the instance")
    why = setup._restart()
    if why:
        return f"the service could not be restarted ({why}) — restart it and run the command again"
    k = config.load()
    if not setup._wait(f"http://127.0.0.1:{k.port}/mcp", 60):
        return "the service did not answer within 60 s after the restart — run the command again when it is up"
    return None


def _local_tool(tool: str, arguments: dict) -> int:
    """Own HTTP call to the running service with the release token: there stays one writer."""
    import json
    import os
    import urllib.request
    k = config.load()
    path = release_token_path()
    if not os.path.exists(path):
        why = _make_release_token(path)
        if why:
            print(why, file=sys.stderr)
            return 2
    try:
        token = open(path).read().strip()
    except PermissionError:
        print(f"no permission to read {path} — run this command as administrator (Windows) or with sudo (Linux)", file=sys.stderr)
        return 2
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{k.port}/mcp"

    def post(req_body, sid=None):
        header = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **({"Mcp-Session-Id": sid} if sid else {})}
        with op.open(urllib.request.Request(url, data=json.dumps(req_body).encode(), headers=header), timeout=30) as a:
            return a.headers.get("Mcp-Session-Id"), json.loads(a.read() or b"{}")
    sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "vi-mcp-freigeben"}}})
    _, a = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, sid)
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
            raw = ns.english_file(json.loads(p.read_text(encoding="utf-8-sig")))
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
    if command == "net":  # Linux (systemd) and since 0.54.0 Windows (scheduled tasks vi-p2p-<network>)
        if sys.platform not in ("linux", "win32"):
            print("The network service (vi-p2p) needs Linux with systemd or Windows; it is not available on this system.", file=sys.stderr)
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
    if command == "visibility" and len(argv) in (4, 5) and argv[2] in ("shared", "internal") and argv[4:] in ([], ["--apply"]):
        return _local_tool("vi_set_visibility", {"filter": argv[1], "visibility": argv[2], "reason": argv[3], "apply": "--apply" in argv})
    if command == "release" and len(argv) in (3, 4) and argv[3:] in ([], ["--discard"]):
        return _approve(argv[1], argv[2], discard=argv[3:] == ["--discard"])
    if command == "quarantine" and len(argv) in (1, 2) and (len(argv) == 1 or argv[1].isdigit()):
        # 0.62.1: a person sees what waits — with a single AI no other instance can release what the fixed rules held from it
        return _local_tool("vi_quarantine", {"limit": int(argv[1]) if len(argv) == 2 else 50})
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
    if command == "index":  # 0.61.0
        from . import indexes
        return indexes.main(argv[1:])
    if command == "family" and len(argv) in (2, 3):
        k = config.load()
        if argv[1] not in k.instances:
            print(f"instance {argv[1]!r} unknown", file=sys.stderr)
            return 2
        if len(argv) == 2:
            import sqlite3
            declared = k.instances[argv[1]].family
            print(f"declared: {declared or 'none'}" + (" (wins over announcements)" if declared else ""))
            try:  # read only: what the clients of this instance announced (0.34.0)
                from . import db as dbmod
                c = dbmod.connect_readonly(k.db)
                rows = c.execute("SELECT json_extract(daten, '$.familie'), json_extract(daten, '$.familie_quelle'), json_extract(daten, '$.client'), "
                                 "MAX(zeit), COUNT(*) FROM objekt WHERE art = 'gespraech' AND instanz = ? AND json_extract(daten, '$.familie') IS NOT NULL "
                                 "GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 10", (argv[1],)).fetchall()
            except sqlite3.Error as e:
                rows, err = [], e
                print(f"announced: not readable ({err})")
            for fam, src, client, last, n in rows:
                print(f"announced: {fam} ({'header X-VI-Family' if src == 'header' else 'client name'}, {client}) — {n} conversation(s), last {str(last)[:16]}")
            if not declared and not rows:
                print("no family known — the instance counts as its own line")
            return 0
        try:
            old = config.set_family(argv[1], None if argv[2] == "-" else argv[2])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"{argv[1]}: family {old or 'undeclared'} → {argv[2] if argv[2] != '-' else 'undeclared'}; restarting the service")
        from . import setup
        setup._restart()
        return 0
    if command == "db":  # 0.50.0: optional PostgreSQL
        from . import db_migrate
        return db_migrate.main(argv[1:])
    if command == "configure":  # 0.48.0
        from . import configure
        return configure.main(argv[1:])
    if command == "web" and argv[1:2] == ["internal"] and len(argv) in (2, 3, 5) and argv[2:3] in ([], ["on"], ["off"]) \
            and (len(argv) < 5 or argv[3] == "--base"):  # 0.62.0: the internal knowledge search with sign-in
        k = config.load()
        if len(argv) == 2:
            print(f"internal knowledge search: {'on' if k.web_internal else 'off'} · path {k.web_internal_base} (the server answers under "
                  "/intern; sign-in with a VI token; the reverse proxy needs no own location if it passes the vi-mcp prefix through)")
            return 0
        try:
            config.set_web_internal(argv[2] == "on", argv[4] if len(argv) == 5 else None)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"internal knowledge search {argv[2]}; restarting the service")
        from . import setup
        setup._restart()
        return 0
    if command == "web" and len(argv) in (1, 2, 4) and argv[1:2] in ([], ["on"], ["off"]) and (len(argv) < 4 or argv[2] == "--base"):  # 0.46.0
        k = config.load()
        if len(argv) == 1:
            print(f"web page: {'on' if k.web else 'off'} · path {k.web_base} (the server answers under /web; give the reverse proxy a location for it)")
            return 0
        try:
            config.set_web(argv[1] == "on", argv[3] if len(argv) == 4 else None)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"web page {argv[1]}; restarting the service")
        from . import setup
        setup._restart()
        return 0
    if command == "redteam":  # 0.62.0: the memory-poisoning test in a throw-away memory
        from . import redteam
        return redteam.main(argv[1:])
    if command == "relevance":  # 0.62.0: a language model grades real searches (UMBRELA) — the relevance label
        from . import relevance
        return relevance.main(argv[1:])
    if command == "logic":  # 0.62.0: the logic layer (clingo) — install, status, check a file
        from . import logic
        return logic.main(argv[1:])
    if command == "finetune":  # 0.62.0: the interface for fine-tuning an AI with this VI
        from . import finetune
        return finetune.main(argv[1:])
    if command == "incubator":  # 0.62.0: maturity of a VI for fine-tuning
        from . import incubator
        return incubator.main(argv[1:])
    if command == "dataset":  # 0.62.0: training data for fine-tuning a model
        from . import dataset
        return dataset.main(argv[1:])
    if command == "classify":  # 0.62.0
        from . import classify
        return classify.main(argv[1:])
    if command == "stdio":
        from . import stdio_bridge
        return stdio_bridge.main(argv[1:])
    if command == "local" and len(argv) in (1, 2, 3):
        k = config.load()
        if len(argv) == 1:
            print(f"local socket: {k.socket or 'not configured'}")
            for u, i in sorted(k.local.items()):
                print(f"  {u} → {i}" + ("" if i in k.instances else "  (instance unknown!)"))
            if not k.local:
                print("  no local user allowed — vi-mcp local USER INSTANCE")
            return 0
        if len(argv) == 2:
            print(k.local.get(argv[1]) or "not allowed")
            return 0
        try:
            old = config.set_local(argv[1], None if argv[2] == "-" else argv[2])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"local user {argv[1]}: {old or 'not allowed'} → {argv[2] if argv[2] != '-' else 'not allowed'}; restarting the service")
        from . import setup
        setup._restart()
        return 0
    if command == "image" and len(argv) >= 2:
        from . import image_cli
        return image_cli.main(argv[1:])
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
