"""vi-p2p — der Netzdienst. Eigener Prozess, eigene Datenbank, kein Zugriff aufs Gedächtnis außer über das MCP-Werkzeugpaar für Ausgang und Eingang.

Modi: standalone (nichts läuft), peer (nur ausgehend), peerhost (nimmt auch Verbindungen an).
Runde: eigenes Wissen ins Logbuch → mit bis zu `nachbarn` Peers Stände abgleichen und Fehlendes holen → Neues ans Gedächtnis → Nachbarn anstoßen.
Peers finden sich über die Startliste und über `adresse`-Einträge in den Logbüchern. Jede Anfrage ist mit dem Schlüssel signiert, nur Mitglieder bekommen Antwort.
Einträge prüfen sich selbst; HTTPS und Torrent sind austauschbare Wege dorthin. Unverschlüsseltes HTTP nur auf dem eigenen Rechner oder mit `http_erlaubt`.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from hashlib import sha256 as _sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import logbook as lb
from .log_output import log

DEFAULT_PATH = "/etc/vi-p2p/config.json"
MODES = ("standalone", "peer", "peerhost")
TIME_WINDOW = 300
MAX_BODY = 1024 * 1024
REQUESTS_PER_MIN = 240
JOINS_PER_MIN = 10
CODE_PREFIX = "vinetz1."
PER_FETCH = 500
LOCAL = ("127.0.0.1", "localhost", "::1")


@dataclass
class NetConfig:
    mode: str = "standalone"
    db: str = "/var/lib/vi-p2p/netz.db"
    seed: str = "/var/lib/vi-p2p/schluessel"
    bind: str = "0.0.0.0"
    port: int = 8766
    address: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    ca_file: str | None = None
    founders: list = field(default_factory=list)
    startpeers: list = field(default_factory=list)
    tick_s: float = 300
    min_round_s: float = 5
    neighbors: int = 6
    http_allowed: bool = False
    believe: list = field(default_factory=lambda: ["*"])
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    mcp_token_file: str = "/etc/vi-p2p/mcp-token"
    torrent: dict = field(default_factory=dict)
    proxy: str | None = None
    no_proxy: list = field(default_factory=list)


def fpath() -> Path:
    return Path(os.environ.get("VI_P2P_CONFIG") or DEFAULT_PATH)


#: Keys of the config file (stored format, stays German so existing installations keep working) → NetConfig field.
#: Keys not listed here have the same name in file and dataclass.
FILE_KEYS = {"modus": "mode", "adresse": "address", "ca_datei": "ca_file", "gruender": "founders", "takt_s": "tick_s",
             "min_runde_s": "min_round_s", "nachbarn": "neighbors", "http_erlaubt": "http_allowed", "glauben": "believe",
             "mcp_token_datei": "mcp_token_file", "kein_proxy": "no_proxy"}


def from_file(d: dict) -> NetConfig:
    """NetConfig from the config file's dict. Accepts the stored German keys and the English field names;
    unknown keys are reported, not dropped silently."""
    fields = NetConfig.__dataclass_fields__
    kw, unknown = {}, []
    for key, value in d.items():
        name = FILE_KEYS.get(key, key)
        if name in fields:
            kw[name] = value
        else:
            unknown.append(key)
    if unknown:
        log(f"config: unknown keys ignored: {', '.join(sorted(unknown))}")
    return NetConfig(**kw)


def load(p: Path | None = None) -> NetConfig:
    p = p or fpath()
    d = json.loads(p.read_text()) if p.exists() else {}
    k = from_file(d)
    if k.mode not in MODES:
        raise ValueError(f"modus muss {', '.join(MODES)} sein")
    return k


def _sign(k, method: str, req_path: str, req_body: bytes) -> str:
    ts = str(int(time.time()))
    sig = k.sign("\n".join((method, req_path, ts, _sha256(req_body).hexdigest())).encode()).hex()
    return f"VI-Netz {lb.public_hex(k)} {ts} {sig}"


def check_header(value: str | None, method: str, req_path: str, req_body: bytes) -> str | None:
    """Öffentlicher Schlüssel des Absenders, wenn die Anfrage echt und frisch ist, sonst None."""
    parts = (value or "").split()
    if len(parts) != 4 or parts[0] != "VI-Netz" or not parts[2].isdigit() or abs(time.time() - int(parts[2])) > TIME_WINDOW:
        return None
    if not lb._HEX64.match(parts[1]):
        return None
    return parts[1] if lb.valid(parts[1], parts[3], "\n".join((method, req_path, parts[2], _sha256(req_body).hexdigest())).encode()) else None


class McpClient:
    """Das Gedächtnis aus Sicht des Netzdienstes: genau zwei Werkzeuge."""

    def __init__(self, url: str, token_file: str):
        self.url, self.token = url, Path(token_file).read_text().strip()
        self.op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _post(self, k: dict, sid: str | None = None):
        h = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {self.token}", **({"Mcp-Session-Id": sid} if sid else {})}
        with self.op.open(urllib.request.Request(self.url, data=json.dumps(k).encode(), headers=h), timeout=120) as a:
            return a.headers.get("Mcp-Session-Id"), json.loads(a.read() or b"{}")

    def _call_tool(self, name: str, args: dict) -> dict:
        sid, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "vi-p2p"}}})
        _, a = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}, sid)
        try:
            self.op.open(urllib.request.Request(self.url, headers={"Authorization": f"Bearer {self.token}", "Mcp-Session-Id": sid}, method="DELETE"), timeout=10).close()
        except (urllib.error.URLError, OSError):
            pass
        text = a["result"]["content"][0]["text"]
        if a["result"].get("isError"):
            raise ValueError(text[:200])
        return json.loads(text)

    def outbox(self) -> dict:
        return self._call_tool("vi_net_outbox", {})

    def inbox(self, entries: list[dict]) -> dict:
        return self._call_tool("vi_net_inbox", {"eintraege": entries})


class NetService:
    def __init__(self, k: NetConfig, mcp=None):
        self.k = k
        self.log = lb.Logbook(Path(k.db), Path(k.seed), k.founders)
        self.mcp = mcp
        for a in k.startpeers:
            self.log.peer_remember(a, "start")
        self.halt = threading.Event()
        self.awake = threading.Event()
        self.server: ThreadingHTTPServer | None = None
        self._round = threading.Lock()
        self._counter: dict[str, list[float]] = {}
        self._last_nudged = 0.0
        self.swarm = None
        self.usage_stats = {"runden": 0, "per_https": 0, "per_torrent": 0}
        if k.torrent.get("aktiv"):
            from . import net_torrent
            if net_torrent.available():
                self.swarm = net_torrent.Swarm(Path(k.torrent.get("verzeichnis") or Path(k.db).parent / "segmente"), int(k.torrent.get("port", 6881)), k.bind if k.mode == "peerhost" else "127.0.0.1")
                for sha, ti, file in self.log.segments_local():
                    self.swarm.parts(ti, Path(file))
            else:
                log("Netz: Torrent konfiguriert, aber python3-libtorrent fehlt; es bleibt bei HTTPS")

    # ---- Client ----

    def _allowed(self, address: str) -> bool:
        u = urllib.parse.urlsplit(address)
        return u.scheme == "https" or self.k.http_allowed or (u.hostname or "") in LOCAL

    def _proxy_for(self, host: str) -> tuple[str, int] | None:
        if not self.k.proxy or host in LOCAL or any(host == n.lstrip(".") or host.endswith("." + n.lstrip(".")) for n in self.k.no_proxy):
            return None
        u = urllib.parse.urlsplit(self.k.proxy)
        return u.hostname, u.port or 80

    def _request(self, address: str, method: str, req_path: str, data=None):
        """Signierte Anfrage. HTTPS prüft das Zertifikat über die CA oder, wenn ein Pin bekannt ist, über dessen SHA-256. HTTPS-Proxy per CONNECT."""
        if not self._allowed(address):
            raise ValueError("unverschlüsseltes HTTP zu einem fremden Rechner ist nicht erlaubt")
        req_body = json.dumps(data).encode() if data is not None else b""
        h = {"Authorization": _sign(self.log.k, method, req_path, req_body), "Content-Type": "application/json"}
        u = urllib.parse.urlsplit(address)
        host, https = u.hostname or "", u.scheme == "https"
        port = u.port or (443 if https else 80)
        proxy = self._proxy_for(host)
        pin = self.log.pin(address)
        try:
            if https:
                if pin:  # selbstsigniert: nicht die CA, sondern genau dieses Zertifikat zählt
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                else:
                    ctx = ssl.create_default_context(cafile=self.k.ca_file)
                c = http.client.HTTPSConnection(*(proxy or (host, port)), context=ctx, timeout=30)
                if proxy:
                    c.set_tunnel(host, port)
                c.connect()
                if pin and hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() != pin:
                    c.close()
                    raise ValueError("Zertifikat passt nicht zum bekannten Pin")
            else:
                c = http.client.HTTPConnection(host, port, timeout=30)
            try:
                c.request(method, u.path.rstrip("/") + req_path, body=req_body if method == "POST" else None, headers=h)
                r = c.getresponse()
                raw = r.read()
            finally:
                c.close()
        except http.client.HTTPException as e:
            raise ValueError(f"HTTP-Fehler: {type(e).__name__}") from e
        if r.status >= 400:
            try:
                reason = json.loads(raw).get("fehler", "")
            except (ValueError, AttributeError):
                reason = ""
            raise ValueError(f"HTTP {r.status}" + (f": {reason}" if reason else ""))
        return json.loads(raw) if raw else None

    def reconcile(self, address: str) -> int:
        """Mit einem Peer: Stände tauschen, Fehlendes holen. Neue Einladungen können weitere Herausgeber freischalten, darum mehrere Durchgänge."""
        new = 0
        try:
            for _ in range(4):
                foreign = self._request(address, "POST", "/netz/koepfe", {"koepfe": self.log.headers()})["koepfe"]
                own = self.log.headers()
                open_ = [(p, s) for p, s in foreign.items() if isinstance(s, int) and s > own.get(p, 0) and self.log.is_member(p)]
                if not open_:
                    break
                before = new
                for pub, target in sorted(open_, key=lambda x: x[0] not in self.k.founders):
                    new += self._torrent_reconcile(address, pub, own.get(pub, 0), target)
                    new += self._fetch(address, pub, target)
                if new == before:
                    break
            # Schieben, nicht nur holen: Ein Peer hinter einer Firewall wäre sonst nie zu lesen
            foreign = self._request(address, "POST", "/netz/koepfe", {"koepfe": self.log.headers()})["koepfe"]
            for pub, s in self.log.headers().items():
                if s > int(foreign.get(pub, 0)) and self.log.is_member(pub):
                    self._push(address, pub, int(foreign.get(pub, 0)))
            self.log.peer_result(address, True)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log(f"Netz: Abgleich mit {address}: {type(e).__name__}: {str(e)[:120]}")
            self.log.peer_result(address, False)
        return new

    def _fetch(self, address: str, pub: str, target: int) -> int:
        new = 0
        while True:
            from_seq = self.log.headers().get(pub, 0)
            if from_seq >= target:
                return new
            r = self.log.ingest(self._request(address, "GET", f"/netz/log/{pub}?ab={from_seq}&max={PER_FETCH}")["eintraege"])
            new += r["neu"]
            self.usage_stats["per_https"] += r["neu"]
            if r["neu"] == 0:
                if r["gruende"]:
                    log(f"Netz: von {address}: {'; '.join(r['gruende'])[:200]}")
                return new

    def _push(self, address: str, pub: str, from_seq: int) -> None:
        while True:
            entry_batch = self.log.read(pub, from_seq, PER_FETCH)
            if not entry_batch:
                return
            package, size = [], 0
            for e in entry_batch:
                n = len(json.dumps(e))
                if package and size + n > MAX_BODY * 3 // 4:
                    break
                package.append(e)
                size += n
            r = self._request(address, "POST", "/netz/eintraege", {"eintraege": package})
            if not r.get("neu") and not r.get("bekannt"):
                return
            from_seq = package[-1]["kopf"]["seq"]

    def _torrent_reconcile(self, address: str, pub: str, progress: int, target: int) -> int:
        if not self.swarm or target - progress < int(self.k.torrent.get("ab", 1000)):
            return 0
        new = 0
        try:
            segments = self._request(address, "GET", f"/netz/segmente/{pub}")["segmente"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return 0
        for s in segments:
            if s["von"] != self.log.headers().get(pub, 0) + 1:
                continue
            entries = self.swarm.fetch(s, urllib.parse.urlsplit(address).hostname, float(self.k.torrent.get("warte_s", 60)), self.log, pub)
            if entries is None:
                break
            r = self.log.ingest(entries)
            new += r["neu"]
            self.usage_stats["per_torrent"] += r["neu"]
        return new

    def build_segment(self) -> None:
        if not self.swarm or self.k.mode != "peerhost":
            return
        size, from_ = int(self.k.torrent.get("segment", 2000)), self.log.last_segment_until(self.log.pub) + 1
        if self.log.headers().get(self.log.pub, 0) - from_ + 1 < size:
            return
        self.swarm.build(self.log, self.log.pub, from_, from_ + size - 1)

    # ---- Runde ----

    def outbox(self) -> int:
        if not self.mcp:
            return 0
        try:
            a = self.mcp.outbox()
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
            log(f"Netz: Gedächtnis nicht erreichbar: {type(e).__name__}: {str(e)[:120]}")
            return 0
        known, revoke, new = self.log.own_objects(), self.log.own_revocations(), 0
        for o in a.get("objekte", []):
            if (o["netz_id"], lb.sha256(o)) not in known and o["netz_id"] not in revoke:
                self.log.attach("objekt", o, o["netz_id"], o["loesch_hash"])
                new += 1
        for w in a.get("widerrufe", []):
            if w["netz_id"] not in revoke:
                self.log.attach("widerruf", {"ziel": w["netz_id"], "token": w["token"]}, w["netz_id"])
                new += 1
        return new

    def inbox(self) -> None:
        if not self.mcp:
            return
        believes_all = "*" in self.k.believe
        for pub in self.log.headers():
            if pub == self.log.pub or not self.log.is_member(pub):
                continue
            while (entry_batch := self.log.new_since_checkpoint(pub)):
                believed = believes_all or pub in self.k.believe
                to_send = [e for e in entry_batch if e["inhalt"] is not None and (e["kopf"]["typ"] == "widerruf" or (believed and e["kopf"]["typ"] == "objekt"))]
                try:
                    if to_send:
                        self.mcp.inbox(to_send)
                except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
                    log(f"Netz: Eingang ins Gedächtnis gescheitert: {type(e).__name__}: {str(e)[:120]}")
                    return
                self.log.set_checkpoint(pub, entry_batch[-1]["kopf"]["seq"])

    def own_pin(self) -> str | None:
        """Nur ein selbst betriebenes TLS hat einen Pin; hinter einem Reverse-Proxy prüft die CA."""
        if not self.k.tls_cert:
            return None
        return certificate_pin(Path(self.k.tls_cert))

    def _report_address(self) -> int:
        if self.k.mode != "peerhost" or not self.k.address:
            return 0
        desired = {"adresse": self.k.address.rstrip("/"), **({"pin": p} if (p := self.own_pin()) else {})}
        if self.log.last_own_address() != desired:
            self.log.attach("adresse", desired)
            return 1
        return 0

    def nudge(self, peers: list[str]) -> None:
        for a in peers:
            try:
                self._request(a, "POST", "/netz/anstoss", {})
            except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
                pass

    def run_round(self) -> int:
        if not self._round.acquire(blocking=False):
            return 0
        try:
            new = self.outbox() + self._report_address()
            self.build_segment()
            excluding = self.k.address.rstrip("/") if self.k.address else None
            peers = self.log.choose_peers(self.k.neighbors, excluding)
            for a in peers:
                new += self.reconcile(a)
            self.inbox()
            self.usage_stats["runden"] += 1
            if new and time.time() - self._last_nudged >= self.k.min_round_s:
                self._last_nudged = time.time()
                self.nudge(peers)
            return new
        finally:
            self._round.release()

    def main_loop(self) -> None:
        while not self.halt.is_set():
            try:
                self.run_round()
            except Exception as e:  # eine fehlerhafte Runde darf den Dienst nicht beenden
                log(f"Netz: Runde gescheitert: {type(e).__name__}: {str(e)[:200]}")
            self.awake.wait(self.k.tick_s)
            self.awake.clear()
            self.halt.wait(self.k.min_round_s)

    # ---- Server ----

    def _limited(self, pub: str, bound: int = REQUESTS_PER_MIN) -> bool:
        now = time.time()
        z = [t for t in self._counter.get(pub, []) if now - t < 60]
        z.append(now)
        self._counter[pub] = z
        return len(z) > bound

    def _handler(self):
        service = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def _send(self, code: int, value=None):
                raw = json.dumps(value).encode() if value is not None else b""
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def _join(self, req_body: bytes):
                """Ohne Mitgliedschaft, aber mit Beweis des Schlüssels und einem einmaligen Code."""
                pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                if not pub:
                    return self._send(401, {"fehler": "Anfrage nicht signiert oder veraltet"})
                if service._limited("beitritt", JOINS_PER_MIN):
                    return self._send(429, {"fehler": "zu viele Beitrittsversuche"})
                try:
                    nonce = json.loads(req_body).get("code")
                except (ValueError, AttributeError):
                    nonce = None
                if reason := service.log.redeem_join(nonce, pub):
                    return self._send(403, {"fehler": reason})
                log(f"Netz: {lb.pseudonym(pub)} mit Beitrittscode eingeladen")
                service.awake.set()
                return self._send(200, {"eingeladen": lb.pseudonym(pub)})

            def _authenticate(self, req_body: bytes) -> str | None:
                pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                if not pub:
                    self._send(401, {"fehler": "Anfrage nicht signiert oder veraltet"})
                    return None
                if not service.log.is_member(pub):
                    self._send(403, {"fehler": "kein Mitglied dieses Netzes"})
                    return None
                if service._limited(pub):
                    self._send(429, {"fehler": "zu viele Anfragen"})
                    return None
                return pub

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path == "/netz/gesund":
                    return self._send(200, {"zustand": "ok"})
                if not self._authenticate(b""):
                    return None
                parts = u.path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["netz", "log"]:
                    q = urllib.parse.parse_qs(u.query)
                    try:
                        from_seq, n = int(q.get("ab", ["0"])[0]), int(q.get("max", [str(PER_FETCH)])[0])
                    except ValueError:
                        return self._send(400, {"fehler": "ab und max müssen Zahlen sein"})
                    return self._send(200, {"eintraege": service.log.read(parts[2], from_seq, min(n, PER_FETCH))})
                if len(parts) == 3 and parts[:2] == ["netz", "segmente"]:
                    return self._send(200, {"segmente": service.log.segments(parts[2])})
                return self._send(404, {"fehler": "unbekannt"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"fehler": "zu groß"})
                req_body = self.rfile.read(length)
                if self.path == "/netz/beitritt":
                    return self._join(req_body)
                if not self._authenticate(req_body):
                    return None
                if self.path == "/netz/koepfe":
                    return self._send(200, {"koepfe": service.log.headers()})
                if self.path == "/netz/eintraege":
                    r = service.log.ingest(json.loads(req_body).get("eintraege"))
                    if r["neu"]:
                        service.awake.set()
                    return self._send(200, r)
                if self.path == "/netz/anstoss":
                    service.awake.set()
                    return self._send(204)
                return self._send(404, {"fehler": "unbekannt"})
        return H

    def start_server(self) -> None:
        self.server = ThreadingHTTPServer((self.k.bind, self.k.port), self._handler())
        self.server.daemon_threads = True
        if self.k.tls_cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.k.tls_cert, self.k.tls_key)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, name="vi-p2p-http", daemon=True).start()

    def port(self) -> int:
        return self.server.server_address[1]

    def stop_service(self) -> None:
        self.halt.set()
        self.awake.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.swarm:
            self.swarm.stop_service()
        self.log.close()


def certificate_pin(req_path: Path) -> str:
    """SHA-256 des Zertifikats in DER-Form, wie es der Peer beim Verbindungsaufbau sieht."""
    pem = req_path.read_text()
    part = pem[pem.index("-----BEGIN CERTIFICATE-----"):pem.index("-----END CERTIFICATE-----")]
    return hashlib.sha256(base64.b64decode("".join(part.splitlines()[1:]))).hexdigest()


def build_code(founders: list[str], start: str, pin: str | None, nonce: str, expiry: float) -> str:
    raw = json.dumps({"g": founders, "s": start, "p": pin, "n": nonce, "a": int(expiry)}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_code(code: str) -> dict:
    """Rein. ValueError mit Grund, wenn der Code nicht passt."""
    code = (code or "").strip()
    if not code.startswith(CODE_PREFIX):
        raise ValueError("kein Beitrittscode (beginnt nicht mit vinetz1.)")
    try:
        d = json.loads(base64.urlsafe_b64decode(code[len(CODE_PREFIX):] + "=" * (-len(code) % 4)))
    except (ValueError, TypeError) as e:
        raise ValueError("Beitrittscode ist beschädigt") from e
    if not isinstance(d, dict) or not isinstance(d.get("g"), list) or not all(isinstance(x, str) and lb._HEX64.match(x) for x in d["g"]) or not d["g"]:
        raise ValueError("Beitrittscode nennt keine gültigen Gründer")
    if not isinstance(d.get("s"), str) or not lb._ADDRESS.match(d["s"]) or not isinstance(d.get("n"), str):
        raise ValueError("Beitrittscode nennt keine gültige Adresse")
    if d.get("p") is not None and not (isinstance(d["p"], str) and lb._HEX64.match(d["p"])):
        raise ValueError("Beitrittscode hat einen unbrauchbaren Pin")
    if not isinstance(d.get("a"), int) or d["a"] < time.time():
        raise ValueError("Beitrittscode ist abgelaufen")
    return d


def main() -> int:
    k = load()
    if k.mode == "standalone":
        log("Netz: Modus standalone, nichts zu tun")
        return 0
    if not k.founders:
        log("Netz: keine Gründer konfiguriert (vi-mcp netz einrichten)")
        return 2
    d = NetService(k, McpClient(k.mcp_url, k.mcp_token_file))
    if k.mode == "peerhost":
        d.start_server()
    import signal
    signal.signal(signal.SIGUSR1, lambda *_: d.awake.set())  # systemctl kill -s USR1 vi-p2p: Runde sofort
    log(f"Netz: Modus {k.mode}, Pseudonym {lb.pseudonym(d.log.pub)}, {len(d.log.members())} Mitglieder bekannt")
    try:
        d.main_loop()
    except KeyboardInterrupt:
        pass
    return 0
