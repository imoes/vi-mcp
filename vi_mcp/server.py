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

from . import __version__
from . import gedaechtnis as g
from . import intuition, konfig, reflexe, schleife, selbst, sitzung, werkzeuge
from .protokoll import log

PROTOKOLLE = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_KOERPER = 8 * 1024 * 1024
SERVER_NAME = "vi-mcp"


def _antwort(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _fehler(mid, code: int, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}


def verarbeite(msg: dict, s: sitzung.Sitzung | None, inst: konfig.Instanz) -> dict | None:
    """Eine JSON-RPC-Nachricht im Auftrag einer Sitzung. None = keine Antwort (Notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _fehler(None, -32600, "Ungültige Anfrage: JSON-RPC 2.0 erwartet")
    methode, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if methode is None:
        return None  # Response des Clients auf eine Server-Anfrage — die VI stellt keine
    if mid is None:
        return None  # Notification (z. B. notifications/initialized)
    with sitzung.im_auftrag(s):
        try:
            if methode == "ping":
                return _antwort(mid, {})
            if methode == "tools/list":
                return _antwort(mid, {"tools": werkzeuge.liste()})
            if methode == "tools/call":
                name = params.get("name", "")
                if not werkzeuge.bekannt(name):
                    return _fehler(mid, -32602, f"Werkzeug unbekannt: {name}")
                t0 = time.monotonic()
                try:
                    text = werkzeuge.rufe(name, params.get("arguments") or {}, inst.name, inst.reflexe)
                    return _antwort(mid, {"content": [{"type": "text", "text": text}], "isError": False})
                except werkzeuge.Abgelehnt as e:
                    return _antwort(mid, {"content": [{"type": "text", "text": f"abgelehnt: {e}"}], "isError": True})
                except Exception as e:  # noqa: BLE001 — Werkzeugfehler, benannt an den Client
                    log(f"{name} scheiterte nach {int((time.monotonic() - t0) * 1000)} ms: {type(e).__name__}: {e}")
                    return _antwort(mid, {"content": [{"type": "text", "text": f"{name}: {type(e).__name__}: {e}"}], "isError": True})
            return _fehler(mid, -32601, f"Methode unbekannt: {methode}")
        except Exception as e:  # noqa: BLE001
            log(f"interner Fehler bei {methode}: {type(e).__name__}: {e}")
            return _fehler(mid, -32603, f"interner Fehler: {type(e).__name__}: {e}")


def _initialize(msg: dict, inst: konfig.Instanz) -> tuple[dict, sitzung.Sitzung]:
    params = msg.get("params") or {}
    gewuenscht = params.get("protocolVersion")
    version = gewuenscht if gewuenscht in PROTOKOLLE else PROTOKOLLE[0]
    ci = params.get("clientInfo") or {}
    client = f"{ci.get('name', '?')} {ci.get('version', '')}".strip()
    s = sitzung.beginne(inst.name, client)
    log(f"Sitzung {s.serial} begonnen: Instanz {inst.name}, Client {client}, Protokoll {version}")
    return _antwort(msg.get("id"), {
        "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "instructions": (f"VI-Gedächtnis, Gespräch {s.serial}, Instanz {inst.name}. Vor einer Handlung vi_vorher, danach vi_nachher "
                         "melden; vi_erinnere/vi_vertiefe zum Nachlesen, vi_lerne mit Quelle zum Lernen.\n"
                         + selbst.hinweis())}), s


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
    k: konfig.Konfig  # vom Server gesetzt
    protocol_version = "HTTP/1.1"
    server_version = f"vi-mcp/{__version__}"

    def log_message(self, fmt, *args):  # Zugriffsprotokoll nur bei Fehlern (siehe _sende)
        pass

    def _sende(self, code: int, koerper: dict | list | str | None = None, kopf: dict | None = None) -> None:
        daten = b"" if koerper is None else (koerper.encode() if isinstance(koerper, str) else json.dumps(koerper, ensure_ascii=False).encode())
        self.send_response(code)
        if koerper is not None:
            self.send_header("Content-Type", "text/plain; charset=utf-8" if isinstance(koerper, str) else "application/json")
        self.send_header("Content-Length", str(len(daten)))
        for k, v in (kopf or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if daten:
            self.wfile.write(daten)
        if code >= 400:
            fwd = self.headers.get("X-Forwarded-For")
            von = self.client_address[0] + (f" für {fwd}" if fwd else "")
            log(f"{self.command} {self.path} → {code} ({von}): {koerper if isinstance(koerper, str) else ''}"[:300])

    def _pruefe(self) -> konfig.Instanz | None:
        origin = self.headers.get("Origin")
        if origin and not any(origin == o or origin.startswith(o + ":") for o in self.k.origins):
            self._sende(403, f"Origin {origin} nicht erlaubt")
            return None
        auth = self.headers.get("Authorization") or ""
        inst = self.k.instanz_zu(auth[7:].strip() if auth.lower().startswith("bearer ") else None)
        if not inst:
            self._sende(401, "Bearer-Token fehlt oder ist falsch", {"WWW-Authenticate": 'Bearer realm="vi-mcp"'})
            return None
        return inst

    def do_GET(self):
        if self.path == "/gesund":
            self._sende(200, f"ok vi-mcp {__version__}\n")
        elif self.path.rstrip("/") == "/mcp":
            self._sende(405, "GET wird nicht unterstützt: der Server sendet nichts von sich aus", {"Allow": "POST, DELETE"})
        else:
            self._sende(404, "nur /mcp und /gesund")

    def do_DELETE(self):
        if self.path.rstrip("/") != "/mcp":
            return self._sende(404, "nur /mcp")
        inst = self._pruefe()
        if not inst:
            return
        sid = self.headers.get("Mcp-Session-Id")
        s = sitzung.finde_ohne_beruehren(sid or "")
        if not s or s.instanz != inst.name:
            return self._sende(404, "Sitzung unbekannt")
        sitzung.beende(s.id, "beendet")
        log(f"Sitzung {s.serial} beendet (DELETE)")
        self._sende(204)

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            return self._sende(404, "nur /mcp")
        inst = self._pruefe()
        if not inst:
            return
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge <= 0 or laenge > MAX_KOERPER:
            return self._sende(413 if laenge > MAX_KOERPER else 400, f"Content-Length {laenge} (erlaubt 1–{MAX_KOERPER})")
        try:
            nachricht = json.loads(self.rfile.read(laenge))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._sende(400, _fehler(None, -32700, f"kein JSON: {e}"))
        stapel = nachricht if isinstance(nachricht, list) else [nachricht]
        if not stapel:
            return self._sende(400, _fehler(None, -32600, "leerer Stapel"))
        sid = self.headers.get("Mcp-Session-Id")
        init = [m for m in stapel if isinstance(m, dict) and m.get("method") == "initialize"]
        if init:
            if len(stapel) != 1:
                return self._sende(400, _fehler(None, -32600, "initialize muss allein kommen"))
            antwort, s = _initialize(init[0], inst)
            return self._sende(200, antwort, {"Mcp-Session-Id": s.id})
        if not sid:
            return self._sende(400, _fehler(None, -32600, "Header Mcp-Session-Id fehlt — erst initialize"))
        s = sitzung.finde(sid)
        if not s or s.instanz != inst.name:
            return self._sende(404, _fehler(None, -32001, "Sitzung unbekannt oder beendet — neu initialisieren"))
        antworten = [a for a in (verarbeite(m, s, inst) for m in stapel) if a is not None]
        if not antworten:
            return self._sende(202)
        self._sende(200, antworten if isinstance(nachricht, list) else antworten[0], {"Mcp-Session-Id": s.id})


def baue(k: konfig.Konfig) -> list[Server]:
    """Ein Gedächtnis, ein Loop — ein HTTP-Server je Bind-Adresse, alle im selben Prozess."""
    if not k.instanzen:
        raise SystemExit(f"keine Instanz konfiguriert ({konfig.pfad()}) — erst: vi-mcp instanz <name>")
    g.oeffne(k.db)
    intuition.ttl_je_werkzeug.clear()
    intuition.ttl_je_werkzeug.update(k.ttl)
    n = len(reflexe.lade_alle())
    selbst.kern()  # Selbst anlegen, falls neu (Version 1 aus den Projektregeln)
    from . import lager, reflexion, vektor
    lager.TAGE.update(k.lager_tage)
    vektor.konfig = k.embed
    reflexion.konfig = k.llm
    handler = type("KHandler", (Handler,), {"k": k})
    srvs = [Server((adr, k.port), handler) for adr in k.bind]
    adressen = ", ".join(f"http://{s.server_address[0]}:{s.server_address[1]}/mcp" for s in srvs)
    log(f"vi-mcp {__version__} auf {adressen} · Gedächtnis {k.db} · {n} Reflexe · "
        f"Instanzen {', '.join(sorted(k.instanzen))} · Loop alle {schleife.LOOP_S} s")
    return srvs


def beende(srvs) -> None:
    schleife.halte()
    n = sitzung.alle_beenden("unterbrochen")
    g.schliesse()
    log(f"beendet; {n} offene Gespräch(e) als unterbrochen gesichert")


def main() -> None:
    k = konfig.lade()
    srvs = baue(k)
    schleife.starte()
    for s in srvs[1:]:
        threading.Thread(target=s.serve_forever, name=f"http-{s.server_address[0]}", daemon=True).start()

    def _stopp(*_a):
        def _alle():
            for s in srvs:
                s.shutdown()
        threading.Thread(target=_alle, daemon=True).start()

    signal.signal(signal.SIGTERM, _stopp)
    signal.signal(signal.SIGINT, _stopp)
    try:
        srvs[0].serve_forever()
    finally:
        for s in srvs:
            s.server_close()
        beende(srvs)
