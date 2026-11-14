"""vi-p2p — the network service. Own process, own database, no access to the memory except via the MCP tool pair for outbox and inbox.

Modes: standalone (nothing runs), peer (outgoing only), peerhost (also accepts connections).
Round: own knowledge into the logbook → reconcile states with up to `nachbarn` peers and fetch what is missing → new entries to the memory → nudge neighbours.
Peers are found via the start list and via `adresse` entries in the logbooks. Every request is signed with the key; only members get an answer.
Entries verify themselves; HTTPS and torrent are interchangeable ways to get them. Unencrypted HTTP only on the own machine or with `http_erlaubt`.
0.39.0: one service per network (systemd vi-p2p@<netz>, config /etc/vi-p2p/<netz>.json); `vi-p2p` without a name is the network `standard`.
`art` firma relays internal names (the memory decides authoritatively, see p2p.networks). Every outbox call carries a snapshot of
peers, versions and backlog for vi_net_status and vi_stats.
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
from datetime import datetime, timezone
from hashlib import sha256 as _sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import logbook as lb
from .log_output import log

#: 0.54.0: the network services also run on Windows (scheduled tasks, %ProgramData%); a flag so tests can switch it
WINDOWS = os.name == "nt"


def etc_dir() -> Path:
    """Directory of the network services' config files: /etc/vi-p2p, on Windows %ProgramData%\\vi-mcp\\p2p (0.54.0); VI_P2P_DIR overrides."""
    if os.environ.get("VI_P2P_DIR"):
        return Path(os.environ["VI_P2P_DIR"])
    if WINDOWS:
        return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "vi-mcp" / "p2p"
    return Path("/etc/vi-p2p")


def var_dir() -> Path:
    """Directory of the logbooks and keys: /var/lib/vi-p2p, on Windows the same folder as the config files (0.54.0) — %ProgramData%\\vi-mcp
    is readable by SYSTEM and administrators only (install.ps1)."""
    if WINDOWS or os.environ.get("VI_P2P_DIR"):
        return etc_dir()
    return Path("/var/lib/vi-p2p")


DEFAULT_PATH = str(etc_dir() / "config.json")
MODES = ("standalone", "peer", "peerhost")
TIME_WINDOW = 300
MAX_BODY = 1024 * 1024
REQUESTS_PER_MIN = 240
REQUESTS_PER_MIN_IP = 600  # 0.45.0: in a free network keys cost little to make — the address is limited as well
PEERS_MAX = 500
JOINS_PER_MIN = 10
CODE_PREFIX = "vinetz1."
PER_FETCH = 500
RATINGS_PER_DAY = 1000
POSTS_PER_DAY = 200
#: 0.42.0: live search — answers per minute and key, members asked at most, seconds per member, hits per member
SEARCHES_PER_MIN = 30
SEARCH_FANOUT = 20
SEARCH_TIMEOUT_S = 5
#: 0.52.0 — news without waiting for the round, like BitTorrent's open connections and "have" messages (BEP 3): a peer behind a firewall
#: keeps one outgoing request open at a peerhost (long poll); the peerhost answers it as soon as it holds entries the peer lacks or a live
#: search waits for the peer. tick_s stays as the fallback. WAIT_MAX_S stays below the 60 s that proxies often allow.
WAIT_MAX_S = 50
MAX_WAITERS = 500
#: a live search at a peerhost is relayed to the peers waiting there (one hop, never further); how long it waits for their answers
RELAY_WAIT_S = 3
RECONNECT_S = 5  # a peer whose wait ended this recently still counts as connected
SEARCH_MAX = 10
LOCAL = ("127.0.0.1", "localhost", "::1")


@dataclass
class NetConfig:
    mode: str = "standalone"
    #: 0.39.0: name of the network (shown in reports) and its kind: offen (anonymised) or firma (internal names allowed in relayed objects)
    net: str = "standard"
    kind: str = "open"  # free, open or company (0.51.0; frei, offen, firma in older files)
    db: str = field(default_factory=lambda: str(var_dir() / "netz.db"))
    seed: str = field(default_factory=lambda: str(var_dir() / "schluessel"))
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
    mcp_token_file: str = field(default_factory=lambda: str(etc_dir() / "mcp-token"))
    torrent: dict = field(default_factory=dict)
    proxy: str | None = None
    no_proxy: list = field(default_factory=list)
    #: 0.42.0: local listener for the memory's live searches (127.0.0.1 only); the memory holds the token, this file only its SHA-256
    local_port: int = 0
    local_token_sha256: str | None = None
    #: 0.63.0: where the local listener binds — 127.0.0.1 on one host; in a container setup the address the memory container reaches
    #: (the listener checks the token in every request either way)
    local_bind: str = "127.0.0.1"
    #: 0.45.0 free network (art frei): no invitation — identity proof of pow_bits, quota for unknown publishers per day, local blocks
    #: (public keys or addresses), and no connections to private addresses learned from others unless private_ok (a lab network)
    pow_bits: int = 26
    new_quota: int = 100
    blocked: list = field(default_factory=list)
    private_ok: bool = False

    def __post_init__(self):
        from . import config as cfg
        self.kind = cfg.net_kind(self.kind)  # 0.51.0: frei/offen/firma (older files, callers) → free/open/company
        if isinstance(self.torrent, dict):
            self.torrent = english_file({"torrent": self.torrent})["torrent"]

def fpath() -> Path:
    return Path(os.environ.get("VI_P2P_CONFIG") or etc_dir() / "config.json")


#: German keys of config files written before 0.51.0 → NetConfig field. Since 0.51.0 the file uses the field names (English); the German
#: keys are still read (english_file). Keys not listed here have the same name in file and dataclass.
FILE_KEYS = {"modus": "mode", "adresse": "address", "ca_datei": "ca_file", "gruender": "founders", "takt_s": "tick_s",
             "min_runde_s": "min_round_s", "nachbarn": "neighbors", "http_erlaubt": "http_allowed", "glauben": "believe",
             "mcp_token_datei": "mcp_token_file", "kein_proxy": "no_proxy", "netz": "net", "art": "kind", "lokal_port": "local_port", "lokal_token_sha256": "local_token_sha256",
             "arbeit_bits": "pow_bits", "quote_neu": "new_quota", "sperren": "blocked", "privat_erlaubt": "private_ok"}


TORRENT_KEYS = {"aktiv": "active", "verzeichnis": "directory"}


def english_file(d: dict) -> dict:
    """A config file's dict with English keys and network kind (0.51.0). If a file has both spellings, the English one wins. Pure."""
    from . import config as cfg
    out: dict = {}
    for key, value in (d or {}).items():
        new = FILE_KEYS.get(key, key)
        if new != key and new in d:
            continue
        out[new] = value
    if "kind" in out:
        out["kind"] = cfg.net_kind(out["kind"])
    if isinstance(out.get("torrent"), dict):
        t = out["torrent"]
        out["torrent"] = {TORRENT_KEYS.get(k, k): v for k, v in t.items() if not (TORRENT_KEYS.get(k, k) != k and TORRENT_KEYS[k] in t)}
    return out


def from_file(d: dict) -> NetConfig:
    """NetConfig from the config file's dict. Accepts the English field names and the German keys of older files;
    unknown keys are reported, not dropped silently."""
    fields = NetConfig.__dataclass_fields__
    kw, unknown = {}, []
    for key, value in english_file(d).items():
        if key in fields:
            kw[key] = value
        else:
            unknown.append(key)
    if unknown:
        log(f"config: unknown keys ignored: {', '.join(sorted(unknown))}")
    return NetConfig(**kw)


def load(p: Path | None = None) -> NetConfig:
    p = p or fpath()
    d = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    k = from_file(d)
    if k.mode not in MODES:
        raise ValueError(f"mode must be {', '.join(MODES)}")
    if k.kind not in ("open", "company", "free"):
        raise ValueError("kind must be open, company or free")
    if k.kind == "free" and not lb.MIN_POW_BITS <= int(k.pow_bits) <= 40:
        raise ValueError(f"pow_bits must be {lb.MIN_POW_BITS}–40")
    return k


def _sign(k, method: str, req_path: str, req_body: bytes) -> str:
    ts = str(int(time.time()))
    sig = k.sign("\n".join((method, req_path, ts, _sha256(req_body).hexdigest())).encode()).hex()
    return f"VI-Netz {lb.public_hex(k)} {ts} {sig}"


def check_header(value: str | None, method: str, req_path: str, req_body: bytes) -> str | None:
    """Public key of the sender if the request is genuine and fresh, otherwise None."""
    parts = (value or "").split()
    if len(parts) != 4 or parts[0] != "VI-Netz" or not parts[2].isdigit() or abs(time.time() - int(parts[2])) > TIME_WINDOW:
        return None
    if not lb._HEX64.match(parts[1]):
        return None
    return parts[1] if lb.valid(parts[1], parts[3], "\n".join((method, req_path, parts[2], _sha256(req_body).hexdigest())).encode()) else None


class McpClient:
    """The memory as the network service sees it: exactly two tools."""

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

    def outbox(self, state: dict | None = None) -> dict:
        return self._call_tool("vi_net_outbox", {"state": state} if state else {})

    def inbox(self, entries: list[dict]) -> dict:
        return self._call_tool("vi_net_inbox", {"entries": entries})

    def answer_search(self, query: str, n: int) -> list:
        return self._call_tool("vi_net_answer_search", {"query": query, "max": n})


def data_dir(k: "NetConfig") -> Path:
    """Directory for files next to the logbook (torrent segments, TLS): beside the SQLite file, or beside the key with PostgreSQL."""
    from . import db as dbmod
    return Path(k.seed).parent if dbmod.is_url(k.db) else Path(k.db).parent


class NetService:
    def __init__(self, k: NetConfig, mcp=None):
        self.k = k
        self.free = k.kind == "free"
        self.trusted: set[str] = set()  # 0.45.0: publishers the memory measured as useful — full quota in a free network
        self.blocked_addresses = {b.rstrip("/") for b in k.blocked if "://" in str(b)}
        self.log = lb.Logbook(k.db, Path(k.seed), k.founders, internal_ok=k.kind == "company", free_bits=int(k.pow_bits) if self.free else None,
                              blocked={b for b in k.blocked if lb._HEX64.match(str(b))}, quota_of=self._quota if self.free else None,
                              schema=lb.schema_for(k.net))
        self.config_blocked = set(self.log.blocked)
        if self.free:
            took = self.log.ensure_identity(int(k.pow_bits))
            if took is not None:
                log(f"network {k.net}: identity proof of {k.pow_bits} bits made in {took} s")
        self.mcp = mcp
        for a in k.startpeers:
            self.log.peer_remember(a, "start")
        self.halt = threading.Event()
        self.awake = threading.Event()
        self.server: ThreadingHTTPServer | None = None
        self.local_server: ThreadingHTTPServer | None = None
        self._round = threading.Lock()
        self._counter: dict[str, list[float]] = {}
        self._last_nudged = 0.0
        self.swarm = None
        self.paused = False  # 0.47.0: the memory switched this network off: no reconciliation, no inbox
        self.usage_stats = {"runden": 0, "per_https": 0, "per_torrent": 0}
        # 0.52.0 long poll and search relay
        self._changed = threading.Condition()
        self._waiters: dict[str, int] = {}  # pub → open waits at this peerhost
        self._waited: dict[str, float] = {}  # pub → when its last wait ended (it reconnects within a second)
        self._searches: dict[str, dict] = {}  # relayed live searches waiting for answers
        self._wait_target: str | None = None  # the peerhost this peer keeps a long poll open at
        self._no_wait: dict[str, float] = {}  # peerhost → until when it is not asked (older version without /netz/warten)
        if k.torrent.get("active"):
            from . import net_torrent
            if net_torrent.available():
                self.swarm = net_torrent.Swarm(Path(k.torrent.get("directory") or data_dir(k) / "segmente"), int(k.torrent.get("port", 6881)), k.bind if k.mode == "peerhost" else "127.0.0.1")
                for sha, ti, file in self.log.segments_local():
                    self.swarm.parts(ti, Path(file))
            else:
                log("network: torrent configured, but python3-libtorrent is missing; staying with HTTPS")

    def _quota(self, pub: str) -> int:
        """Free network: unknown publishers get new_quota entries a day, those the memory measured as useful the full quota."""
        return lb.MAX_PER_DAY if pub in self.trusted or pub == self.log.pub else int(self.k.new_quota)

    def _trust(self, v) -> None:
        """From the memory (outbox): {"bewaehrt": [pub], "gesperrt": [pub]} — measured benefit decides, never a founder."""
        if not isinstance(v, dict):
            return
        self.trusted = {p for p in v.get("bewaehrt") or [] if isinstance(p, str) and lb._HEX64.match(p)}
        blocked = self.config_blocked | {p for p in v.get("gesperrt") or [] if isinstance(p, str) and lb._HEX64.match(p)}
        if blocked != self.log.blocked:
            self.log.blocked = blocked
            self.log._members = None

    def _public_target(self, host: str) -> None:
        """Free network: never connect to a private, loopback or link-local address learned from others (no reaching into the own LAN)."""
        if not self.free or self.k.private_ok:
            return
        import ipaddress
        import socket as _socket
        try:
            infos = _socket.getaddrinfo(host, None)
        except OSError as e:
            raise ValueError(f"cannot resolve {host}: {e}") from e
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise ValueError(f"{host} is not a public address — refused in a free network (privat_erlaubt for a lab)")

    def exchange_peers(self, address: str) -> int:
        """0.45.0: ask a peer for the addresses it reached recently; remember the new ones. Seeds are only the first contact."""
        try:
            got = self._request(address, "GET", "/netz/peers").get("peers") or []
        except (urllib.error.URLError, OSError, ValueError, AttributeError, TypeError, http.client.HTTPException):
            return 0
        own = self.k.address.rstrip("/") if self.k.address else None
        new = 0
        for a in got[:100]:
            if not isinstance(a, str) or not lb._ADDRESS.match(a.rstrip("/")) or a.rstrip("/") in (own, address) or a.rstrip("/") in self.blocked_addresses:
                continue
            if self.log.peer_count() >= PEERS_MAX:
                break
            if not self.log.pin(a) and a.rstrip("/") not in {p["adresse"] for p in self.log.peers()}:
                self.log.peer_remember(a, "austausch")
                new += 1
        return new

    # ---- Client ----

    def _allowed(self, address: str) -> bool:
        u = urllib.parse.urlsplit(address)
        return u.scheme == "https" or self.k.http_allowed or (u.hostname or "") in LOCAL

    def _proxy_for(self, host: str) -> tuple[str, int] | None:
        if not self.k.proxy or host in LOCAL or any(host == n.lstrip(".") or host.endswith("." + n.lstrip(".")) for n in self.k.no_proxy):
            return None
        u = urllib.parse.urlsplit(self.k.proxy)
        return u.hostname, u.port or 80

    def _request(self, address: str, method: str, req_path: str, data=None, timeout: float = 30):
        """Signed request. HTTPS verifies the certificate via the CA or, if a pin is known, via its SHA-256. HTTPS proxy via CONNECT."""
        if not self._allowed(address):
            raise ValueError("unencrypted HTTP to another machine is not allowed")
        req_body = json.dumps(data).encode() if data is not None else b""
        h = {"Authorization": _sign(self.log.k, method, req_path, req_body), "Content-Type": "application/json"}
        u = urllib.parse.urlsplit(address)
        host, https = u.hostname or "", u.scheme == "https"
        self._public_target(host)
        port = u.port or (443 if https else 80)
        proxy = self._proxy_for(host)
        pin = self.log.pin(address)
        try:
            if https:
                if pin:  # self-signed: not the CA but exactly this certificate counts
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                else:
                    ctx = ssl.create_default_context(cafile=self.k.ca_file)
                c = http.client.HTTPSConnection(*(proxy or (host, port)), context=ctx, timeout=timeout)
                if proxy:
                    c.set_tunnel(host, port)
                c.connect()
                if pin and hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() != pin:
                    c.close()
                    raise ValueError("certificate does not match the known pin")
            else:
                c = http.client.HTTPConnection(host, port, timeout=timeout)
            try:
                c.request(method, u.path.rstrip("/") + req_path, body=req_body if method == "POST" else None, headers=h)
                r = c.getresponse()
                raw = r.read()
            finally:
                c.close()
        except http.client.HTTPException as e:
            raise ValueError(f"HTTP error: {type(e).__name__}") from e
        if r.status >= 400:
            try:
                reason = json.loads(raw).get("fehler", "")
            except (ValueError, AttributeError):
                reason = ""
            raise ValueError(f"HTTP {r.status}" + (f": {reason}" if reason else ""))
        return json.loads(raw) if raw else None

    def reconcile(self, address: str) -> int:
        """With one peer: exchange states, fetch what is missing. New invitations can unlock further publishers, hence several passes."""
        new = 0
        try:
            try:  # 0.39.0: the peer's version — a new entry type is only written once every peer understands it
                try:  # 0.59.1: /netz/health; a peer before 0.59.1 knows only /netz/gesund
                    h = self._request(address, "GET", "/netz/health")
                except ValueError as ex:
                    if "404" not in str(ex):
                        raise
                    h = self._request(address, "GET", "/netz/gesund")
                self.log.peer_state(address, version=str((h or {}).get("version") or "?"))
            except (ValueError, OSError, TypeError, AttributeError):
                pass
            for _ in range(4):
                foreign = self._request(address, "POST", "/netz/koepfe", {"koepfe": self.log.headers()})["koepfe"]
                own = self.log.headers()
                # free network: any key not blocked here — its entry 1 (the identity) is checked on arrival
                open_ = [(p, s) for p, s in foreign.items() if isinstance(s, int) and s > own.get(p, 0)
                         and (self.log.is_member(p) or (self.free and isinstance(p, str) and lb._HEX64.match(p) and p not in self.log.blocked))]
                if not open_:
                    break
                before = new
                for pub, target in sorted(open_, key=lambda x: x[0] not in self.k.founders):
                    new += self._torrent_reconcile(address, pub, own.get(pub, 0), target)
                    new += self._fetch(address, pub, target)
                if new == before:
                    break
            # push, not only fetch: a peer behind a firewall could otherwise never be read
            foreign = self._request(address, "POST", "/netz/koepfe", {"koepfe": self.log.headers()})["koepfe"]
            for pub, s in self.log.headers().items():
                if s > int(foreign.get(pub, 0)) and self.log.is_member(pub):
                    self._push(address, pub, int(foreign.get(pub, 0)))
            self._record_backlog(address)
            self.log.peer_result(address, True)
            if self.free:
                self.exchange_peers(address)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            log(f"network: reconcile with {address}: {type(e).__name__}: {str(e)[:120]}")
            self.log.peer_result(address, False)
        return new

    def _record_backlog(self, address: str) -> None:
        """Entries of members the peer has and we lack, and the other way round — after the exchange, so ideally both 0."""
        try:
            foreign = self._request(address, "POST", "/netz/koepfe", {"koepfe": self.log.headers()})["koepfe"]
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
            return
        own = self.log.headers()
        members = self.log.members()
        here = sum(max(0, int(s) - own.get(p, 0)) for p, s in foreign.items() if p in members and isinstance(s, int))
        there = sum(max(0, s - int(foreign.get(p, 0) or 0)) for p, s in own.items() if p in members)
        self.log.peer_state(address, missing_here=here, missing_there=there)

    def snapshot(self) -> dict:
        """0.39.0: what the memory shows in vi_net_status and vi_stats. Addresses stay on this machine (the memory is local)."""
        st = self.log.status()
        now = time.time()
        peers = [{"adresse": p["adresse"], "version": p["version"], "zuletzt_s": round(now - p["zuletzt"]) if p["zuletzt"] else None, "fehler": p["fehler"],
                  "erreichbar": bool(p["zuletzt"]) and p["fehler"] == 0, "fehlt_hier": p["fehlt_hier"], "fehlt_dort": p["fehlt_dort"]} for p in self.log.peers()]
        return {"netz": self.k.net, "art": self.k.kind, "modus": self.k.mode, "pausiert": self.paused, "identitaeten": st.get("identitaeten"), "gesperrt": st.get("gesperrt"),
                "bewaehrt": len(self.trusted), "pseudonym": lb.pseudonym(self.log.pub), "version": __version__,
                "mitglieder": st["mitglieder"], "eintraege": st["eintraege"], "unbekannte_typen": st["unbekannte_typen"], "gabelungen": st["gabelungen"],
                "verstoesse": st["verstoesse"], "peers": peers, "transport": dict(self.usage_stats),
                "eigene": {t: self.log.count_own(t) for t in ("objekt", "widerruf", "bewertung", "seite", "beitrag")}}

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
                    log(f"network: from {address}: {'; '.join(r['gruende'])[:200]}")
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

    # ---- News without waiting for the round (0.52.0) ----

    def _signal(self) -> None:
        """Something changed here (new entries, a relayed search): wake every waiting long poll."""
        with self._changed:
            self._changed.notify_all()

    def _news_for(self, theirs: dict) -> bool:
        return any(s > int((theirs or {}).get(p, 0) or 0) for p, s in self.log.headers().items())

    def _searches_for(self, pub: str) -> list[dict]:
        out, now = [], time.monotonic()
        for sid, x in self._searches.items():
            if x["von"] != pub and pub not in x["an"] and x["ende"] > now:
                x["an"].add(pub)
                out.append({"id": sid, "q": x["q"], "max": x["max"]})
        return out

    def wait_for(self, pub: str, theirs: dict, max_s: float) -> dict:
        """Peerhost side of the long poll: answer at once if there is news for the caller, else wait for news up to max_s."""
        deadline = time.monotonic() + max(0.0, min(float(max_s), WAIT_MAX_S))
        with self._changed:
            if sum(self._waiters.values()) >= MAX_WAITERS:
                return {"neu": False, "suchen": [], "voll": True}
            self._waiters[pub] = self._waiters.get(pub, 0) + 1
            try:
                while True:
                    news, searches = self._news_for(theirs), self._searches_for(pub)
                    if news or searches or self.halt.is_set():
                        return {"neu": news, "suchen": searches}
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return {"neu": False, "suchen": []}
                    self._changed.wait(left)
            finally:
                self._waiters[pub] -= 1
                if not self._waiters[pub]:
                    del self._waiters[pub]
                self._waited[pub] = time.monotonic()

    def wait_once(self, address: str) -> dict:
        """Peer side: one long poll at the peerhost. News → reconcile with it at once; relayed searches → answer them from here."""
        r = self._request(address, "POST", "/netz/warten", {"koepfe": self.log.headers(), "max_s": WAIT_MAX_S}, timeout=WAIT_MAX_S + 20)
        for x in (r or {}).get("suchen") or []:
            try:
                a = self.answer(str(x.get("q") or "")[:300], int(x.get("max") or SEARCH_MAX))
            except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
                log(f"network: relayed search not answered: {type(e).__name__}: {str(e)[:120]}")
                a = {"pub": self.log.pub, "treffer": []}
            try:
                self._request(address, "POST", "/netz/suche/antwort", {"id": str(x.get("id")), **a}, timeout=SEARCH_TIMEOUT_S)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError, http.client.HTTPException) as e:
                log(f"network: relayed search answer not delivered: {type(e).__name__}: {str(e)[:120]}")
        if (r or {}).get("neu") and not self.paused and self._round.acquire(timeout=30):
            try:
                if self.reconcile(address):
                    self.inbox()
            finally:
                self._round.release()
        return r or {}

    def wait_targets(self) -> list[str]:
        """Peerhosts this peer can keep a long poll open at: known addresses, reachable at the last attempt, not marked as too old."""
        own = self.k.address.rstrip("/") if self.k.address else None
        now = time.time()
        return [p["adresse"] for p in self.log.peers() if p["adresse"] != own and p["fehler"] == 0 and self._no_wait.get(p["adresse"], 0) < now]

    def wait_loop(self) -> None:
        """Peer mode: keep one long poll open, at the first reachable peerhost; never a tight loop."""
        pause = 1.0
        while not self.halt.is_set():
            targets = self.wait_targets()
            if self.paused or not targets:
                self.halt.wait(10)
                continue
            address = self._wait_target if self._wait_target in targets else targets[0]
            self._wait_target = address
            try:
                if self.wait_once(address).get("voll"):
                    self.halt.wait(10)
                pause = 1.0
            except (urllib.error.URLError, OSError, ValueError, TimeoutError, http.client.HTTPException, KeyError, TypeError) as e:
                if "404" in str(e):  # a peerhost older than 0.52.0: rounds only, ask again in an hour
                    self._no_wait[address] = time.time() + 3600
                    self._wait_target = None
                else:
                    log(f"network: long poll at {address}: {type(e).__name__}: {str(e)[:120]}")
                    self.halt.wait(pause)
                    pause = min(pause * 2, 60.0)
            self.halt.wait(0.5)

    def relay_search(self, asker: str, query: str, n: int) -> dict:
        """Peerhost: hand a member's live search to the peers waiting here and collect their signed answers for RELAY_WAIT_S at most.
        One hop: a peer answers from its own memory and never relays further."""
        import uuid
        with self._changed:
            # waiting now, or between two waits (a peer reconnects within a second and then picks the search up at once)
            recent = {p for p, t in self._waited.items() if time.monotonic() - t < RECONNECT_S}
            targets = (set(self._waiters) | recent) - {asker}
            if not targets:
                return {"antworten": [], "gefragt": 0, "ohne_antwort": 0}
            sid = uuid.uuid4().hex
            self._searches[sid] = x = {"q": query, "max": n, "von": asker, "an": set(), "antworten": {}, "ende": time.monotonic() + RELAY_WAIT_S}
            self._changed.notify_all()
            try:
                while time.monotonic() < x["ende"] and not targets <= set(x["antworten"]):
                    self._changed.wait(max(0.05, x["ende"] - time.monotonic()))
            finally:
                del self._searches[sid]
        self.usage_stats["suchen_weitergeleitet"] = self.usage_stats.get("suchen_weitergeleitet", 0) + 1
        return {"antworten": list(x["antworten"].values()), "gefragt": len(targets), "ohne_antwort": len(targets - set(x["antworten"]))}

    def relay_answer(self, pub: str, body: dict) -> bool:
        with self._changed:
            x = self._searches.get(str(body.get("id") or ""))
            if not x or pub not in x["an"] or body.get("pub") != pub:
                return False
            x["antworten"][pub] = {"pub": pub, "treffer": [t for t in (body.get("treffer") or []) if isinstance(t, dict)][:SEARCH_MAX]}
            self._changed.notify_all()
            return True

    # ---- Live search (0.42.0) ----

    def answer(self, query: str, n: int) -> dict:
        """A member asks: hits from the memory in this network's export form, each signed with this server's key."""
        hits = self.mcp.answer_search(query, min(int(n or SEARCH_MAX), SEARCH_MAX)) if self.mcp else []
        self.usage_stats["suchen_beantwortet"] = self.usage_stats.get("suchen_beantwortet", 0) + 1
        return {"pub": self.log.pub, "treffer": [{"objekt": o, "sig": self.log.k.sign(lb.canonical(o)).hex()} for o in hits if isinstance(o, dict)][:SEARCH_MAX]}

    def search(self, query: str, n: int = SEARCH_MAX) -> dict:
        """Ask every reachable member with an address at once (no forwarding, so no amplification); verify every hit's signature."""
        from concurrent.futures import ThreadPoolExecutor
        t0 = time.monotonic()
        own = self.k.address.rstrip("/") if self.k.address else None
        targets = [p["adresse"] for p in self.log.peers() if p["adresse"] != own][:SEARCH_FANOUT]

        def ask(address):
            try:
                return address, self._request(address, "POST", "/netz/suche", {"q": query, "max": n}, timeout=SEARCH_TIMEOUT_S + RELAY_WAIT_S), None
            except (urllib.error.URLError, OSError, TimeoutError, ValueError, http.client.HTTPException) as e:
                return address, None, f"{type(e).__name__}: {str(e)[:80]}"
        answers, unreachable, dropped, relayed_to, relayed_silent = [], [], 0, 0, 0

        def verified(pub, hits):
            nonlocal dropped
            good = []
            for t in hits or []:
                if isinstance(t, dict) and isinstance(t.get("objekt"), dict) and isinstance(t.get("sig"), str) and lb.valid(pub, t["sig"], lb.canonical(t["objekt"])):
                    good.append(t)
                else:
                    dropped += 1
            return good
        with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
            for address, a, err in ex.map(ask, targets):
                if err or not isinstance(a, dict):
                    unreachable.append({"adresse": address, "grund": err or "no answer"})
                    continue
                pub = a.get("pub")
                if not isinstance(pub, str) or not lb._HEX64.match(pub) or not self.log.is_member(pub):
                    unreachable.append({"adresse": address, "grund": "answer not from a member"})
                    continue
                answers.append({"adresse": address, "pub": pub, "treffer": verified(pub, a.get("treffer"))})
                # 0.52.0: answers of the peers behind the peerhost — each signed by its own author, so the peerhost cannot forge them
                relayed_to += int(a.get("weitergeleitet_an") or 0)
                relayed_silent += int(a.get("ohne_antwort") or 0)
                for r in a.get("weitergeleitet") or []:
                    rp = r.get("pub") if isinstance(r, dict) else None
                    if not isinstance(rp, str) or not lb._HEX64.match(rp) or not self.log.is_member(rp) or rp == self.log.pub:
                        dropped += len((r or {}).get("treffer") or []) if isinstance(r, dict) else 1
                        continue
                    answers.append({"adresse": f"{address} → {lb.pseudonym(rp)}", "pub": rp, "treffer": verified(rp, r.get("treffer"))})
        if self.k.mode == "peerhost":  # 0.52.0: a peerhost asks the peers waiting at it too
            mine = self.relay_search(self.log.pub, query, n)
            relayed_to += mine["gefragt"]
            relayed_silent += mine["ohne_antwort"]
            for r in mine["antworten"]:
                if self.log.is_member(r["pub"]):
                    answers.append({"adresse": f"waiting here → {lb.pseudonym(r['pub'])}", "pub": r["pub"], "treffer": verified(r["pub"], r["treffer"])})
        self.usage_stats["suchen_gestellt"] = self.usage_stats.get("suchen_gestellt", 0) + 1
        return {"antworten": answers, "nicht_erreichbar": unreachable, "verworfen": dropped, "gefragt": len(targets), "weitergeleitet_an": relayed_to,
                "weitergeleitet_ohne_antwort": relayed_silent, "ms": int((time.monotonic() - t0) * 1000)}

    def _local_handler(self):
        service = self

        class L(BaseHTTPRequestHandler):
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

            def do_POST(self):
                import hmac as _hmac
                token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                if not service.k.local_token_sha256 or not _hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), service.k.local_token_sha256):
                    return self._send(401, {"fehler": "local token wrong"})
                length = int(self.headers.get("Content-Length") or 0)
                if length > 64 * 1024:
                    return self._send(413, {"fehler": "too large"})
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send(400, {"fehler": "not JSON"})
                if self.path == "/lokal/anstoss":  # 0.52.0: the memory has something new for the network (a question, an answer, a page)
                    service.awake.set()
                    return self._send(204)
                if self.path == "/lokal/suche" and isinstance(body.get("q"), str) and body["q"].strip():
                    return self._send(200, service.search(body["q"].strip()[:300], int(body.get("max") or SEARCH_MAX)))
                return self._send(404, {"fehler": "unknown"})
        return L

    def start_local_server(self) -> int:
        """Only on the own machine: the memory asks the network through this service (which holds the key)."""
        self.local_server = ThreadingHTTPServer((self.k.local_bind or "127.0.0.1", self.k.local_port), self._local_handler())
        self.local_server.daemon_threads = True
        threading.Thread(target=self.local_server.serve_forever, name="vi-p2p-local", daemon=True).start()
        return self.local_server.server_address[1]

    # ---- Round ----

    def outbox(self) -> int:
        if not self.mcp:
            return 0
        try:
            a = self.mcp.outbox(self.snapshot())
            self._trust(a.get("vertrauen"))
            self.paused = bool(a.get("aus"))  # 0.47.0: switched off in the memory
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
            log(f"network: memory not reachable: {type(e).__name__}: {str(e)[:120]}")
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
        return new + self._ratings(a.get("bewertungen") or []) + self._pages(a.get("seiten") or []) + self._posts(a.get("beitraege") or [])

    def _posts(self, posts: list) -> int:
        """0.43.0: own posts (questions and answers between AIs) — each once, at most POSTS_PER_DAY, only once no peer is older than 0.39.0."""
        if not posts:
            return 0
        if blocked := self.log.peers_below(lb.RELAY_MIN):
            self.usage_stats["beitraege_sperre"] = blocked[:10]
            return 0
        self.usage_stats.pop("beitraege_sperre", None)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        done, n, new = self.log.own_shas("beitrag"), self.log.count_own("beitrag", today), 0
        for c in reversed(posts):
            if n >= POSTS_PER_DAY:
                break
            if not isinstance(c, dict) or lb.sha256(c) in done or not isinstance(c.get("netz_id"), str) or not isinstance(c.get("loesch_hash"), str):
                continue
            self.log.attach("beitrag", c, c["netz_id"], c["loesch_hash"])
            n, new = n + 1, new + 1
        return new

    def _pages(self, pages: list) -> int:
        """0.41.0: own wiki revisions — each once (by checksum), only once no peer is older than 0.39.0."""
        if not pages:
            return 0
        if blocked := self.log.peers_below(lb.RELAY_MIN):
            self.usage_stats["seiten_wartend"] = len(pages)
            self.usage_stats["seiten_sperre"] = blocked[:10]
            return 0
        self.usage_stats.pop("seiten_sperre", None)
        done, new = self.log.own_shas("seite"), 0
        for c in reversed(pages):  # oldest first: parents before children
            if not isinstance(c, dict) or lb.sha256(c) in done or not isinstance(c.get("netz_id"), str) or not isinstance(c.get("loesch_hash"), str):
                continue
            self.log.attach("seite", c, c["netz_id"], c["loesch_hash"])
            new += 1
        self.usage_stats["seiten_wartend"] = 0
        return new

    def _ratings(self, ratings: list) -> int:
        """0.40.0: own measurements per content. Only changed values, at most one per content and day, RATINGS_PER_DAY in all — and only
        once no peer is older than 0.39.0 (older ones would reject the type and stop this server's whole chain)."""
        if not ratings:
            return 0
        if blocked := self.log.peers_below(lb.RELAY_MIN):
            self.usage_stats["bewertungen_wartend"] = len(ratings)
            self.usage_stats["bewertung_sperre"] = blocked[:10]
            return 0
        self.usage_stats.pop("bewertung_sperre", None)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        last, n, new = self.log.own_ratings(), self.log.count_own("bewertung", today), 0
        for r in ratings:
            if n >= RATINGS_PER_DAY:
                break
            if not lb.valid_rating(r) or (prev := last.get(r["ziel"])) and (prev[0] == lb.sha256(r) or prev[1] == today):
                continue
            self.log.attach("bewertung", r)
            n, new = n + 1, new + 1
        self.usage_stats["bewertungen_wartend"] = 0
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
                to_send = [e for e in entry_batch if e["inhalt"] is not None and (e["kopf"]["typ"] == "widerruf" or (believed and e["kopf"]["typ"] in ("objekt", "bewertung", "seite", "beitrag")))]
                try:
                    if to_send:
                        self.mcp.inbox(to_send)
                except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
                    log(f"network: inbox to memory failed: {type(e).__name__}: {str(e)[:120]}")
                    return
                self.log.set_checkpoint(pub, entry_batch[-1]["kopf"]["seq"])

    def own_pin(self) -> str | None:
        """Only self-operated TLS has a pin; behind a reverse proxy the CA verifies."""
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
            new = self.outbox()
            if self.paused:
                self.usage_stats["pausiert"] = self.usage_stats.get("pausiert", 0) + 1
                return 0
            new += self._report_address()
            self.build_segment()
            excluding = self.k.address.rstrip("/") if self.k.address else None
            peers = self.log.choose_peers(self.k.neighbors, excluding)
            if self._wait_target and self._wait_target not in peers:  # 0.52.0: the peerhost of the long poll always gets our news
                peers.append(self._wait_target)
            for a in peers:
                new += self.reconcile(a)
            self.inbox()
            self.usage_stats["runden"] += 1
            if new:
                self._signal()
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
            except Exception as e:  # a failed round must not end the service
                log(f"network: round failed: {type(e).__name__}: {str(e)[:200]}")
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
                """Without membership, but with proof of the key and a one-time code."""
                pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                if not pub:
                    return self._send(401, {"fehler": "request not signed or stale"})
                if service._limited("beitritt", JOINS_PER_MIN):
                    return self._send(429, {"fehler": "too many join attempts"})
                try:
                    nonce = json.loads(req_body).get("code")
                except (ValueError, AttributeError):
                    nonce = None
                if reason := service.log.redeem_join(nonce, pub):
                    return self._send(403, {"fehler": reason})
                log(f"network: {lb.pseudonym(pub)} invited with join code")
                service.awake.set()
                return self._send(200, {"eingeladen": lb.pseudonym(pub)})

            def _authenticate(self, req_body: bytes) -> str | None:
                pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                if not pub:
                    self._send(401, {"fehler": "request not signed or stale"})
                    return None
                if service.free:  # 0.45.0: no membership needed — but not blocked here, and limited per key and per address
                    if pub in service.log.blocked or service._limited(f"ip:{self.client_address[0]}", REQUESTS_PER_MIN_IP):
                        self._send(403 if pub in service.log.blocked else 429, {"fehler": "blocked on this server" if pub in service.log.blocked else "too many requests"})
                        return None
                elif not service.log.is_member(pub):
                    self._send(403, {"fehler": "not a member of this network"})
                    return None
                if service._limited(pub):
                    self._send(429, {"fehler": "too many requests"})
                    return None
                return pub

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path in ("/netz/health", "/netz/gesund"):  # version since 0.39.0: peers gate new entry types on it; /netz/health since 0.59.1
                    return self._send(200, {"zustand": "ok", "version": __version__})
                if not self._authenticate(b""):
                    return None
                parts = u.path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["netz", "log"]:
                    q = urllib.parse.parse_qs(u.query)
                    try:
                        from_seq, n = int(q.get("ab", ["0"])[0]), int(q.get("max", [str(PER_FETCH)])[0])
                    except ValueError:
                        return self._send(400, {"fehler": "ab and max must be numbers"})
                    return self._send(200, {"eintraege": service.log.read(parts[2], from_seq, min(n, PER_FETCH))})
                if u.path == "/netz/peers":  # 0.45.0: peer exchange
                    own = [service.k.address.rstrip("/")] if service.k.address and service.k.mode == "peerhost" else []
                    return self._send(200, {"peers": own + [a for a in service.log.public_peers() if a not in own]})
                if len(parts) == 3 and parts[:2] == ["netz", "segmente"]:
                    return self._send(200, {"segmente": service.log.segments(parts[2])})
                return self._send(404, {"fehler": "unknown"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"fehler": "too large"})
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
                        service._signal()  # 0.52.0: peers waiting here learn it now, not at their next round
                    return self._send(200, r)
                if self.path == "/netz/warten":  # 0.52.0: long poll of a peer behind a firewall
                    pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                    try:
                        q = json.loads(req_body or b"{}")
                        theirs, max_s = q.get("koepfe") or {}, float(q.get("max_s") or WAIT_MAX_S)
                    except (ValueError, AttributeError, TypeError):
                        return self._send(400, {"fehler": "koepfe and max_s"})
                    if not isinstance(theirs, dict):
                        return self._send(400, {"fehler": "koepfe must be an object"})
                    return self._send(200, service.wait_for(pub, theirs, max_s))
                if self.path == "/netz/suche/antwort":  # 0.52.0: a waiting peer answers a relayed search
                    pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                    try:
                        body = json.loads(req_body)
                    except ValueError:
                        return self._send(400, {"fehler": "not JSON"})
                    return self._send(204) if service.relay_answer(pub, body if isinstance(body, dict) else {}) else self._send(410, {"fehler": "search unknown or over"})
                if self.path == "/netz/anstoss":
                    service.awake.set()
                    return self._send(204)
                if self.path == "/netz/suche":  # 0.42.0: live search of a member
                    pub = check_header(self.headers.get("Authorization"), self.command, self.path, req_body)
                    if service._limited(f"suche:{pub}", SEARCHES_PER_MIN):
                        service.usage_stats["suchen_abgewiesen"] = service.usage_stats.get("suchen_abgewiesen", 0) + 1
                        return self._send(429, {"fehler": "too many searches"})
                    try:
                        q = json.loads(req_body)
                        query, n = str(q.get("q") or "").strip()[:300], int(q.get("max") or SEARCH_MAX)
                    except (ValueError, AttributeError, TypeError):
                        return self._send(400, {"fehler": "q and max"})
                    if not query:
                        return self._send(400, {"fehler": "q is empty"})
                    try:
                        own = service.answer(query, n)
                    except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError) as e:
                        own = {"pub": service.log.pub, "treffer": [], "fehler": f"memory not reachable: {type(e).__name__}"}
                    relayed = service.relay_search(pub, query, n) if service.k.mode == "peerhost" else {"antworten": [], "gefragt": 0, "ohne_antwort": 0}
                    return self._send(200, {**own, "weitergeleitet": relayed["antworten"], "weitergeleitet_an": relayed["gefragt"], "ohne_antwort": relayed["ohne_antwort"]})
                return self._send(404, {"fehler": "unknown"})
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
        self._signal()
        for srv in (self.server, self.local_server):
            if srv:
                srv.shutdown()
                srv.server_close()
        if self.swarm:
            self.swarm.stop_service()
        self.log.close()


def certificate_pin(req_path: Path) -> str:
    """SHA-256 of the certificate in DER form, as the peer sees it when connecting."""
    pem = req_path.read_text()
    part = pem[pem.index("-----BEGIN CERTIFICATE-----"):pem.index("-----END CERTIFICATE-----")]
    return hashlib.sha256(base64.b64decode("".join(part.splitlines()[1:]))).hexdigest()


def build_code(founders: list[str], start: str, pin: str | None, nonce: str, expiry: float) -> str:
    raw = json.dumps({"g": founders, "s": start, "p": pin, "n": nonce, "a": int(expiry)}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_code(code: str) -> dict:
    """Pure. ValueError with reason if the code does not fit."""
    code = (code or "").strip()
    if not code.startswith(CODE_PREFIX):
        raise ValueError("not a join code (does not start with vinetz1.)")
    try:
        d = json.loads(base64.urlsafe_b64decode(code[len(CODE_PREFIX):] + "=" * (-len(code) % 4)))
    except (ValueError, TypeError) as e:
        raise ValueError("join code is corrupted") from e
    if not isinstance(d, dict) or not isinstance(d.get("g"), list) or not all(isinstance(x, str) and lb._HEX64.match(x) for x in d["g"]) or not d["g"]:
        raise ValueError("join code names no valid founders")
    if not isinstance(d.get("s"), str) or not lb._ADDRESS.match(d["s"]) or not isinstance(d.get("n"), str):
        raise ValueError("join code names no valid address")
    if d.get("p") is not None and not (isinstance(d["p"], str) and lb._HEX64.match(d["p"])):
        raise ValueError("join code has an unusable pin")
    if not isinstance(d.get("a"), int) or d["a"] < time.time():
        raise ValueError("join code has expired")
    return d


def main() -> int:
    k = load()
    if k.mode == "standalone":
        log("network: mode standalone, nothing to do")
        return 0
    if not k.founders and k.kind != "free":
        log("network: no founders configured (vi-mcp net setup)")
        return 2
    d = NetService(k, McpClient(k.mcp_url, k.mcp_token_file))
    if k.mode == "peerhost":
        d.start_server()
    if k.local_token_sha256:  # 0.42.0: live search for the memory
        log(f"network: local search listener on 127.0.0.1:{d.start_local_server()}")
    import signal
    if hasattr(signal, "SIGUSR1"):  # not on Windows (0.54.0)
        signal.signal(signal.SIGUSR1, lambda *_: d.awake.set())  # systemctl kill -s USR1 vi-p2p: round now
    log(f"network: mode {k.mode}, pseudonym {lb.pseudonym(d.log.pub)}, {len(d.log.members())} members known")
    if k.mode == "peer":  # 0.52.0: behind a firewall — keep a long poll open at a peerhost, news arrive in seconds
        threading.Thread(target=d.wait_loop, name="vi-p2p-wait", daemon=True).start()
    try:
        d.main_loop()
    except KeyboardInterrupt:
        pass
    return 0
