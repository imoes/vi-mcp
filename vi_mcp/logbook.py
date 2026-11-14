"""Logbook — per server a signed, chained sequence of entries; the basis of the network. Knows neither transport nor memory.

Header: number, hash of the predecessor, type, hash of the content, signature. Content is separate: if an object is forgotten, the content
disappears and the chain stays valid. Whoever relays a logbook cannot forge, reorder or cut it in the middle (withholding it is possible).
Two different entries with the same number are a fork: this publisher is no longer accepted.

A member is whoever is reachable from a founder via a chain of invitations. Founders and the inviter may exclude;
whoever was invited only via an excluded key drops out as well. Relaying requires signature and fixed rules (checks.py),
believing is decided only by the memory.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import checks

VERSION = 1
TYPE_NAMES = ("objekt", "widerruf", "einladung", "ausschluss", "adresse", "bewertung", "seite", "beitrag", "identitaet")
#: 0.45.0: a free network (art frei) needs no invitation. Instead every key proves once that work went into it: entry 1 of its logbook is
#: an `identitaet` {pub, nonce, bits} with SHA-256(pub ‖ nonce) starting with `bits` zero bits. Cheap to check, expensive in bulk —
#: a server makes one identity in under a minute, a spammer who wants thousands pays thousands of minutes.
DEFAULT_POW_BITS = 26  # measured 11.11.2026: 2.5 M hashes/s in Python on a workstation → ~26 s on average, about a minute on slower servers
MIN_POW_BITS = 8
#: types whose content can be forgotten by the author (netz_id + loesch_hash in the header)
FORGETTABLE = ("objekt", "seite", "beitrag")
#: 0.40.0: a rating names a content hash and five non-negative numbers (net_score.py); peers before 0.39.0 would reject the type
RATING_FIELDS = ("gezeigt", "ja", "nein", "bestaetigt", "widerlegt")
RELAY_MIN = "0.39.0"
HEADER_REQUIRED = {"v", "pub", "seq", "vor", "typ", "sha", "zeit", "sig"}
HEADER_OPTIONAL = {"netz_id", "loesch_hash"}
MAX_CONTENT = 128 * 1024
MAX_PER_DAY = 5000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
#: 0.39.0: forward compatibility. A type or optional header field a newer version introduces is accepted, stored and relayed (signature,
#: chain and quota are checked as always), but not interpreted. Before, an older peer stopped the whole chain of that publisher.
_NAME = re.compile(r"^[a-z][a-z_]{1,19}$")
EXTRA_HEADER_MAX = 4
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: behind a reverse proxy the service lives under a path, e.g. https://host/vi-p2p
_ADDRESS = re.compile(r"^https?://[^/\s?#]+(?:/[A-Za-z0-9._~-]+)*$")


def version_tuple(v: str) -> tuple:
    """'0.39.0' → (0, 39, 0); unusable parts count as 0."""
    out = []
    for part in str(v).split(".")[:3]:
        digits = re.match(r"\d+", part)
        out.append(int(digits.group(0)) if digits else 0)
    return tuple(out + [0] * (3 - len(out)))


def pow_ok(pub_hex: str, nonce: int, bits: int) -> bool:
    """Pure. Does SHA-256(public key ‖ nonce as 8 bytes) start with `bits` zero bits?"""
    if not (isinstance(nonce, int) and not isinstance(nonce, bool) and 0 <= nonce < 2 ** 64 and isinstance(bits, int) and 0 < bits <= 64):
        return False
    try:
        h = int.from_bytes(hashlib.sha256(bytes.fromhex(pub_hex) + nonce.to_bytes(8, "big")).digest(), "big")
    except ValueError:
        return False
    return h >> (256 - bits) == 0


def solve_pow(pub_hex: str, bits: int, start: int = 0) -> int:
    """The work: the first nonce whose hash has `bits` leading zero bits. ~2^bits hashes on average."""
    key, nonce, shift = bytes.fromhex(pub_hex), start, 256 - bits
    sha = hashlib.sha256
    while int.from_bytes(sha(key + nonce.to_bytes(8, "big")).digest(), "big") >> shift:
        nonce += 1
    return nonce


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _crypto():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def generate_keys(fpath: Path) -> str:
    """Create the seed (0600, never overwritten). Returns the public key as hex."""
    priv, _pub, _inv = _crypto()
    if fpath.exists():
        raise ValueError(f"{fpath} already exists")
    k = priv.generate()
    with os.fdopen(os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(k.private_bytes_raw())
    return k.public_key().public_bytes_raw().hex()


def private(fpath: Path):
    return _crypto()[0].from_private_bytes(Path(fpath).read_bytes())


def public_hex(k) -> str:
    return k.public_key().public_bytes_raw().hex()


def valid(pubkey_hex: str, sig_hex: str, data: bytes) -> bool:
    _priv, pub, inv = _crypto()
    try:
        pub.from_public_bytes(bytes.fromhex(pubkey_hex)).verify(bytes.fromhex(sig_hex), data)
        return True
    except (inv, ValueError, TypeError):
        return False


def pseudonym(pubkey_hex: str) -> str:
    """The network knows no host name, only this fingerprint of the key."""
    return "vi-" + hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()[:12]


def entry_hash(header: dict) -> str:
    return sha256(header)


def signature_valid(header: dict) -> bool:
    return isinstance(header.get("sig"), str) and valid(header["pub"], header["sig"], canonical({k: v for k, v in header.items() if k != "sig"}))


def known_type(type_) -> bool:
    return type_ in TYPE_NAMES


def _extra_ok(key, value) -> bool:
    return bool(_NAME.match(key)) and (isinstance(value, str) and len(value) <= 200 or isinstance(value, int) and not isinstance(value, bool))


def header_form(header) -> str | None:
    """Pure. Reason why a header is not in order, otherwise None."""
    if not isinstance(header, dict) or not HEADER_REQUIRED <= set(header):
        return "header has wrong fields"
    extra = set(header) - HEADER_REQUIRED - HEADER_OPTIONAL
    if len(extra) > EXTRA_HEADER_MAX or not all(_extra_ok(k, header[k]) for k in extra):
        return "header has wrong fields"
    if header["v"] != VERSION or not isinstance(header["typ"], str) or not _NAME.match(header["typ"]) or not isinstance(header["pub"], str) or not _HEX64.match(header["pub"]):
        return "header: version, type or key unusable"
    if isinstance(header["seq"], bool) or not isinstance(header["seq"], int) or header["seq"] < 1 or not (header["vor"] is None or (isinstance(header["vor"], str) and _HEX64.match(header["vor"]))):
        return "header: number or predecessor unusable"
    if not isinstance(header["zeit"], str) or not _DATE.match(header["zeit"]) or not isinstance(header["sha"], str) or not _HEX64.match(header["sha"]):
        return "header: date or checksum unusable"
    if header["typ"] in ("objekt", "widerruf", "seite", "beitrag") and not (isinstance(header.get("netz_id"), str) and _HEX32.match(header["netz_id"])):
        return "header: netz_id missing"
    if header["typ"] in FORGETTABLE and not (isinstance(header.get("loesch_hash"), str) and _HEX64.match(header["loesch_hash"])):
        return "header: loesch_hash missing"
    return None


def valid_rating(c) -> bool:
    """Pure. The content of a `bewertung` entry: the target content hash and five non-negative numbers, nothing else."""
    return (isinstance(c, dict) and set(c) == {"ziel", *RATING_FIELDS} and isinstance(c["ziel"], str) and bool(_HEX64.match(c["ziel"]))
            and all(isinstance(c[k], (int, float)) and not isinstance(c[k], bool) and 0 <= c[k] <= 1e6 for k in RATING_FIELDS))


def valid_control_form(type_: str, content) -> bool:
    if not isinstance(content, dict):
        return False
    if type_ == "bewertung":
        return valid_rating(content)
    if type_ == "identitaet":
        return set(content) == {"pub", "nonce", "bits"} and isinstance(content["pub"], str) and bool(_HEX64.match(content["pub"])) \
            and isinstance(content["bits"], int) and not isinstance(content["bits"], bool) and pow_ok(content["pub"], content["nonce"], content["bits"])
    if type_ == "widerruf":
        return set(content) == {"ziel", "token"} and isinstance(content["ziel"], str) and isinstance(content["token"], str) and len(content["token"]) <= 128
    if type_ in ("einladung", "ausschluss"):
        return set(content) == {"pub"} and isinstance(content["pub"], str) and bool(_HEX64.match(content["pub"]))
    if type_ == "adresse":
        # pin: SHA-256 of the TLS certificate, for peerhosts without a public CA (since 0.15.0). Since 0.39.0 further short fields of a newer
        # version are tolerated (before, an older peer rejected the entry and with it the whole chain)
        extra = set(content) - {"adresse", "pin"}
        return "adresse" in content and isinstance(content["adresse"], str) and bool(_ADDRESS.match(content["adresse"])) \
            and ("pin" not in content or (isinstance(content["pin"], str) and bool(_HEX64.match(content["pin"])))) \
            and len(extra) <= EXTRA_HEADER_MAX and all(_NAME.match(k) and len(canonical(content[k])) <= 500 for k in extra)
    return False


def schema_for(net: str) -> str:
    """PostgreSQL schema of a network's logbook (0.50.0): every network service its own, so two networks never share tables."""
    return "netz_" + (re.sub(r"[^a-z0-9_]", "_", str(net).lower())[:50] or "standard")


class Logbook:
    def __init__(self, fpath: Path | str, seed: Path, founders: list[str], internal_ok: bool = False, free_bits: int | None = None,
                 blocked: set[str] | None = None, quota_of=None, schema: str | None = None):
        """fpath: SQLite file, or (0.50.0) a postgresql:// URL — then the tables live in `schema` (one per network, schema_for(net))."""
        from . import db as dbmod
        self.lock = threading.RLock()
        if dbmod.is_url(fpath):
            self.db = dbmod.connect(str(fpath), schema=schema, autocommit=True)
        else:
            Path(fpath).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            old_umask_value = os.umask(0o077)
            try:
                self.db = sqlite3.connect(str(fpath), check_same_thread=False, timeout=30, isolation_level=None)
            finally:
                os.umask(old_umask_value)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS eintrag (pub TEXT NOT NULL, seq INTEGER NOT NULL, hash TEXT NOT NULL, typ TEXT NOT NULL, sha TEXT NOT NULL, netz_id TEXT, loesch_hash TEXT, zeit TEXT NOT NULL, kopf TEXT NOT NULL, PRIMARY KEY (pub, seq));
            CREATE INDEX IF NOT EXISTS eintrag_netz ON eintrag (netz_id);
            CREATE INDEX IF NOT EXISTS eintrag_typ ON eintrag (typ);
            CREATE TABLE IF NOT EXISTS inhalt (sha TEXT PRIMARY KEY, daten TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS grab (netz_id TEXT PRIMARY KEY, token_sha TEXT NOT NULL, zeit TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS gabelung (pub TEXT PRIMARY KEY, seq INTEGER NOT NULL, zeit TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS verstoss (pub TEXT PRIMARY KEY, n INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS stand (pub TEXT PRIMARY KEY, seq INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS peer (adresse TEXT PRIMARY KEY, quelle TEXT NOT NULL, zuletzt REAL, fehler INTEGER NOT NULL DEFAULT 0, naechster REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS beitritt (nonce_sha TEXT PRIMARY KEY, ablauf REAL NOT NULL, benutzt TEXT);
            CREATE TABLE IF NOT EXISTS segment (sha256 TEXT PRIMARY KEY, pub TEXT NOT NULL, von INTEGER NOT NULL, bis INTEGER NOT NULL, torrent TEXT NOT NULL, port INTEGER NOT NULL, datei TEXT NOT NULL);
        """)
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(peer)")]
        for col, typ in (("pin", "TEXT"), ("version", "TEXT"), ("version_zeit", "REAL"), ("fehlt_hier", "INTEGER"), ("fehlt_dort", "INTEGER")):
            if col not in cols:  # 0.39.0: version and backlog per peer, for vi_net_status and vi_stats
                self.db.execute(f"ALTER TABLE peer ADD COLUMN {col} {typ}")
        #: 0.39.0: a company network relays internal names (its members belong to one organisation); the open network rejects them
        self.internal_ok = internal_ok
        self.k = private(seed)
        self.pub = public_hex(self.k)
        self.founders = list(founders)
        #: 0.45.0 free network: membership = a valid identity proof of at least free_bits; None = closed network (invitations)
        self.free_bits = free_bits
        self.blocked: set[str] = set(blocked or ())  # keys this server does not accept, relay or answer (local, never for others)
        self.quota_of = quota_of  # pub → entries per day; None = MAX_PER_DAY for everyone
        self.db.execute("CREATE TABLE IF NOT EXISTS identitaet (pub TEXT PRIMARY KEY, bits INTEGER NOT NULL, zeit TEXT NOT NULL)")
        self._members: set[str] | None = None

    # ---- own entries ----

    def _header_of(self, pub: str) -> tuple[int, str | None]:
        z = self.db.execute("SELECT seq, hash FROM eintrag WHERE pub = ? ORDER BY seq DESC LIMIT 1", (pub,)).fetchone()
        return (z[0], z[1]) if z else (0, None)

    def attach(self, type_: str, content: dict, net_id: str | None = None, delete_hash: str | None = None) -> dict:
        if type_ not in FORGETTABLE and not valid_control_form(type_, content):
            raise ValueError(f"content does not fit type {type_}")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                seq, prev_hash = self._header_of(self.pub)
                header = {"v": VERSION, "pub": self.pub, "seq": seq + 1, "vor": prev_hash, "typ": type_, "sha": sha256(content), "zeit": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        **({"netz_id": net_id} if net_id else {}), **({"loesch_hash": delete_hash} if delete_hash else {})}
                header["sig"] = self.k.sign(canonical(header)).hex()
                self._insert(header, content)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        self._apply_effects(header, content)
        return header

    def _insert(self, header: dict, content) -> None:
        self.db.execute("INSERT INTO eintrag (pub, seq, hash, typ, sha, netz_id, loesch_hash, zeit, kopf) VALUES (?,?,?,?,?,?,?,?,?)",
                        (header["pub"], header["seq"], entry_hash(header), header["typ"], header["sha"], header.get("netz_id"), header.get("loesch_hash"), header["zeit"], json.dumps(header, sort_keys=True)))
        if content is not None:
            self.db.execute("INSERT OR IGNORE INTO inhalt (sha, daten) VALUES (?,?)", (header["sha"], json.dumps(content, ensure_ascii=False, sort_keys=True)))

    def _apply_effects(self, header: dict, content) -> None:
        """What an entry causes, no matter where it came from."""
        if header["typ"] == "identitaet":
            self.db.execute("INSERT OR IGNORE INTO identitaet (pub, bits, zeit) VALUES (?,?,?)", (header["pub"], content["bits"], header["zeit"]))
            self._members = None
        elif header["typ"] in ("einladung", "ausschluss"):
            self._members = None
        elif header["typ"] == "adresse" and header["pub"] != self.pub:
            self.peer_remember(content["adresse"], "logbuch", content.get("pin"))
        elif header["typ"] == "widerruf":
            self.forget(content["ziel"], content["token"])

    # ---- Forgetting ----

    def forget(self, net_id: str, token: str) -> list[tuple[str, int]]:
        """Delete the content if the proof matches; remember a tombstone. Returns (pub, seq) of the deleted entries."""
        evidence = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            lines = self.db.execute("SELECT pub, seq, sha, loesch_hash FROM eintrag WHERE netz_id = ? AND typ IN ('objekt', 'seite', 'beitrag')", (net_id,)).fetchall()
            if lines and not any(hmac.compare_digest(z[3], evidence) for z in lines):
                return []  # wrong proof
            remove = []
            for pub, seq, sha, l in lines:
                if hmac.compare_digest(l, evidence):
                    self.db.execute("DELETE FROM inhalt WHERE sha = ?", (sha,))
                    remove.append((pub, seq))
            self.db.execute("INSERT OR IGNORE INTO grab (netz_id, token_sha, zeit) VALUES (?,?,?)", (net_id, evidence, time.strftime("%Y-%m-%d", time.gmtime())))
            for pub, seq in remove:
                self.discard_segments(pub, seq)
        return remove

    # ---- Membership ----

    def members(self) -> set[str]:
        with self.lock:
            if self._members is not None:
                return set(self._members)
            if self.free_bits is not None:  # free network: whoever proved the work, minus what this server blocks
                self._members = {r[0] for r in self.db.execute("SELECT pub FROM identitaet WHERE bits >= ?", (self.free_bits,))} - self.blocked
                return set(self._members)
            edges: dict[str, set[str]] = {}
            outputs = []
            for pub, type_, data in self.db.execute("SELECT e.pub, e.typ, i.daten FROM eintrag e JOIN inhalt i ON i.sha = e.sha WHERE e.typ IN ('einladung', 'ausschluss') ORDER BY e.pub, e.seq"):
                target = json.loads(data)["pub"]
                if type_ == "einladung":
                    edges.setdefault(pub, set()).add(target)
                else:
                    outputs.append((pub, target))
            excluded = {target for who, target in outputs if (who in self.founders or target in edges.get(who, set())) and target not in self.founders}
            seen = set(self.founders)
            open_ = list(self.founders)
            while open_:
                for n in edges.get(open_.pop(), set()):
                    if n not in seen and n not in excluded:
                        seen.add(n)
                        open_.append(n)
            self._members = seen
            return set(seen)

    def is_member(self, pub: str) -> bool:
        return pub in self.members()

    # ---- Exchange ----

    def headers(self) -> dict[str, int]:
        with self.lock:
            return dict(self.db.execute("SELECT pub, MAX(seq) FROM eintrag GROUP BY pub").fetchall())

    def read(self, pub: str, from_seq: int, count: int = 500) -> list[dict]:
        with self.lock:
            lines = self.db.execute("SELECT e.kopf, i.daten FROM eintrag e LEFT JOIN inhalt i ON i.sha = e.sha WHERE e.pub = ? AND e.seq > ? ORDER BY e.seq LIMIT ?", (pub, from_seq, min(count, 2000))).fetchall()
        return [{"kopf": json.loads(k), "inhalt": json.loads(d) if d else None} for k, d in lines]

    def _violation(self, pub: str) -> None:
        self.db.execute("INSERT INTO verstoss (pub, n) VALUES (?, 1) ON CONFLICT(pub) DO UPDATE SET n = verstoss.n + 1", (pub,))

    def _object_content(self, header: dict, content):
        """The content of an object to store, or None (forgotten, missing, or violating the rules)."""
        tombstone = self.db.execute("SELECT token_sha FROM grab WHERE netz_id = ?", (header["netz_id"],)).fetchone()
        if tombstone and hmac.compare_digest(tombstone[0], header["loesch_hash"]):
            return None
        if content is None:
            return None
        if sha256(content) != header["sha"] or len(canonical(content)) > MAX_CONTENT or not isinstance(content, dict) or content.get("netz_id") != header["netz_id"] or content.get("loesch_hash") != header["loesch_hash"]:
            self._violation(header["pub"])
            return None
        rules = {"seite": checks.check_page, "beitrag": checks.check_post}.get(header["typ"]) or (lambda c, internal_ok: checks.check(c, may_reflex=True, internal_ok=internal_ok))
        if rules(content, internal_ok=self.internal_ok).verdict == "ablehnen":
            self._violation(header["pub"])
            return None
        return content

    def ingest(self, entries) -> dict:
        """Check and store foreign entries. An error only stops this publisher's logbook for this pass."""
        report = {"neu": 0, "bekannt": 0, "abgelehnt": 0, "unbekannt": 0, "gruende": []}
        stopped: set[str] = set()

        def stop(pub, reason):
            report["abgelehnt"] += 1
            report["gruende"].append(f"{pseudonym(pub) if isinstance(pub, str) and _HEX64.match(pub) else '?'}: {reason}")
            stopped.add(pub)
        for e in entries if isinstance(entries, list) else []:
            header, content = e.get("kopf") if isinstance(e, dict) else None, e.get("inhalt") if isinstance(e, dict) else None
            if reason := header_form(header):
                stop(header.get("pub") if isinstance(header, dict) else None, reason)
                continue
            pub = header["pub"]
            if pub in stopped:
                continue
            with self.lock:
                if self.db.execute("SELECT 1 FROM gabelung WHERE pub = ?", (pub,)).fetchone():
                    stop(pub, "fork known")
                    continue
                if pub in self.blocked:
                    stop(pub, "blocked on this server")
                    continue
                opens_identity = self.free_bits is not None and header["seq"] == 1 and header["typ"] == "identitaet"
                if not opens_identity and not self.is_member(pub):
                    stop(pub, "no identity proof known (free network: entry 1 must be the identity)" if self.free_bits is not None else "not a member")
                    continue
                if not signature_valid(header):
                    stop(pub, "signature invalid")
                    continue
                present = self.db.execute("SELECT hash FROM eintrag WHERE pub = ? AND seq = ?", (pub, header["seq"])).fetchone()
                if present:
                    if present[0] != entry_hash(header):
                        self.db.execute("INSERT OR REPLACE INTO gabelung (pub, seq, zeit) VALUES (?,?,?)", (pub, header["seq"], header["zeit"]))
                        stop(pub, f"fork at number {header['seq']}")
                        continue
                    report["bekannt"] += 1
                    if header["typ"] in FORGETTABLE and content is not None and not self.db.execute("SELECT 1 FROM inhalt WHERE sha = ?", (header["sha"],)).fetchone():
                        if (good := self._object_content(header, content)) is not None:
                            self.db.execute("INSERT OR IGNORE INTO inhalt (sha, daten) VALUES (?,?)", (header["sha"], json.dumps(good, ensure_ascii=False, sort_keys=True)))
                    continue
                seq, prev_hash = self._header_of(pub)
                if header["seq"] != seq + 1 or header["vor"] != prev_hash:
                    stop(pub, f"chain broken at number {header['seq']}")
                    continue
                if self.db.execute("SELECT COUNT(*) FROM eintrag WHERE pub = ? AND zeit = ?", (pub, header["zeit"])).fetchone()[0] >= (self.quota_of(pub) if self.quota_of else MAX_PER_DAY):
                    stop(pub, "daily quota exhausted")
                    continue
                if header["typ"] in FORGETTABLE:
                    to_save = self._object_content(header, content)
                elif not known_type(header["typ"]):
                    # a type of a newer version: relayed, not interpreted; content only against checksum and size
                    if content is not None and (sha256(content) != header["sha"] or len(canonical(content)) > MAX_CONTENT):
                        self._violation(pub)
                        stop(pub, f"content of type {header['typ']} unusable")
                        continue
                    to_save = content
                    report["unbekannt"] += 1
                else:
                    if not valid_control_form(header["typ"], content) or sha256(content) != header["sha"] or (header["typ"] == "widerruf" and content["ziel"] != header["netz_id"]) \
                            or (header["typ"] == "identitaet" and (content["pub"] != pub or header["seq"] != 1 or (self.free_bits is not None and content["bits"] < self.free_bits))):
                        self._violation(pub)
                        stop(pub, f"content of type {header['typ']} unusable")
                        continue
                    to_save = content
                self._insert(header, to_save)
                report["neu"] += 1
                if to_save is not None and known_type(header["typ"]):
                    self._apply_effects(header, to_save)
        report["gruende"] = report["gruende"][:20]
        return report

    # ---- Handover to the memory ----

    def new_since_checkpoint(self, pub: str, count: int = 200) -> list[dict]:
        with self.lock:
            z = self.db.execute("SELECT seq FROM stand WHERE pub = ?", (pub,)).fetchone()
        return self.read(pub, z[0] if z else 0, count)

    def set_checkpoint(self, pub: str, seq: int) -> None:
        with self.lock:
            self.db.execute("INSERT INTO stand (pub, seq) VALUES (?,?) ON CONFLICT(pub) DO UPDATE SET seq = excluded.seq", (pub, seq))

    def own_objects(self) -> set[tuple[str, str]]:
        with self.lock:
            return set(self.db.execute("SELECT netz_id, sha FROM eintrag WHERE pub = ? AND typ = 'objekt'", (self.pub,)).fetchall())

    def own_shas(self, type_: str) -> set[str]:
        with self.lock:
            return {r[0] for r in self.db.execute("SELECT sha FROM eintrag WHERE pub = ? AND typ = ?", (self.pub, type_))}

    def own_ratings(self) -> dict[str, tuple[str, str, dict]]:
        """content hash → (sha of the last own rating, its date, its data)."""
        with self.lock:
            lines = self.db.execute("SELECT e.sha, e.zeit, i.daten FROM eintrag e JOIN inhalt i ON i.sha = e.sha WHERE e.pub = ? AND e.typ = 'bewertung' ORDER BY e.seq",
                                    (self.pub,)).fetchall()
        return {(d := json.loads(raw))["ziel"]: (sha, z, d) for sha, z, raw in lines}

    def count_own(self, type_: str, day: str | None = None) -> int:
        with self.lock:
            if day:
                return self.db.execute("SELECT COUNT(*) FROM eintrag WHERE pub = ? AND typ = ? AND zeit = ?", (self.pub, type_, day)).fetchone()[0]
            return self.db.execute("SELECT COUNT(*) FROM eintrag WHERE pub = ? AND typ = ?", (self.pub, type_)).fetchone()[0]

    def own_revocations(self) -> set[str]:
        with self.lock:
            return {r[0] for r in self.db.execute("SELECT netz_id FROM eintrag WHERE pub = ? AND typ = 'widerruf'", (self.pub,))}

    def last_own_address(self) -> dict | None:
        with self.lock:
            z = self.db.execute("SELECT i.daten FROM eintrag e JOIN inhalt i ON i.sha = e.sha WHERE e.pub = ? AND e.typ = 'adresse' ORDER BY e.seq DESC LIMIT 1", (self.pub,)).fetchone()
        return json.loads(z[0]) if z else None

    # ---- Peers ----

    def peer_remember(self, address: str, source: str, pin: str | None = None) -> None:
        """A pin only comes from a signed source: the peer's own adresse entry or a join code."""
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO peer (adresse, quelle) VALUES (?,?)", (address.rstrip("/"), source))
            if pin:
                self.db.execute("UPDATE peer SET pin = ? WHERE adresse = ?", (pin, address.rstrip("/")))

    def pin(self, address: str) -> str | None:
        with self.lock:
            z = self.db.execute("SELECT pin FROM peer WHERE adresse = ?", (address.rstrip("/"),)).fetchone()
        return z[0] if z else None

    def peers(self) -> list[dict]:
        with self.lock:
            lines = self.db.execute("SELECT adresse, quelle, pin, zuletzt, fehler, naechster, version, fehlt_hier, fehlt_dort FROM peer ORDER BY adresse").fetchall()
        return [{"adresse": a, "quelle": q, "pin": p, "zuletzt": z, "fehler": f, "naechster": n, "version": v, "fehlt_hier": fh, "fehlt_dort": fd}
                for a, q, p, z, f, n, v, fh, fd in lines]

    # ---- Joining with a code: one-time, time-limited, only the hash is stored here ----

    def create_join(self, nonce: str, valid_s: float) -> None:
        with self.lock:
            self.db.execute("INSERT INTO beitritt (nonce_sha, ablauf) VALUES (?,?)", (hashlib.sha256(nonce.encode()).hexdigest(), time.time() + valid_s))

    def redeem_join(self, nonce: str, pub: str) -> str | None:
        """Reason for rejection or None. On success this server invites the new key."""
        if not isinstance(nonce, str) or len(nonce) > 200:
            return "code unusable"
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                z = self.db.execute("SELECT ablauf, benutzt FROM beitritt WHERE nonce_sha = ?", (hashlib.sha256(nonce.encode()).hexdigest(),)).fetchone()
                if not z or z[1] or z[0] < time.time():
                    self.db.execute("ROLLBACK")
                    return "join code invalid, expired or already used"
                self.db.execute("UPDATE beitritt SET benutzt = ? WHERE nonce_sha = ?", (pub, hashlib.sha256(nonce.encode()).hexdigest()))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        if not self.is_member(pub):
            self.attach("einladung", {"pub": pub})
        return None

    def ensure_identity(self, bits: int) -> int | None:
        """Free network: make entry 1 the identity proof. Returns the seconds of work, None if it existed. Refuses if the logbook already has
        other entries (peers would reject them all, since they come before the proof)."""
        with self.lock:
            if self.db.execute("SELECT 1 FROM identitaet WHERE pub = ?", (self.pub,)).fetchone():
                return None
            if self._header_of(self.pub)[0]:
                raise ValueError("this logbook already has entries: a free network needs the identity as entry 1 — set up a new network (own --network name)")
        t0 = time.time()
        nonce = solve_pow(self.pub, bits)
        self.attach("identitaet", {"pub": self.pub, "nonce": nonce, "bits": bits})
        return round(time.time() - t0, 1)

    def public_peers(self, limit: int = 50) -> list[str]:
        """0.45.0: addresses this server reached in the last 7 days — for the peer exchange."""
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT adresse FROM peer WHERE fehler = 0 AND zuletzt >= ? ORDER BY zuletzt DESC LIMIT ?",
                                                  (time.time() - 7 * 86400, limit))]

    def peer_count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM peer").fetchone()[0]

    def choose_peers(self, n: int, excluding: str | None = None) -> list[str]:
        with self.lock:
            all_ = [r[0] for r in self.db.execute("SELECT adresse FROM peer WHERE naechster <= ?", (time.time(),)) if r[0] != excluding and r[0] not in self.blocked]
        random.shuffle(all_)
        return all_[:n]

    def peer_state(self, address: str, version: str | None = None, missing_here: int | None = None, missing_there: int | None = None) -> None:
        """0.39.0: what a peer reported at the last reconciliation (version from /netz/gesund, backlog in entries both ways)."""
        with self.lock:
            if version is not None:
                self.db.execute("UPDATE peer SET version = ?, version_zeit = ? WHERE adresse = ?", (str(version)[:20], time.time(), address))
            if missing_here is not None:
                self.db.execute("UPDATE peer SET fehlt_hier = ?, fehlt_dort = ? WHERE adresse = ?", (missing_here, missing_there, address))

    def peers_below(self, minimum: str, days: float = 7) -> list[str]:
        """Peers seen in the last `days` whose reported version is older than `minimum` or unknown. Guards a new entry type."""
        with self.lock:
            lines = self.db.execute("SELECT adresse, version FROM peer WHERE zuletzt >= ?", (time.time() - days * 86400,)).fetchall()
        return sorted(a for a, v in lines if not v or version_tuple(v) < version_tuple(minimum))

    def peer_result(self, address: str, ok: bool) -> None:
        with self.lock:
            if ok:
                self.db.execute("UPDATE peer SET zuletzt = ?, fehler = 0, naechster = 0 WHERE adresse = ?", (time.time(), address))
            else:
                row = self.db.execute("SELECT fehler FROM peer WHERE adresse = ?", (address,)).fetchone()
                errors = int(row[0] or 0) if row else 0  # backoff 30 s · 2^errors, at most an hour (computed here: portable SQL)
                self.db.execute("UPDATE peer SET fehler = fehler + 1, naechster = ? WHERE adresse = ?",
                                (time.time() + min(3600, 30 * (1 << min(errors, 7))), address))

    # ---- Segments: transport cache for torrent, without evidential value of their own ----

    def remember_segment(self, sha: str, pub: str, from_: int, until: int, torrent: bytes, port: int, file: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO segment (sha256, pub, von, bis, torrent, port, datei) VALUES (?,?,?,?,?,?,?)", (sha, pub, from_, until, base64.b64encode(torrent).decode(), port, file))

    def segments(self, pub: str) -> list[dict]:
        with self.lock:
            z = self.db.execute("SELECT sha256, von, bis, torrent, port FROM segment WHERE pub = ? ORDER BY von", (pub,)).fetchall()
        return [{"sha256": a, "von": b, "bis": c, "torrent": d, "port": e} for a, b, c, d, e in z]

    def segments_local(self) -> list[tuple[str, str, str]]:
        with self.lock:
            return self.db.execute("SELECT sha256, torrent, datei FROM segment").fetchall()

    def last_segment_until(self, pub: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COALESCE(MAX(bis), 0) FROM segment WHERE pub = ?", (pub,)).fetchone()[0]

    def discard_segments(self, pub: str, seq: int) -> None:
        """A segment with forgotten content must not be distributed further. The file drops out at the next reconciliation of the swarm list."""
        with self.lock:
            for (d,) in self.db.execute("SELECT datei FROM segment WHERE pub = ? AND von <= ? AND bis >= ?", (pub, seq, seq)).fetchall():
                try:
                    Path(d).unlink(missing_ok=True)
                except OSError:
                    pass
            self.db.execute("DELETE FROM segment WHERE pub = ? AND von <= ? AND bis >= ?", (pub, seq, seq))

    def status(self) -> dict:
        with self.lock:
            d = {"eintraege": self.db.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0], "inhalte": self.db.execute("SELECT COUNT(*) FROM inhalt").fetchone()[0],
                 "grabsteine": self.db.execute("SELECT COUNT(*) FROM grab").fetchone()[0], "gabelungen": self.db.execute("SELECT COUNT(*) FROM gabelung").fetchone()[0],
                 "verstoesse": self.db.execute("SELECT COALESCE(SUM(n), 0) FROM verstoss").fetchone()[0], "segmente": self.db.execute("SELECT COUNT(*) FROM segment").fetchone()[0],
                 "peers": self.db.execute("SELECT COUNT(*) FROM peer").fetchone()[0], "peers_erreichbar": self.db.execute("SELECT COUNT(*) FROM peer WHERE fehler = 0 AND zuletzt IS NOT NULL").fetchone()[0],
                 "unbekannte_typen": self.db.execute("SELECT COUNT(*) FROM eintrag WHERE typ NOT IN (%s)" % ",".join("?" * len(TYPE_NAMES)), TYPE_NAMES).fetchone()[0]}
        d["identitaeten"] = self.db.execute("SELECT COUNT(*) FROM identitaet").fetchone()[0]
        return {**d, "mitglieder": len(self.members()), "gesperrt": len(self.blocked)}

    def close(self) -> None:
        with self.lock:
            self.db.close()
