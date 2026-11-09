"""MCP über Streamable HTTP — EIN Prozess, viele Sitzungen.

Endpunkt `/mcp` (MCP-Spezifikation „Streamable HTTP“, https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):
  POST   JSON-RPC-Nachricht oder -Stapel → Antwort als application/json (kein SSE nötig, die VI streamt nicht);
         nur Notifications/Responses → 202 ohne Inhalt.
  GET    405 — der Server sendet nichts von sich aus.
  DELETE beendet die Sitzung (Gespräch wird gesichert, Zustand `beendet`).
Sitzung: `initialize` vergibt `Mcp-Session-Id`; jede weitere Anfrage braucht sie (fehlt → 400, unbekannt → 404).
Schutz: Bearer-Token je Instanz (401 ohne/mit falschem Token), Origin-Prüfung gegen DNS-Rebinding (403),
Bind standardmäßig 127.0.0.1; mehrere Adressen möglich (z. B. zusätzlich das Gateway eines Docker-Netzes, über
das ein Reverse-Proxy im Container zugreift) — alle teilen denselben Prozess, dasselbe Gedächtnis.
Zusätzlich `GET /gesund` ohne Anmeldung: nur „ok“ + Version, für systemd/Monitoring.
"""
from __future__ import annotations

import json
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import memory as g
from . import anonymize, on_demand, intuition, config, reflexes, main_loop, scorer, self_model, session, usage_stats, tools
from .log_output import log

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 8 * 1024 * 1024
SERVER_NAME = "vi-mcp"


def _answer(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}


def process(msg: dict, s: session.Session | None, inst: config.Instance) -> dict | None:
    """Eine JSON-RPC-Nachricht im Auftrag einer Sitzung. None = keine Antwort (Notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Ungültige Anfrage: JSON-RPC 2.0 erwartet")
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method is None:
        return None  # Response des Clients auf eine Server-Anfrage — die VI stellt keine
    if mid is None:
        return None  # Notification (z. B. notifications/initialized)
    with session.on_behalf(s):
        try:
            if method == "ping":
                return _answer(mid, {})
            if method == "tools/list":
                return _answer(mid, {"tools": tools.listing(inst.name)})
            if method == "tools/call":
                name = params.get("name", "")
                if not tools.known(name):
                    return _error(mid, -32602, f"Werkzeug unbekannt: {name}")
                t0 = time.monotonic()
                client = s.client if s else None
                public = tools.api_en.canonical_name(name)  # Statistik einheitlich mit dem öffentlichen (englischen) Namen
                ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
                try:
                    text = tools.call_tool(name, params.get("arguments") or {}, inst.name, inst.reflexes, inst.release)
                    usage_stats.record(inst.name, client, public, "ok", ms(), text)
                    return _answer(mid, {"content": [{"type": "text", "text": text}], "isError": False})
                except tools.Rejected as e:
                    usage_stats.record(inst.name, client, public, "abgelehnt", ms())
                    return _answer(mid, {"content": [{"type": "text", "text": f"abgelehnt: {e}"}], "isError": True})
                except Exception as e:  # noqa: BLE001 — Werkzeugfehler, benannt an den Client
                    log(f"{name} scheiterte nach {ms()} ms: {type(e).__name__}: {e}")
                    usage_stats.record(inst.name, client, public, "fehler", ms())
                    return _answer(mid, {"content": [{"type": "text", "text": f"{name}: {type(e).__name__}: {e}"}], "isError": True})
            return _error(mid, -32601, f"Methode unbekannt: {method}")
        except Exception as e:  # noqa: BLE001
            log(f"interner Fehler bei {method}: {type(e).__name__}: {e}")
            return _error(mid, -32603, f"interner Fehler: {type(e).__name__}: {e}")


def _initialize(msg: dict, inst: config.Instance) -> tuple[dict, session.Session]:
    params = msg.get("params") or {}
    requested = params.get("protocolVersion")
    version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    ci = params.get("clientInfo") or {}
    client = f"{ci.get('name', '?')} {ci.get('version', '')}".strip()
    s = session.begin(inst.name, client)
    log(f"Sitzung {s.serial} begonnen: Instanz {inst.name}, Client {client}, Protokoll {version}")
    return _answer(msg.get("id"), {
        "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "instructions": (f"VI memory, conversation {s.serial}, instance {inst.name}. Report vi_before before an action and vi_after "
                         "afterwards; vi_recall/vi_drilldown to look things up, vi_object reads one object completely. vi_learn with a source to learn: code, API tables and commands belong unabridged into the field content, otherwise memory has gaps.\n"
                         + tools.RULES + "\n"
                         + (tools.RULES_WITHOUT_TOKEN + "\n" if inst.name == config.OPEN else "") + self_model.hint())}), s


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64  # Python-Vorgabe 5 ist für viele gleichzeitige Clients zu knapp

    def server_bind(self):
        # IP_FREEBIND: an eine Adresse binden, die (noch) nicht existiert — z. B. das Docker-Gateway beim Booten,
        # bevor das Netz angelegt ist. Linux; fehlt die Option, wird normal gebunden.
        if hasattr(socket, "IP_FREEBIND"):
            try:
                self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_FREEBIND, 1)
            except OSError:
                pass
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    k: config.Config  # vom Server gesetzt
    protocol_version = "HTTP/1.1"
    server_version = f"vi-mcp/{__version__}"

    def log_message(self, fmt, *args):  # Zugriffsprotokoll nur bei Fehlern (siehe _sende)
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
            from_ = self.client_address[0] + (f" für {fwd}" if fwd else "")
            log(f"{self.command} {self.path} → {code} ({from_}): {req_body if isinstance(req_body, str) else ''}"[:300])

    def _check(self) -> config.Instance | None:
        origin = self.headers.get("Origin")
        if origin and not any(origin == o or origin.startswith(o + ":") for o in self.k.origins):
            self._send(403, f"Origin {origin} nicht erlaubt")
            return None
        auth = self.headers.get("Authorization") or ""
        inst = self.k.instance_for(auth[7:].strip() if auth.lower().startswith("bearer ") else None)
        if not inst:
            self._send(401, "Bearer-Token fehlt oder ist falsch", {"WWW-Authenticate": 'Bearer realm="vi-mcp"'})
            return None
        return inst

    def do_GET(self):
        if self.path == "/gesund":
            self._send(200, f"ok vi-mcp {__version__}\n")
        elif self.path.rstrip("/") == "/mcp":
            self._send(405, "GET wird nicht unterstützt: der Server sendet nichts von sich aus", {"Allow": "POST, DELETE"})
        else:
            self._send(404, "nur /mcp und /gesund")

    def do_DELETE(self):
        if self.path.rstrip("/") != "/mcp":
            return self._send(404, "nur /mcp")
        inst = self._check()
        if not inst:
            return
        sid = self.headers.get("Mcp-Session-Id")
        s = session.find_without_touching(sid or "")
        if not s or s.instance != inst.name:
            return self._send(404, "Sitzung unbekannt")
        session.finish(s.id, "beendet")
        log(f"Sitzung {s.serial} beendet (DELETE)")
        self._send(204)

    def _signal(self):
        """Signal des Nutzers aus dem Hook: Korrektur oder Note, nie sein Text. Bewusst kein MCP-Werkzeug."""
        inst = self._check()
        if not inst:
            return
        if not inst.human:
            return self._send(403, f"Instanz {inst.name} darf keine Signale melden")
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 4096:
            return self._send(400, "Körper fehlt oder ist zu groß")
        try:
            d = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, "kein JSON")
        s = session.find_without_touching(d.get("mcp_session_id") or "")
        if not s:
            return self._send(404, "Sitzung unbekannt")
        kind, grade = d.get("art"), d.get("note")
        if kind == "korrektur":
            s.signals.append({"zeit": g.now(), "art": "korrektur"})
        elif kind == "note" and isinstance(grade, (int, float)) and not isinstance(grade, bool) and 0 <= grade <= 1:
            s.signals.append({"zeit": g.now(), "art": "note", "note": grade})
            with session.on_behalf(s):
                scorer.human(s.serial, s.instance, float(grade))
        else:
            return self._send(400, "art muss korrektur oder note (0–1) sein")
        self._send(204)

    def do_POST(self):
        if self.path.rstrip("/") == "/signal":
            return self._signal()
        if self.path.rstrip("/") != "/mcp":
            return self._send(404, "nur /mcp und /signal")
        inst = self._check()
        if not inst:
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413 if length > MAX_BODY else 400, f"Content-Length {length} (erlaubt 1–{MAX_BODY})")
        try:
            message = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, _error(None, -32700, f"kein JSON: {e}"))
        stack = message if isinstance(message, list) else [message]
        if not stack:
            return self._send(400, _error(None, -32600, "leerer Stapel"))
        sid = self.headers.get("Mcp-Session-Id")
        init = [m for m in stack if isinstance(m, dict) and m.get("method") == "initialize"]
        if init:
            if len(stack) != 1:
                return self._send(400, _error(None, -32600, "initialize muss allein kommen"))
            answer, s = _initialize(init[0], inst)
            return self._send(200, answer, {"Mcp-Session-Id": s.id})
        if not sid:
            return self._send(400, _error(None, -32600, "Header Mcp-Session-Id fehlt — erst initialize"))
        s = session.find(sid)
        if not s or s.instance != inst.name:
            return self._send(404, _error(None, -32001, "Sitzung unbekannt oder beendet — neu initialisieren"))
        answers = [a for a in (process(m, s, inst) for m in stack) if a is not None]
        if not answers:
            return self._send(202)
        self._send(200, answers if isinstance(message, list) else answers[0], {"Mcp-Session-Id": s.id})


def build(k: config.Config) -> list[Server]:
    """Ein Gedächtnis, ein Loop — ein HTTP-Server je Bind-Adresse, alle im selben Prozess."""
    if not k.instances:
        raise SystemExit(f"keine Instanz konfiguriert ({config.fpath()}) — erst: vi-mcp instanz <name>")
    g.open_db(k.db)
    intuition.ttl_per_tool.clear()
    intuition.ttl_per_tool.update(k.ttl)
    n = len(reflexes.load_all())
    self_model.core()  # Selbst anlegen, falls neu (Version 1 aus den Projektregeln)
    from . import archive, p2p, reviewer, reflection, vector
    archive.DAYS.update(k.archive_days)
    p2p.config = k.p2p
    anonymize.configure(k.p2p)
    reviewer.prompt_path = Path(k.reviewer_prompt) if k.reviewer_prompt else None
    vector.config = k.embed
    reflection.config = k.llm
    handler = type("KHandler", (Handler,), {"k": k})
    srvs = [Server((addr, k.port), handler) for addr in k.bind]
    addresses = ", ".join(f"http://{s.server_address[0]}:{s.server_address[1]}/mcp" for s in srvs)
    log(f"vi-mcp {__version__} auf {addresses} · Gedächtnis {k.db} · {n} Reflexe · "
        f"Instanzen {', '.join(sorted(k.instances))} · Loop alle {main_loop.LOOP_S} s")
    return srvs


def finish(srvs) -> None:
    main_loop.stop_background()
    on_demand.stop_background()
    n = session.end_all("unterbrochen")
    g.close_db()
    log(f"beendet; {n} offene Gespräch(e) als unterbrochen gesichert")


def main() -> None:
    k = config.load()
    srvs = build(k)
    main_loop.launch()
    on_demand.launch()
    for s in srvs[1:]:
        threading.Thread(target=s.serve_forever, name=f"http-{s.server_address[0]}", daemon=True).start()

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
