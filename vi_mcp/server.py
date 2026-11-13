"""MCP over Streamable HTTP — ONE process, many sessions.

Endpoint `/mcp` (MCP specification "Streamable HTTP", https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):
  POST   JSON-RPC message or batch → answer as application/json (no SSE needed, the VI does not stream);
         only notifications/responses → 202 without content.
  GET    405 — the server sends nothing on its own.
  DELETE ends the session (conversation is saved, state `beendet`).
Session: `initialize` assigns `Mcp-Session-Id`; every further request needs it (missing → 400, unknown → 404).
Protection: bearer token per instance (401 without/with wrong token), Origin check against DNS rebinding (403),
bind 127.0.0.1 by default; several addresses possible (e.g. additionally the gateway of a Docker network through
which a reverse proxy in a container connects) — all share the same process, the same memory.
Additionally `GET /health` without authentication (old name `/gesund` still answered): only "ok" + version, for systemd/monitoring.
0.36.0: the same handler also on a local Unix socket (Linux, config `socket` or $VI_MCP_SOCKET) for `vi-mcp stdio`: there the kernel
names the connecting user (SO_PEERCRED) and config `lokal` maps the user to an instance — no token. Unlisted users get 403 with the reason.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import memory as g
from . import anonymize, index, on_demand, intuition, config, reflexes, main_loop, scorer, self_model, session, usage_stats, tools
from .log_output import log

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 8 * 1024 * 1024
SERVER_NAME = "vi-mcp"


def _answer(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}


def process(msg: dict, s: session.Session | None, inst: config.Instance) -> dict | None:
    """One JSON-RPC message on behalf of a session. None = no answer (notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid request: JSON-RPC 2.0 expected")
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method is None:
        return None  # the client's response to a server request — the VI makes none
    if mid is None:
        return None  # notification (e.g. notifications/initialized)
    with session.on_behalf(s):
        try:
            if method == "ping":
                return _answer(mid, {})
            if method == "tools/list":
                return _answer(mid, {"tools": tools.listing(inst.name)})
            if method == "tools/call":
                name = params.get("name", "")
                if not tools.known(name):
                    return _error(mid, -32602, f"unknown tool: {name}")
                t0 = time.monotonic()
                client = s.client if s else None
                public = tools.api_en.canonical_name(name)  # statistics uniformly under the public (English) name
                ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
                try:
                    text = tools.call_tool(name, params.get("arguments") or {}, inst.name, inst.reflexes, inst.release,
                                          inst.family or (s.family if s else None))  # the operator's declaration wins over the client's
                    usage_stats.record(inst.name, client, public, "ok", ms(), text)
                    pics = [{"type": "image", "data": data, "mimeType": mime} for mime, data in getattr(text, "images", [])]  # 0.35.0
                    return _answer(mid, {"content": [{"type": "text", "text": str(text)}, *pics], "isError": False})
                except tools.Rejected as e:
                    usage_stats.record(inst.name, client, public, "abgelehnt", ms())
                    return _answer(mid, {"content": [{"type": "text", "text": f"rejected: {e}"}], "isError": True})
                except Exception as e:  # noqa: BLE001 — tool error, named to the client
                    log(f"{name} failed after {ms()} ms: {type(e).__name__}: {e}")
                    usage_stats.record(inst.name, client, public, "fehler", ms())
                    return _answer(mid, {"content": [{"type": "text", "text": f"{name}: {type(e).__name__}: {e}"}], "isError": True})
            return _error(mid, -32601, f"unknown method: {method}")
        except Exception as e:  # noqa: BLE001
            log(f"internal error in {method}: {type(e).__name__}: {e}")
            return _error(mid, -32603, f"internal error: {type(e).__name__}: {e}")


def project_name(cwd) -> str | None:
    """0.24.0: the last component of the client's working directory names the project (the hook sends clientInfo.cwd). Only the name,
    never the path; at most 80 characters of [A-Za-z0-9._-]."""
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    import re
    name = re.sub(r"[^A-Za-z0-9._-]", "_", cwd.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1])[:80]
    return name or None


#: 0.34.0: model family of well-known MCP clients, recognised from clientInfo.name (prefix). Anything else must announce itself with the
#: header X-VI-Family (vi-mcp setup writes it) or is declared by the operator (vi-mcp family) — otherwise the instance is its own line.
KNOWN_CLIENT_FAMILIES = (("claude", "claude"), ("codex", "gpt"))


def client_family(announced: str | None, client_name: str | None) -> tuple[str | None, str | None]:
    """(family, source): the client's own announcement (header X-VI-Family) first, then a known client name; (None, None) if neither."""
    a = "".join(c for c in (announced or "").strip().lower() if c.isalnum() or c in "-_.")[:40]
    if a:
        return a, "header"
    n = (client_name or "").strip().lower()
    for prefix, fam in KNOWN_CLIENT_FAMILIES:
        if n.startswith(prefix):
            return fam, "client"
    return None, None


def _initialize(msg: dict, inst: config.Instance, announced: str | None = None) -> tuple[dict, session.Session]:
    params = msg.get("params") or {}
    requested = params.get("protocolVersion")
    version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    ci = params.get("clientInfo") or {}
    client = f"{ci.get('name', '?')} {ci.get('version', '')}".strip()
    family, source = client_family(announced, ci.get("name"))
    s = session.begin(inst.name, client, project_name(ci.get("cwd")), family=family, family_source=source)
    log(f"session {s.serial} started: instance {inst.name}, client {client}, protocol {version}"
        + (f", family {family} ({source})" if family else ""))
    return _answer(msg.get("id"), {
        "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "instructions": (f"VI memory, conversation {s.serial}, instance {inst.name}. Report vi_before before an action and vi_after "
                         "afterwards; vi_recall/vi_drilldown to look things up, vi_object reads one object completely. vi_learn with a source to learn: code, API tables and commands belong unabridged into the field content, otherwise memory has gaps.\n"
                         + _training_notice() + "\n"  # 0.57.0: early, clients cut long instructions
                         + tools.RULES + "\n"
                         + (tools.RULES_WITHOUT_TOKEN + "\n" if inst.name == config.OPEN else "") + self_model.hint()
                         + (f"\n{ix}" if (ix := index.text(inst.name)) else "")
                         + (f"\n{nt}" if (nt := _network_notice()) else ""))}), s  # 0.38.0: the memory index, like a MEMORY.md


def _training_notice() -> str:
    from . import learning
    try:
        return learning.training_notice()
    except Exception:  # noqa: BLE001 — a broken model object must never cost the initialize
        return ""



HEALTH_PATHS = ("/health", "/gesund")  # 0.59.1: English name first; the old one stays valid

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64  # Python's default of 5 is too small for many simultaneous clients

    def server_bind(self):
        # IP_FREEBIND: bind to an address that does not exist (yet) — e.g. the Docker gateway at boot,
        # before the network is created. Linux; without the option, it binds normally.
        if hasattr(socket, "IP_FREEBIND"):
            try:
                self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_FREEBIND, 1)
            except OSError:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        # a client that hangs up mid-request is not a server error; no traceback in the log for it (0.28.1)
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


# 0.38.2: only where the platform has Unix sockets. On Windows socketserver has no UnixStreamServer, and defining the class at import
# time broke `import vi_mcp.server` there — the MSI's server check failed and the installation rolled back (0.36.0–0.38.1).
LocalServer = None
if hasattr(socketserver, "UnixStreamServer"):
    class LocalServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        """0.36.0: HTTP on a Unix socket; who connects is told by the kernel, not by a token. Mode 0666: everyone may knock, only users in
        config `lokal` get in (Handler._check)."""
        daemon_threads = True
        request_queue_size = 64
        local = True

        def __init__(self, path: str, handler):
            p = Path(path)
            if p.is_socket():
                p.unlink()  # left over from a crash; a running second server would hold the port and fail before this
            super().__init__(path, handler)
            os.chmod(path, 0o666)

        def get_request(self):
            conn, _ = self.socket.accept()
            return conn, ("local", 0)  # BaseHTTPRequestHandler logs client_address[0]

        def server_close(self):
            super().server_close()
            try:
                Path(self.server_address).unlink()
            except OSError:
                pass

        handle_error = Server.handle_error


def peer_user(conn) -> str:
    """Name of the local user at the other end of a Unix socket (SO_PEERCRED; Linux)."""
    _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        return f"uid{uid}"


class Handler(BaseHTTPRequestHandler):
    k: config.Config  # set by the server
    protocol_version = "HTTP/1.1"
    server_version = f"vi-mcp/{__version__}"

    def log_message(self, fmt, *args):  # access log only on errors (see _send)
        pass

    def _send(self, code: int, req_body: dict | list | str | None = None, header: dict | None = None) -> None:
        data = b"" if req_body is None else (req_body.encode() if isinstance(req_body, str) else json.dumps(req_body, ensure_ascii=False).encode())
        self.send_response(code)
        if req_body is not None:
            self.send_header("Content-Type", "text/plain; charset=utf-8" if isinstance(req_body, str) else "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (header or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)
        if code >= 400:
            fwd = self.headers.get("X-Forwarded-For")
            from_ = self.client_address[0] + (f" for {fwd}" if fwd else "")
            log(f"{self.command} {self.path} → {code} ({from_}): {req_body if isinstance(req_body, str) else ''}"[:300])

    def _check(self) -> config.Instance | None:
        if getattr(self.server, "local", False):  # 0.36.0: local socket — the kernel names the user, no token
            user = peer_user(self.connection)
            name = self.k.local.get(user)
            inst = self.k.instances.get(name or "")
            if not inst:
                self._send(403, f"local user {user} has no instance on this socket" + (f" (instance {name!r} unknown)" if name else "")
                           + f" — an administrator allows it with: vi-mcp local {user} INSTANCE")
                return None
            return inst
        origin = self.headers.get("Origin")
        if origin and not any(origin == o or origin.startswith(o + ":") for o in self.k.origins):
            self._send(403, f"Origin {origin} not allowed")
            return None
        auth = self.headers.get("Authorization") or ""
        inst = self.k.instance_for(auth[7:].strip() if auth.lower().startswith("bearer ") else None)
        if not inst:
            self._send(401, "bearer token missing or wrong", {"WWW-Authenticate": 'Bearer realm="vi-mcp"'})
            return None
        return inst

    def do_GET(self):
        if self.path in HEALTH_PATHS:  # 0.59.1: /health, the German /gesund stays for monitors and older installers
            self._send(200, f"ok vi-mcp {__version__}\n")
        elif self.k.web and (self.path == "/web" or self.path.startswith(("/web/", "/web?"))):  # 0.46.0: read-only web page
            from . import web
            try:
                code, ctype, data, header = web.handle(self.path, self.client_address[0] if not self.headers.get("X-Forwarded-For")
                                                       else self.headers["X-Forwarded-For"].split(",")[0].strip(), self.k.web_base)
            except Exception as ex:  # noqa: BLE001 — a page error must not take the server down
                log(f"web {self.path}: {type(ex).__name__}: {ex}")
                code, ctype, data, header = 500, "text/plain; charset=utf-8", b"internal error (named in the server log)", {}
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for hk, hv in header.items():
                self.send_header(hk, hv)
            self.end_headers()
            self.wfile.write(data)
        elif self.k.web_internal and (self.path == "/intern" or self.path.startswith(("/intern/", "/intern?"))):  # 0.62.0
            self._internal("GET", b"")
        elif self.path.rstrip("/") == "/mcp":
            self._send(405, "GET is not supported: the server sends nothing on its own", {"Allow": "POST, DELETE"})
        else:
            self._send(404, "only /mcp, /health" + (" and /web" if self.k.web else "") + (" and /intern" if self.k.web_internal else ""))

    def _internal(self, method: str, body: bytes) -> None:
        """0.62.0: the internal knowledge search (web_internal.py) — its own sign-in, never the bearer token of /mcp."""
        from . import web_internal
        client = self.client_address[0] if not self.headers.get("X-Forwarded-For") else self.headers["X-Forwarded-For"].split(",")[0].strip()
        try:
            code, ctype, data, header = web_internal.handle(method, self.path, self.headers, body, client, self.k)
        except Exception as ex:  # noqa: BLE001 — a page error must not take the server down
            log(f"intern {self.path.split('?')[0]}: {type(ex).__name__}: {ex}")
            code, ctype, data, header = 500, "text/plain; charset=utf-8", b"internal error (named in the server log)", {}
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for hk, hv in header.items():
            self.send_header(hk, hv)
        self.end_headers()
        self.wfile.write(data)

    def do_DELETE(self):
        if self.path.rstrip("/") != "/mcp":
            return self._send(404, "only /mcp")
        inst = self._check()
        if not inst:
            return
        sid = self.headers.get("Mcp-Session-Id")
        s = session.find_without_touching(sid or "")
        if not s or s.instance != inst.name:
            return self._send(404, "session unknown")
        session.finish(s.id, "beendet")
        log(f"session {s.serial} ended (DELETE)")
        self._send(204)

    def _signal(self):
        """Signal of the user from the hook: correction or grade, never their text. Deliberately not an MCP tool."""
        inst = self._check()
        if not inst:
            return
        if not inst.human:
            return self._send(403, f"instance {inst.name} may not report signals")
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 4096:
            return self._send(400, "body missing or too large")
        try:
            d = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, "not JSON")
        s = session.find_without_touching(d.get("mcp_session_id") or "")
        if not s:
            return self._send(404, "session unknown")
        kind, grade = d.get("art"), d.get("note")
        if kind == "korrektur":
            s.signals.append({"zeit": g.now(), "art": "korrektur"})
        elif kind == "note" and isinstance(grade, (int, float)) and not isinstance(grade, bool) and 0 <= grade <= 1:
            s.signals.append({"zeit": g.now(), "art": "note", "note": grade})
            with session.on_behalf(s):
                scorer.human(s.serial, s.instance, float(grade))
        else:
            return self._send(400, "art must be korrektur or note (0–1)")
        self._send(204)

    def do_POST(self):
        if self.path.rstrip("/") == "/signal":
            return self._signal()
        if self.k.web_internal and (self.path in ("/intern/login", "/intern/logout")
                                    or (self.path.startswith("/intern/o/") and self.path.endswith("/gold"))):  # 0.62.0: forms, at most 4 KB
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4096:
                return self._send(413, "form too large")
            return self._internal("POST", self.rfile.read(n) if n > 0 else b"")
        if self.path.rstrip("/") != "/mcp":
            return self._send(404, "only /mcp and /signal")
        inst = self._check()
        if not inst:
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413 if length > MAX_BODY else 400, f"Content-Length {length} (allowed 1–{MAX_BODY})")
        try:
            message = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, _error(None, -32700, f"not JSON: {e}"))
        stack = message if isinstance(message, list) else [message]
        if not stack:
            return self._send(400, _error(None, -32600, "empty batch"))
        sid = self.headers.get("Mcp-Session-Id")
        init = [m for m in stack if isinstance(m, dict) and m.get("method") == "initialize"]
        if init:
            if len(stack) != 1:
                return self._send(400, _error(None, -32600, "initialize must come alone"))
            answer, s = _initialize(init[0], inst, self.headers.get("X-VI-Family"))
            return self._send(200, answer, {"Mcp-Session-Id": s.id})
        if not sid:
            return self._send(400, _error(None, -32600, "header Mcp-Session-Id missing — initialize first"))
        s = session.find(sid)
        if not s or s.instance != inst.name:
            return self._send(404, _error(None, -32001, "session unknown or ended — initialize again"))
        answers = [a for a in (process(m, s, inst) for m in stack) if a is not None]
        if not answers:
            return self._send(202)
        self._send(200, answers if isinstance(message, list) else answers[0], {"Mcp-Session-Id": s.id})


def _network_notice() -> str:
    """0.47.0: the public networks this server takes part in — the AI tells the user and switches off on request."""
    try:
        from . import p2p
        return p2p.notice()
    except Exception:  # noqa: BLE001 — a notice must never break initialize
        return ""


def _db_label(target) -> str:
    from . import db as dbmod
    return f"PostgreSQL {dbmod.redact(target)}" if dbmod.is_url(target) else str(target)


def build(k: config.Config) -> list[Server]:
    """One memory, one loop — one HTTP server per bind address, all in the same process."""
    if not k.instances:
        raise SystemExit(f"no instance configured ({config.fpath()}) — first: vi-mcp instance <name>")
    g.open_db(k.db)
    intuition.ttl_per_tool.clear()
    intuition.ttl_per_tool.update(k.ttl)
    n = len(reflexes.load_all())
    self_model.core()  # create the self if new (version 1 from the project rules)
    from . import archive, p2p, reviewer, reflection, vector
    archive.DAYS.update(k.archive_days)
    p2p.config = k.p2p
    anonymize.configure(k.p2p)
    reviewer.prompt_path = Path(k.reviewer_prompt) if k.reviewer_prompt else None
    vector.config = k.embed
    vector.rerank_config = k.rerank
    intuition.HOLD_BACK = k.hold_back  # 0.61.0
    reflection.config = k.llm
    handler = type("KHandler", (Handler,), {"k": k})
    srvs = [Server((addr, k.port), handler) for addr in k.bind]
    addresses = ", ".join(f"http://{s.server_address[0]}:{s.server_address[1]}/mcp" for s in srvs)
    if k.socket:  # 0.36.0
        if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED") or LocalServer is None:
            log(f"local socket {k.socket} not opened: it needs Linux (the user is taken from SO_PEERCRED)")
        else:
            try:
                srvs.append(LocalServer(k.socket, handler))
                addresses += f", local socket {k.socket} (users: {', '.join(f'{u}→{i}' for u, i in sorted(k.local.items())) or 'none allowed yet'})"
            except OSError as e:  # HTTP keeps working; the reason is named, the socket is not silently missing
                log(f"local socket {k.socket} not opened: {e} — HTTP is unaffected, vi-mcp stdio will not reach this service")
    log(f"vi-mcp {__version__} on {addresses} · memory {_db_label(k.db)} · {n} reflexes · "
        f"instances {', '.join(sorted(k.instances))} · loop every {main_loop.LOOP_S} s")
    return srvs


def finish(srvs) -> None:
    main_loop.stop_background()
    on_demand.stop_background()
    n = session.end_all("unterbrochen")
    g.close_db()
    log(f"stopped; {n} open conversation(s) saved as unterbrochen")


def main() -> None:
    k = config.load()
    srvs = build(k)
    main_loop.launch()
    on_demand.launch()
    for s in srvs[1:]:
        threading.Thread(target=s.serve_forever, name=f"http-{s.server_address if isinstance(s.server_address, str) else s.server_address[0]}", daemon=True).start()

    def _stop(*_a):
        def _all():
            for s in srvs:
                s.shutdown()
        threading.Thread(target=_all, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        srvs[0].serve_forever()
    finally:
        for s in srvs:
            s.server_close()
        finish(srvs)
