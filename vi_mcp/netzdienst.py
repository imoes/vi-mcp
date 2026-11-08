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

from . import logbuch as lb
from .protokoll import log

STANDARD_PFAD = "/etc/vi-p2p/config.json"
MODI = ("standalone", "peer", "peerhost")
ZEIT_FENSTER = 300
MAX_KOERPER = 1024 * 1024
ANFRAGEN_JE_MIN = 240
BEITRITTE_JE_MIN = 10
CODE_PRAEFIX = "vinetz1."
JE_ABRUF = 500
LOKAL = ("127.0.0.1", "localhost", "::1")


@dataclass
class NetzKonfig:
    modus: str = "standalone"
    db: str = "/var/lib/vi-p2p/netz.db"
    seed: str = "/var/lib/vi-p2p/schluessel"
    bind: str = "0.0.0.0"
    port: int = 8766
    adresse: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    ca_datei: str | None = None
    gruender: list = field(default_factory=list)
    startpeers: list = field(default_factory=list)
    takt_s: float = 300
    min_runde_s: float = 5
    nachbarn: int = 6
    http_erlaubt: bool = False
    glauben: list = field(default_factory=lambda: ["*"])
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    mcp_token_datei: str = "/etc/vi-p2p/mcp-token"
    torrent: dict = field(default_factory=dict)
    proxy: str | None = None
    kein_proxy: list = field(default_factory=list)


def pfad() -> Path:
    return Path(os.environ.get("VI_P2P_CONFIG") or STANDARD_PFAD)


def lade(p: Path | None = None) -> NetzKonfig:
    p = p or pfad()
    d = json.loads(p.read_text()) if p.exists() else {}
    k = NetzKonfig(**{a: b for a, b in d.items() if a in NetzKonfig.__dataclass_fields__})
    if k.modus not in MODI:
        raise ValueError(f"modus muss {', '.join(MODI)} sein")
    return k


def _signiere(k, methode: str, pfad_: str, koerper: bytes) -> str:
    zeit = str(int(time.time()))
    sig = k.sign("\n".join((methode, pfad_, zeit, _sha256(koerper).hexdigest())).encode()).hex()
    return f"VI-Netz {lb.oeffentlich_hex(k)} {zeit} {sig}"


def pruefe_kopf(wert: str | None, methode: str, pfad_: str, koerper: bytes) -> str | None:
    """Öffentlicher Schlüssel des Absenders, wenn die Anfrage echt und frisch ist, sonst None."""
    teile = (wert or "").split()
    if len(teile) != 4 or teile[0] != "VI-Netz" or not teile[2].isdigit() or abs(time.time() - int(teile[2])) > ZEIT_FENSTER:
        return None
    if not lb._HEX64.match(teile[1]):
        return None
    return teile[1] if lb.gueltig(teile[1], teile[3], "\n".join((methode, pfad_, teile[2], _sha256(koerper).hexdigest())).encode()) else None


class McpKlient:
    """Das Gedächtnis aus Sicht des Netzdienstes: genau zwei Werkzeuge."""

    def __init__(self, url: str, token_datei: str):
        self.url, self.token = url, Path(token_datei).read_text().strip()
        self.op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _post(self, k: dict, sid: str | None = None):
        h = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {self.token}", **({"Mcp-Session-Id": sid} if sid else {})}
        with self.op.open(urllib.request.Request(self.url, data=json.dumps(k).encode(), headers=h), timeout=120) as a:
            return a.headers.get("Mcp-Session-Id"), json.loads(a.read() or b"{}")

    def _rufe(self, name: str, args: dict) -> dict:
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

    def ausgang(self) -> dict:
        return self._rufe("vi_netz_ausgang", {})

    def eingang(self, eintraege: list[dict]) -> dict:
        return self._rufe("vi_netz_eingang", {"eintraege": eintraege})


class Netzdienst:
    def __init__(self, k: NetzKonfig, mcp=None):
        self.k = k
        self.log = lb.Logbuch(Path(k.db), Path(k.seed), k.gruender)
        self.mcp = mcp
        for a in k.startpeers:
            self.log.peer_merken(a, "start")
        self.halt = threading.Event()
        self.wach = threading.Event()
        self.server: ThreadingHTTPServer | None = None
        self._runde = threading.Lock()
        self._zaehler: dict[str, list[float]] = {}
        self._zuletzt_angestossen = 0.0
        self.schwarm = None
        self.statistik = {"runden": 0, "per_https": 0, "per_torrent": 0}
        if k.torrent.get("aktiv"):
            from . import netz_torrent
            if netz_torrent.verfuegbar():
                self.schwarm = netz_torrent.Schwarm(Path(k.torrent.get("verzeichnis") or Path(k.db).parent / "segmente"), int(k.torrent.get("port", 6881)), k.bind if k.modus == "peerhost" else "127.0.0.1")
                for sha, ti, datei in self.log.segmente_lokal():
                    self.schwarm.teile(ti, Path(datei))
            else:
                log("Netz: Torrent konfiguriert, aber python3-libtorrent fehlt; es bleibt bei HTTPS")

    # ---- Client ----

    def _erlaubt(self, adresse: str) -> bool:
        u = urllib.parse.urlsplit(adresse)
        return u.scheme == "https" or self.k.http_erlaubt or (u.hostname or "") in LOKAL

    def _proxy_fuer(self, host: str) -> tuple[str, int] | None:
        if not self.k.proxy or host in LOKAL or any(host == n.lstrip(".") or host.endswith("." + n.lstrip(".")) for n in self.k.kein_proxy):
            return None
        u = urllib.parse.urlsplit(self.k.proxy)
        return u.hostname, u.port or 80

    def _anfrage(self, adresse: str, methode: str, pfad_: str, daten=None):
        """Signierte Anfrage. HTTPS prüft das Zertifikat über die CA oder, wenn ein Pin bekannt ist, über dessen SHA-256. HTTPS-Proxy per CONNECT."""
        if not self._erlaubt(adresse):
            raise ValueError("unverschlüsseltes HTTP zu einem fremden Rechner ist nicht erlaubt")
        koerper = json.dumps(daten).encode() if daten is not None else b""
        h = {"Authorization": _signiere(self.log.k, methode, pfad_, koerper), "Content-Type": "application/json"}
        u = urllib.parse.urlsplit(adresse)
        host, https = u.hostname or "", u.scheme == "https"
        port = u.port or (443 if https else 80)
        proxy = self._proxy_fuer(host)
        pin = self.log.pin(adresse)
        try:
            if https:
                if pin:  # selbstsigniert: nicht die CA, sondern genau dieses Zertifikat zählt
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                else:
                    ctx = ssl.create_default_context(cafile=self.k.ca_datei)
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
                c.request(methode, u.path.rstrip("/") + pfad_, body=koerper if methode == "POST" else None, headers=h)
                r = c.getresponse()
                roh = r.read()
            finally:
                c.close()
        except http.client.HTTPException as e:
            raise ValueError(f"HTTP-Fehler: {type(e).__name__}") from e
        if r.status >= 400:
            try:
                grund = json.loads(roh).get("fehler", "")
            except (ValueError, AttributeError):
                grund = ""
            raise ValueError(f"HTTP {r.status}" + (f": {grund}" if grund else ""))
        return json.loads(roh) if roh else None

    def abgleich(self, adresse: str) -> int:
        """Mit einem Peer: Stände tauschen, Fehlendes holen. Neue Einladungen können weitere Herausgeber freischalten, darum mehrere Durchgänge."""
        neu = 0
        try:
            for _ in range(4):
                fremd = self._anfrage(adresse, "POST", "/netz/koepfe", {"koepfe": self.log.koepfe()})["koepfe"]
                eigen = self.log.koepfe()
                offen = [(p, s) for p, s in fremd.items() if isinstance(s, int) and s > eigen.get(p, 0) and self.log.ist_mitglied(p)]
                if not offen:
                    break
                vorher = neu
                for pub, ziel in sorted(offen, key=lambda x: x[0] not in self.k.gruender):
                    neu += self._torrent_abgleich(adresse, pub, eigen.get(pub, 0), ziel)
                    neu += self._hole(adresse, pub, ziel)
                if neu == vorher:
                    break
            # Schieben, nicht nur holen: Ein Peer hinter einer Firewall wäre sonst nie zu lesen
            fremd = self._anfrage(adresse, "POST", "/netz/koepfe", {"koepfe": self.log.koepfe()})["koepfe"]
            for pub, s in self.log.koepfe().items():
                if s > int(fremd.get(pub, 0)) and self.log.ist_mitglied(pub):
                    self._schiebe(adresse, pub, int(fremd.get(pub, 0)))
            self.log.peer_ergebnis(adresse, True)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log(f"Netz: Abgleich mit {adresse}: {type(e).__name__}: {str(e)[:120]}")
            self.log.peer_ergebnis(adresse, False)
        return neu

    def _hole(self, adresse: str, pub: str, ziel: int) -> int:
        neu = 0
        while True:
            ab = self.log.koepfe().get(pub, 0)
            if ab >= ziel:
                return neu
            r = self.log.aufnehmen(self._anfrage(adresse, "GET", f"/netz/log/{pub}?ab={ab}&max={JE_ABRUF}")["eintraege"])
            neu += r["neu"]
            self.statistik["per_https"] += r["neu"]
            if r["neu"] == 0:
                if r["gruende"]:
                    log(f"Netz: von {adresse}: {'; '.join(r['gruende'])[:200]}")
                return neu

    def _schiebe(self, adresse: str, pub: str, ab: int) -> None:
        while True:
            reihe = self.log.lies(pub, ab, JE_ABRUF)
            if not reihe:
                return
            paket, groesse = [], 0
            for e in reihe:
                n = len(json.dumps(e))
                if paket and groesse + n > MAX_KOERPER * 3 // 4:
                    break
                paket.append(e)
                groesse += n
            r = self._anfrage(adresse, "POST", "/netz/eintraege", {"eintraege": paket})
            if not r.get("neu") and not r.get("bekannt"):
                return
            ab = paket[-1]["kopf"]["seq"]

    def _torrent_abgleich(self, adresse: str, pub: str, stand: int, ziel: int) -> int:
        if not self.schwarm or ziel - stand < int(self.k.torrent.get("ab", 1000)):
            return 0
        neu = 0
        try:
            segmente = self._anfrage(adresse, "GET", f"/netz/segmente/{pub}")["segmente"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return 0
        for s in segmente:
            if s["von"] != self.log.koepfe().get(pub, 0) + 1:
                continue
            eintraege = self.schwarm.hole(s, urllib.parse.urlsplit(adresse).hostname, float(self.k.torrent.get("warte_s", 60)), self.log, pub)
            if eintraege is None:
                break
            r = self.log.aufnehmen(eintraege)
            neu += r["neu"]
            self.statistik["per_torrent"] += r["neu"]
        return neu

    def segment_bauen(self) -> None:
        if not self.schwarm or self.k.modus != "peerhost":
            return
        groesse, von = int(self.k.torrent.get("segment", 2000)), self.log.letztes_segment_bis(self.log.pub) + 1
        if self.log.koepfe().get(self.log.pub, 0) - von + 1 < groesse:
            return
        self.schwarm.baue(self.log, self.log.pub, von, von + groesse - 1)

    # ---- Runde ----

    def ausgang(self) -> int:
        if not self.mcp:
            return 0
        try:
            a = self.mcp.ausgang()
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
            log(f"Netz: Gedächtnis nicht erreichbar: {type(e).__name__}: {str(e)[:120]}")
            return 0
        bekannt, widerrufen, neu = self.log.eigene_objekte(), self.log.eigene_widerrufe(), 0
        for o in a.get("objekte", []):
            if (o["netz_id"], lb.sha256(o)) not in bekannt and o["netz_id"] not in widerrufen:
                self.log.anhaengen("objekt", o, o["netz_id"], o["loesch_hash"])
                neu += 1
        for w in a.get("widerrufe", []):
            if w["netz_id"] not in widerrufen:
                self.log.anhaengen("widerruf", {"ziel": w["netz_id"], "token": w["token"]}, w["netz_id"])
                neu += 1
        return neu

    def eingang(self) -> None:
        if not self.mcp:
            return
        glaubt_alle = "*" in self.k.glauben
        for pub in self.log.koepfe():
            if pub == self.log.pub or not self.log.ist_mitglied(pub):
                continue
            while (reihe := self.log.neu_seit_stand(pub)):
                geglaubt = glaubt_alle or pub in self.k.glauben
                senden = [e for e in reihe if e["inhalt"] is not None and (e["kopf"]["typ"] == "widerruf" or (geglaubt and e["kopf"]["typ"] == "objekt"))]
                try:
                    if senden:
                        self.mcp.eingang(senden)
                except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
                    log(f"Netz: Eingang ins Gedächtnis gescheitert: {type(e).__name__}: {str(e)[:120]}")
                    return
                self.log.stand_setzen(pub, reihe[-1]["kopf"]["seq"])

    def eigener_pin(self) -> str | None:
        """Nur ein selbst betriebenes TLS hat einen Pin; hinter einem Reverse-Proxy prüft die CA."""
        if not self.k.tls_cert:
            return None
        return zertifikat_pin(Path(self.k.tls_cert))

    def _adresse_melden(self) -> int:
        if self.k.modus != "peerhost" or not self.k.adresse:
            return 0
        soll = {"adresse": self.k.adresse.rstrip("/"), **({"pin": p} if (p := self.eigener_pin()) else {})}
        if self.log.letzte_eigene_adresse() != soll:
            self.log.anhaengen("adresse", soll)
            return 1
        return 0

    def anstossen(self, peers: list[str]) -> None:
        for a in peers:
            try:
                self._anfrage(a, "POST", "/netz/anstoss", {})
            except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
                pass

    def runde(self) -> int:
        if not self._runde.acquire(blocking=False):
            return 0
        try:
            neu = self.ausgang() + self._adresse_melden()
            self.segment_bauen()
            ausser = self.k.adresse.rstrip("/") if self.k.adresse else None
            peers = self.log.peers_waehlen(self.k.nachbarn, ausser)
            for a in peers:
                neu += self.abgleich(a)
            self.eingang()
            self.statistik["runden"] += 1
            if neu and time.time() - self._zuletzt_angestossen >= self.k.min_runde_s:
                self._zuletzt_angestossen = time.time()
                self.anstossen(peers)
            return neu
        finally:
            self._runde.release()

    def schleife(self) -> None:
        while not self.halt.is_set():
            try:
                self.runde()
            except Exception as e:  # eine fehlerhafte Runde darf den Dienst nicht beenden
                log(f"Netz: Runde gescheitert: {type(e).__name__}: {str(e)[:200]}")
            self.wach.wait(self.k.takt_s)
            self.wach.clear()
            self.halt.wait(self.k.min_runde_s)

    # ---- Server ----

    def _begrenzt(self, pub: str, grenze: int = ANFRAGEN_JE_MIN) -> bool:
        jetzt = time.time()
        z = [t for t in self._zaehler.get(pub, []) if jetzt - t < 60]
        z.append(jetzt)
        self._zaehler[pub] = z
        return len(z) > grenze

    def _handler(self):
        dienst = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def _sende(self, code: int, wert=None):
                roh = json.dumps(wert).encode() if wert is not None else b""
                self.send_response(code)
                self.send_header("Content-Length", str(len(roh)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(roh)

            def _beitritt(self, koerper: bytes):
                """Ohne Mitgliedschaft, aber mit Beweis des Schlüssels und einem einmaligen Code."""
                pub = pruefe_kopf(self.headers.get("Authorization"), self.command, self.path, koerper)
                if not pub:
                    return self._sende(401, {"fehler": "Anfrage nicht signiert oder veraltet"})
                if dienst._begrenzt("beitritt", BEITRITTE_JE_MIN):
                    return self._sende(429, {"fehler": "zu viele Beitrittsversuche"})
                try:
                    nonce = json.loads(koerper).get("code")
                except (ValueError, AttributeError):
                    nonce = None
                if grund := dienst.log.beitritt_einloesen(nonce, pub):
                    return self._sende(403, {"fehler": grund})
                log(f"Netz: {lb.pseudonym(pub)} mit Beitrittscode eingeladen")
                dienst.wach.set()
                return self._sende(200, {"eingeladen": lb.pseudonym(pub)})

            def _anmelden(self, koerper: bytes) -> str | None:
                pub = pruefe_kopf(self.headers.get("Authorization"), self.command, self.path, koerper)
                if not pub:
                    self._sende(401, {"fehler": "Anfrage nicht signiert oder veraltet"})
                    return None
                if not dienst.log.ist_mitglied(pub):
                    self._sende(403, {"fehler": "kein Mitglied dieses Netzes"})
                    return None
                if dienst._begrenzt(pub):
                    self._sende(429, {"fehler": "zu viele Anfragen"})
                    return None
                return pub

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path == "/netz/gesund":
                    return self._sende(200, {"zustand": "ok"})
                if not self._anmelden(b""):
                    return None
                teile = u.path.strip("/").split("/")
                if len(teile) == 3 and teile[:2] == ["netz", "log"]:
                    q = urllib.parse.parse_qs(u.query)
                    try:
                        ab, n = int(q.get("ab", ["0"])[0]), int(q.get("max", [str(JE_ABRUF)])[0])
                    except ValueError:
                        return self._sende(400, {"fehler": "ab und max müssen Zahlen sein"})
                    return self._sende(200, {"eintraege": dienst.log.lies(teile[2], ab, min(n, JE_ABRUF))})
                if len(teile) == 3 and teile[:2] == ["netz", "segmente"]:
                    return self._sende(200, {"segmente": dienst.log.segmente(teile[2])})
                return self._sende(404, {"fehler": "unbekannt"})

            def do_POST(self):
                laenge = int(self.headers.get("Content-Length") or 0)
                if laenge > MAX_KOERPER:
                    return self._sende(413, {"fehler": "zu groß"})
                koerper = self.rfile.read(laenge)
                if self.path == "/netz/beitritt":
                    return self._beitritt(koerper)
                if not self._anmelden(koerper):
                    return None
                if self.path == "/netz/koepfe":
                    return self._sende(200, {"koepfe": dienst.log.koepfe()})
                if self.path == "/netz/eintraege":
                    r = dienst.log.aufnehmen(json.loads(koerper).get("eintraege"))
                    if r["neu"]:
                        dienst.wach.set()
                    return self._sende(200, r)
                if self.path == "/netz/anstoss":
                    dienst.wach.set()
                    return self._sende(204)
                return self._sende(404, {"fehler": "unbekannt"})
        return H

    def starte_server(self) -> None:
        self.server = ThreadingHTTPServer((self.k.bind, self.k.port), self._handler())
        self.server.daemon_threads = True
        if self.k.tls_cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.k.tls_cert, self.k.tls_key)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, name="vi-p2p-http", daemon=True).start()

    def port(self) -> int:
        return self.server.server_address[1]

    def stoppe(self) -> None:
        self.halt.set()
        self.wach.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.schwarm:
            self.schwarm.stoppe()
        self.log.schliessen()


def zertifikat_pin(pfad_: Path) -> str:
    """SHA-256 des Zertifikats in DER-Form, wie es der Peer beim Verbindungsaufbau sieht."""
    pem = pfad_.read_text()
    teil = pem[pem.index("-----BEGIN CERTIFICATE-----"):pem.index("-----END CERTIFICATE-----")]
    return hashlib.sha256(base64.b64decode("".join(teil.splitlines()[1:]))).hexdigest()


def code_bauen(gruender: list[str], start: str, pin: str | None, nonce: str, ablauf: float) -> str:
    roh = json.dumps({"g": gruender, "s": start, "p": pin, "n": nonce, "a": int(ablauf)}, separators=(",", ":")).encode()
    return CODE_PRAEFIX + base64.urlsafe_b64encode(roh).decode().rstrip("=")


def code_lesen(code: str) -> dict:
    """Rein. ValueError mit Grund, wenn der Code nicht passt."""
    code = (code or "").strip()
    if not code.startswith(CODE_PRAEFIX):
        raise ValueError("kein Beitrittscode (beginnt nicht mit vinetz1.)")
    try:
        d = json.loads(base64.urlsafe_b64decode(code[len(CODE_PRAEFIX):] + "=" * (-len(code) % 4)))
    except (ValueError, TypeError) as e:
        raise ValueError("Beitrittscode ist beschädigt") from e
    if not isinstance(d, dict) or not isinstance(d.get("g"), list) or not all(isinstance(x, str) and lb._HEX64.match(x) for x in d["g"]) or not d["g"]:
        raise ValueError("Beitrittscode nennt keine gültigen Gründer")
    if not isinstance(d.get("s"), str) or not lb._ADRESSE.match(d["s"]) or not isinstance(d.get("n"), str):
        raise ValueError("Beitrittscode nennt keine gültige Adresse")
    if d.get("p") is not None and not (isinstance(d["p"], str) and lb._HEX64.match(d["p"])):
        raise ValueError("Beitrittscode hat einen unbrauchbaren Pin")
    if not isinstance(d.get("a"), int) or d["a"] < time.time():
        raise ValueError("Beitrittscode ist abgelaufen")
    return d


def main() -> int:
    k = lade()
    if k.modus == "standalone":
        log("Netz: Modus standalone, nichts zu tun")
        return 0
    if not k.gruender:
        log("Netz: keine Gründer konfiguriert (vi-mcp netz einrichten)")
        return 2
    d = Netzdienst(k, McpKlient(k.mcp_url, k.mcp_token_datei))
    if k.modus == "peerhost":
        d.starte_server()
    import signal
    signal.signal(signal.SIGUSR1, lambda *_: d.wach.set())  # systemctl kill -s USR1 vi-p2p: Runde sofort
    log(f"Netz: Modus {k.modus}, Pseudonym {lb.pseudonym(d.log.pub)}, {len(d.log.mitglieder())} Mitglieder bekannt")
    try:
        d.schleife()
    except KeyboardInterrupt:
        pass
    return 0
