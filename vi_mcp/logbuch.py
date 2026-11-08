"""Logbuch — je Server eine signierte, verkettete Folge von Einträgen; Grundlage des Netzes. Kennt weder Transport noch Gedächtnis.

Kopf: Nummer, Hash des Vorgängers, Typ, Hash des Inhalts, Signatur. Inhalt getrennt: Wird ein Objekt vergessen, verschwindet der Inhalt,
die Kette bleibt gültig. Wer ein Logbuch weiterträgt, kann es nicht fälschen, umordnen oder in der Mitte kürzen (zurückhalten kann er es).
Zwei verschiedene Einträge mit derselben Nummer sind eine Gabelung: Dieser Herausgeber wird nicht mehr angenommen.

Mitglied ist, wer von einem Gründer aus über eine Kette von Einladungen erreichbar ist. Ausschließen dürfen Gründer und der Einladende;
wer nur über einen Ausgeschlossenen eingeladen wurde, fällt mit heraus. Weitertragen setzt Signatur und feste Regeln voraus (pruefung.py),
Glauben entscheidet erst das Gedächtnis.
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

from . import pruefung

VERSION = 1
TYPEN = ("objekt", "widerruf", "einladung", "ausschluss", "adresse")
KOPF_PFLICHT = {"v", "pub", "seq", "vor", "typ", "sha", "zeit", "sig"}
KOPF_FREI = {"netz_id", "loesch_hash"}
MAX_INHALT = 128 * 1024
MAX_JE_TAG = 5000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: hinter einem Reverse-Proxy liegt der Dienst unter einem Pfad, z. B. https://host/vi-p2p
_ADRESSE = re.compile(r"^https?://[^/\s?#]+(?:/[A-Za-z0-9._~-]+)*$")


def kanonisch(wert) -> bytes:
    return json.dumps(wert, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(wert) -> str:
    return hashlib.sha256(kanonisch(wert)).hexdigest()


def _krypto():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def schluessel_erzeugen(pfad: Path) -> str:
    """Seed anlegen (0600, wird nie überschrieben). Liefert den öffentlichen Schlüssel als Hex."""
    priv, _pub, _inv = _krypto()
    if pfad.exists():
        raise ValueError(f"{pfad} existiert bereits")
    k = priv.generate()
    with os.fdopen(os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(k.private_bytes_raw())
    return k.public_key().public_bytes_raw().hex()


def privat(pfad: Path):
    return _krypto()[0].from_private_bytes(Path(pfad).read_bytes())


def oeffentlich_hex(k) -> str:
    return k.public_key().public_bytes_raw().hex()


def gueltig(pubkey_hex: str, sig_hex: str, daten: bytes) -> bool:
    _priv, pub, inv = _krypto()
    try:
        pub.from_public_bytes(bytes.fromhex(pubkey_hex)).verify(bytes.fromhex(sig_hex), daten)
        return True
    except (inv, ValueError, TypeError):
        return False


def pseudonym(pubkey_hex: str) -> str:
    """Das Netz kennt keinen Hostnamen, nur diesen Abdruck des Schlüssels."""
    return "vi-" + hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()[:12]


def eintrag_hash(kopf: dict) -> str:
    return sha256(kopf)


def signatur_stimmt(kopf: dict) -> bool:
    return isinstance(kopf.get("sig"), str) and gueltig(kopf["pub"], kopf["sig"], kanonisch({k: v for k, v in kopf.items() if k != "sig"}))


def kopf_form(kopf) -> str | None:
    """Rein. Grund, warum ein Kopf nicht in Ordnung ist, sonst None."""
    if not isinstance(kopf, dict) or not KOPF_PFLICHT <= set(kopf) or not set(kopf) <= KOPF_PFLICHT | KOPF_FREI:
        return "Kopf hat falsche Felder"
    if kopf["v"] != VERSION or kopf["typ"] not in TYPEN or not isinstance(kopf["pub"], str) or not _HEX64.match(kopf["pub"]):
        return "Kopf: Version, Typ oder Schlüssel unbrauchbar"
    if isinstance(kopf["seq"], bool) or not isinstance(kopf["seq"], int) or kopf["seq"] < 1 or not (kopf["vor"] is None or (isinstance(kopf["vor"], str) and _HEX64.match(kopf["vor"]))):
        return "Kopf: Nummer oder Vorgänger unbrauchbar"
    if not isinstance(kopf["zeit"], str) or not _DATUM.match(kopf["zeit"]) or not isinstance(kopf["sha"], str) or not _HEX64.match(kopf["sha"]):
        return "Kopf: Datum oder Prüfsumme unbrauchbar"
    if kopf["typ"] in ("objekt", "widerruf") and not (isinstance(kopf.get("netz_id"), str) and _HEX32.match(kopf["netz_id"])):
        return "Kopf: netz_id fehlt"
    if kopf["typ"] == "objekt" and not (isinstance(kopf.get("loesch_hash"), str) and _HEX64.match(kopf["loesch_hash"])):
        return "Kopf: loesch_hash fehlt"
    return None


def steuer_form(typ: str, inhalt) -> bool:
    if not isinstance(inhalt, dict):
        return False
    if typ == "widerruf":
        return set(inhalt) == {"ziel", "token"} and isinstance(inhalt["ziel"], str) and isinstance(inhalt["token"], str) and len(inhalt["token"]) <= 128
    if typ in ("einladung", "ausschluss"):
        return set(inhalt) == {"pub"} and isinstance(inhalt["pub"], str) and bool(_HEX64.match(inhalt["pub"]))
    if typ == "adresse":
        # pin: SHA-256 des TLS-Zertifikats, für peerhosts ohne öffentliche CA (seit 0.15.0; ältere Peers lehnen das Feld ab)
        return set(inhalt) in ({"adresse"}, {"adresse", "pin"}) and isinstance(inhalt["adresse"], str) and bool(_ADRESSE.match(inhalt["adresse"])) \
            and ("pin" not in inhalt or (isinstance(inhalt["pin"], str) and bool(_HEX64.match(inhalt["pin"]))))
    return False


class Logbuch:
    def __init__(self, pfad: Path, seed: Path, gruender: list[str]):
        Path(pfad).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.sperre = threading.RLock()
        alte = os.umask(0o077)
        try:
            self.db = sqlite3.connect(str(pfad), check_same_thread=False, timeout=30, isolation_level=None)
        finally:
            os.umask(alte)
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
        if "pin" not in [r[1] for r in self.db.execute("PRAGMA table_info(peer)")]:
            self.db.execute("ALTER TABLE peer ADD COLUMN pin TEXT")
        self.k = privat(seed)
        self.pub = oeffentlich_hex(self.k)
        self.gruender = list(gruender)
        self._mitglieder: set[str] | None = None

    # ---- eigene Einträge ----

    def _kopf_von(self, pub: str) -> tuple[int, str | None]:
        z = self.db.execute("SELECT seq, hash FROM eintrag WHERE pub = ? ORDER BY seq DESC LIMIT 1", (pub,)).fetchone()
        return (z[0], z[1]) if z else (0, None)

    def anhaengen(self, typ: str, inhalt: dict, netz_id: str | None = None, loesch_hash: str | None = None) -> dict:
        if typ != "objekt" and not steuer_form(typ, inhalt):
            raise ValueError(f"Inhalt passt nicht zu Typ {typ}")
        with self.sperre:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                seq, vor = self._kopf_von(self.pub)
                kopf = {"v": VERSION, "pub": self.pub, "seq": seq + 1, "vor": vor, "typ": typ, "sha": sha256(inhalt), "zeit": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        **({"netz_id": netz_id} if netz_id else {}), **({"loesch_hash": loesch_hash} if loesch_hash else {})}
                kopf["sig"] = self.k.sign(kanonisch(kopf)).hex()
                self._einfuegen(kopf, inhalt)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        self._folgen(kopf, inhalt)
        return kopf

    def _einfuegen(self, kopf: dict, inhalt) -> None:
        self.db.execute("INSERT INTO eintrag (pub, seq, hash, typ, sha, netz_id, loesch_hash, zeit, kopf) VALUES (?,?,?,?,?,?,?,?,?)",
                        (kopf["pub"], kopf["seq"], eintrag_hash(kopf), kopf["typ"], kopf["sha"], kopf.get("netz_id"), kopf.get("loesch_hash"), kopf["zeit"], json.dumps(kopf, sort_keys=True)))
        if inhalt is not None:
            self.db.execute("INSERT OR IGNORE INTO inhalt (sha, daten) VALUES (?,?)", (kopf["sha"], json.dumps(inhalt, ensure_ascii=False, sort_keys=True)))

    def _folgen(self, kopf: dict, inhalt) -> None:
        """Was ein Eintrag bewirkt, egal woher er kam."""
        if kopf["typ"] in ("einladung", "ausschluss"):
            self._mitglieder = None
        elif kopf["typ"] == "adresse" and kopf["pub"] != self.pub:
            self.peer_merken(inhalt["adresse"], "logbuch", inhalt.get("pin"))
        elif kopf["typ"] == "widerruf":
            self.vergiss(inhalt["ziel"], inhalt["token"])

    # ---- Vergessen ----

    def vergiss(self, netz_id: str, token: str) -> list[tuple[str, int]]:
        """Inhalt löschen, wenn der Nachweis passt; Grabstein merken. Liefert (pub, seq) der gelöschten Einträge."""
        beleg = hashlib.sha256(token.encode()).hexdigest()
        with self.sperre:
            zeilen = self.db.execute("SELECT pub, seq, sha, loesch_hash FROM eintrag WHERE netz_id = ? AND typ = 'objekt'", (netz_id,)).fetchall()
            if zeilen and not any(hmac.compare_digest(z[3], beleg) for z in zeilen):
                return []  # falscher Nachweis
            weg = []
            for pub, seq, sha, l in zeilen:
                if hmac.compare_digest(l, beleg):
                    self.db.execute("DELETE FROM inhalt WHERE sha = ?", (sha,))
                    weg.append((pub, seq))
            self.db.execute("INSERT OR IGNORE INTO grab (netz_id, token_sha, zeit) VALUES (?,?,?)", (netz_id, beleg, time.strftime("%Y-%m-%d", time.gmtime())))
            for pub, seq in weg:
                self.segmente_verwerfen(pub, seq)
        return weg

    # ---- Mitgliedschaft ----

    def mitglieder(self) -> set[str]:
        with self.sperre:
            if self._mitglieder is not None:
                return set(self._mitglieder)
            kanten: dict[str, set[str]] = {}
            aus = []
            for pub, typ, daten in self.db.execute("SELECT e.pub, e.typ, i.daten FROM eintrag e JOIN inhalt i ON i.sha = e.sha WHERE e.typ IN ('einladung', 'ausschluss') ORDER BY e.pub, e.seq"):
                ziel = json.loads(daten)["pub"]
                if typ == "einladung":
                    kanten.setdefault(pub, set()).add(ziel)
                else:
                    aus.append((pub, ziel))
            raus = {ziel for wer, ziel in aus if (wer in self.gruender or ziel in kanten.get(wer, set())) and ziel not in self.gruender}
            gesehen = set(self.gruender)
            offen = list(self.gruender)
            while offen:
                for n in kanten.get(offen.pop(), set()):
                    if n not in gesehen and n not in raus:
                        gesehen.add(n)
                        offen.append(n)
            self._mitglieder = gesehen
            return set(gesehen)

    def ist_mitglied(self, pub: str) -> bool:
        return pub in self.mitglieder()

    # ---- Austausch ----

    def koepfe(self) -> dict[str, int]:
        with self.sperre:
            return dict(self.db.execute("SELECT pub, MAX(seq) FROM eintrag GROUP BY pub").fetchall())

    def lies(self, pub: str, ab: int, anzahl: int = 500) -> list[dict]:
        with self.sperre:
            zeilen = self.db.execute("SELECT e.kopf, i.daten FROM eintrag e LEFT JOIN inhalt i ON i.sha = e.sha WHERE e.pub = ? AND e.seq > ? ORDER BY e.seq LIMIT ?", (pub, ab, min(anzahl, 2000))).fetchall()
        return [{"kopf": json.loads(k), "inhalt": json.loads(d) if d else None} for k, d in zeilen]

    def _verstoss(self, pub: str) -> None:
        self.db.execute("INSERT INTO verstoss (pub, n) VALUES (?, 1) ON CONFLICT(pub) DO UPDATE SET n = n + 1", (pub,))

    def _objekt_inhalt(self, kopf: dict, inhalt):
        """Der zu speichernde Inhalt eines Objekts oder None (vergessen, fehlt, oder verstößt gegen die Regeln)."""
        grab = self.db.execute("SELECT token_sha FROM grab WHERE netz_id = ?", (kopf["netz_id"],)).fetchone()
        if grab and hmac.compare_digest(grab[0], kopf["loesch_hash"]):
            return None
        if inhalt is None:
            return None
        if sha256(inhalt) != kopf["sha"] or len(kanonisch(inhalt)) > MAX_INHALT or not isinstance(inhalt, dict) or inhalt.get("netz_id") != kopf["netz_id"] or inhalt.get("loesch_hash") != kopf["loesch_hash"]:
            self._verstoss(kopf["pub"])
            return None
        if pruefung.pruefe(inhalt, darf_reflex=True).urteil == "ablehnen":
            self._verstoss(kopf["pub"])
            return None
        return inhalt

    def aufnehmen(self, eintraege) -> dict:
        """Fremde Einträge prüfen und speichern. Ein Fehler beendet nur das Logbuch dieses Herausgebers für diesen Durchlauf."""
        bericht = {"neu": 0, "bekannt": 0, "abgelehnt": 0, "gruende": []}
        gestoppt: set[str] = set()

        def stop(pub, grund):
            bericht["abgelehnt"] += 1
            bericht["gruende"].append(f"{pseudonym(pub) if isinstance(pub, str) and _HEX64.match(pub) else '?'}: {grund}")
            gestoppt.add(pub)
        for e in eintraege if isinstance(eintraege, list) else []:
            kopf, inhalt = e.get("kopf") if isinstance(e, dict) else None, e.get("inhalt") if isinstance(e, dict) else None
            if grund := kopf_form(kopf):
                stop(kopf.get("pub") if isinstance(kopf, dict) else None, grund)
                continue
            pub = kopf["pub"]
            if pub in gestoppt:
                continue
            with self.sperre:
                if self.db.execute("SELECT 1 FROM gabelung WHERE pub = ?", (pub,)).fetchone():
                    stop(pub, "Gabelung bekannt")
                    continue
                if not self.ist_mitglied(pub):
                    stop(pub, "kein Mitglied")
                    continue
                if not signatur_stimmt(kopf):
                    stop(pub, "Signatur ungültig")
                    continue
                vorhanden = self.db.execute("SELECT hash FROM eintrag WHERE pub = ? AND seq = ?", (pub, kopf["seq"])).fetchone()
                if vorhanden:
                    if vorhanden[0] != eintrag_hash(kopf):
                        self.db.execute("INSERT OR REPLACE INTO gabelung (pub, seq, zeit) VALUES (?,?,?)", (pub, kopf["seq"], kopf["zeit"]))
                        stop(pub, f"Gabelung bei Nummer {kopf['seq']}")
                        continue
                    bericht["bekannt"] += 1
                    if kopf["typ"] == "objekt" and inhalt is not None and not self.db.execute("SELECT 1 FROM inhalt WHERE sha = ?", (kopf["sha"],)).fetchone():
                        if (gut := self._objekt_inhalt(kopf, inhalt)) is not None:
                            self.db.execute("INSERT OR IGNORE INTO inhalt (sha, daten) VALUES (?,?)", (kopf["sha"], json.dumps(gut, ensure_ascii=False, sort_keys=True)))
                    continue
                seq, vor = self._kopf_von(pub)
                if kopf["seq"] != seq + 1 or kopf["vor"] != vor:
                    stop(pub, f"Kette unterbrochen bei Nummer {kopf['seq']}")
                    continue
                if self.db.execute("SELECT COUNT(*) FROM eintrag WHERE pub = ? AND zeit = ?", (pub, kopf["zeit"])).fetchone()[0] >= MAX_JE_TAG:
                    stop(pub, "Tageskontingent erschöpft")
                    continue
                if kopf["typ"] == "objekt":
                    speichern = self._objekt_inhalt(kopf, inhalt)
                else:
                    if not steuer_form(kopf["typ"], inhalt) or sha256(inhalt) != kopf["sha"] or (kopf["typ"] == "widerruf" and inhalt["ziel"] != kopf["netz_id"]):
                        self._verstoss(pub)
                        stop(pub, f"Inhalt von Typ {kopf['typ']} unbrauchbar")
                        continue
                    speichern = inhalt
                self._einfuegen(kopf, speichern)
                bericht["neu"] += 1
                if speichern is not None:
                    self._folgen(kopf, speichern)
        bericht["gruende"] = bericht["gruende"][:20]
        return bericht

    # ---- Weitergabe ans Gedächtnis ----

    def neu_seit_stand(self, pub: str, anzahl: int = 200) -> list[dict]:
        with self.sperre:
            z = self.db.execute("SELECT seq FROM stand WHERE pub = ?", (pub,)).fetchone()
        return self.lies(pub, z[0] if z else 0, anzahl)

    def stand_setzen(self, pub: str, seq: int) -> None:
        with self.sperre:
            self.db.execute("INSERT INTO stand (pub, seq) VALUES (?,?) ON CONFLICT(pub) DO UPDATE SET seq = excluded.seq", (pub, seq))

    def eigene_objekte(self) -> set[tuple[str, str]]:
        with self.sperre:
            return set(self.db.execute("SELECT netz_id, sha FROM eintrag WHERE pub = ? AND typ = 'objekt'", (self.pub,)).fetchall())

    def eigene_widerrufe(self) -> set[str]:
        with self.sperre:
            return {r[0] for r in self.db.execute("SELECT netz_id FROM eintrag WHERE pub = ? AND typ = 'widerruf'", (self.pub,))}

    def letzte_eigene_adresse(self) -> dict | None:
        with self.sperre:
            z = self.db.execute("SELECT i.daten FROM eintrag e JOIN inhalt i ON i.sha = e.sha WHERE e.pub = ? AND e.typ = 'adresse' ORDER BY e.seq DESC LIMIT 1", (self.pub,)).fetchone()
        return json.loads(z[0]) if z else None

    # ---- Peers ----

    def peer_merken(self, adresse: str, quelle: str, pin: str | None = None) -> None:
        """Ein Pin kommt nur aus einer signierten Quelle: dem adresse-Eintrag des Peers selbst oder einem Beitrittscode."""
        with self.sperre:
            self.db.execute("INSERT OR IGNORE INTO peer (adresse, quelle) VALUES (?,?)", (adresse.rstrip("/"), quelle))
            if pin:
                self.db.execute("UPDATE peer SET pin = ? WHERE adresse = ?", (pin, adresse.rstrip("/")))

    def pin(self, adresse: str) -> str | None:
        with self.sperre:
            z = self.db.execute("SELECT pin FROM peer WHERE adresse = ?", (adresse.rstrip("/"),)).fetchone()
        return z[0] if z else None

    def peers(self) -> list[dict]:
        with self.sperre:
            zeilen = self.db.execute("SELECT adresse, quelle, pin, zuletzt, fehler, naechster FROM peer ORDER BY adresse").fetchall()
        return [{"adresse": a, "quelle": q, "pin": p, "zuletzt": z, "fehler": f, "naechster": n} for a, q, p, z, f, n in zeilen]

    # ---- Beitritt mit Code: einmalig, befristet, nur der Hash liegt hier ----

    def beitritt_anlegen(self, nonce: str, gueltig_s: float) -> None:
        with self.sperre:
            self.db.execute("INSERT INTO beitritt (nonce_sha, ablauf) VALUES (?,?)", (hashlib.sha256(nonce.encode()).hexdigest(), time.time() + gueltig_s))

    def beitritt_einloesen(self, nonce: str, pub: str) -> str | None:
        """Grund der Ablehnung oder None. Bei Erfolg lädt dieser Server den neuen Schlüssel ein."""
        if not isinstance(nonce, str) or len(nonce) > 200:
            return "Code unbrauchbar"
        with self.sperre:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                z = self.db.execute("SELECT ablauf, benutzt FROM beitritt WHERE nonce_sha = ?", (hashlib.sha256(nonce.encode()).hexdigest(),)).fetchone()
                if not z or z[1] or z[0] < time.time():
                    self.db.execute("ROLLBACK")
                    return "Beitrittscode ungültig, abgelaufen oder schon benutzt"
                self.db.execute("UPDATE beitritt SET benutzt = ? WHERE nonce_sha = ?", (pub, hashlib.sha256(nonce.encode()).hexdigest()))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        if not self.ist_mitglied(pub):
            self.anhaengen("einladung", {"pub": pub})
        return None

    def peers_waehlen(self, n: int, ausser: str | None = None) -> list[str]:
        with self.sperre:
            alle = [r[0] for r in self.db.execute("SELECT adresse FROM peer WHERE naechster <= ?", (time.time(),)) if r[0] != ausser]
        random.shuffle(alle)
        return alle[:n]

    def peer_ergebnis(self, adresse: str, ok: bool) -> None:
        with self.sperre:
            if ok:
                self.db.execute("UPDATE peer SET zuletzt = ?, fehler = 0, naechster = 0 WHERE adresse = ?", (time.time(), adresse))
            else:
                self.db.execute("UPDATE peer SET fehler = fehler + 1, naechster = ? + min(3600, 30 * (1 << min(fehler, 7))) WHERE adresse = ?", (time.time(), adresse))

    # ---- Segmente: Transport-Zwischenablage für Torrent, ohne eigene Beweiskraft ----

    def segment_merken(self, sha: str, pub: str, von: int, bis: int, torrent: bytes, port: int, datei: str) -> None:
        with self.sperre:
            self.db.execute("INSERT OR REPLACE INTO segment (sha256, pub, von, bis, torrent, port, datei) VALUES (?,?,?,?,?,?,?)", (sha, pub, von, bis, base64.b64encode(torrent).decode(), port, datei))

    def segmente(self, pub: str) -> list[dict]:
        with self.sperre:
            z = self.db.execute("SELECT sha256, von, bis, torrent, port FROM segment WHERE pub = ? ORDER BY von", (pub,)).fetchall()
        return [{"sha256": a, "von": b, "bis": c, "torrent": d, "port": e} for a, b, c, d, e in z]

    def segmente_lokal(self) -> list[tuple[str, str, str]]:
        with self.sperre:
            return self.db.execute("SELECT sha256, torrent, datei FROM segment").fetchall()

    def letztes_segment_bis(self, pub: str) -> int:
        with self.sperre:
            return self.db.execute("SELECT COALESCE(MAX(bis), 0) FROM segment WHERE pub = ?", (pub,)).fetchone()[0]

    def segmente_verwerfen(self, pub: str, seq: int) -> None:
        """Ein Segment mit vergessenem Inhalt darf nicht weiter verteilt werden. Die Datei fällt beim nächsten Abgleich der Schwarm-Liste weg."""
        with self.sperre:
            for (d,) in self.db.execute("SELECT datei FROM segment WHERE pub = ? AND von <= ? AND bis >= ?", (pub, seq, seq)).fetchall():
                try:
                    Path(d).unlink(missing_ok=True)
                except OSError:
                    pass
            self.db.execute("DELETE FROM segment WHERE pub = ? AND von <= ? AND bis >= ?", (pub, seq, seq))

    def status(self) -> dict:
        with self.sperre:
            d = {"eintraege": self.db.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0], "inhalte": self.db.execute("SELECT COUNT(*) FROM inhalt").fetchone()[0],
                 "grabsteine": self.db.execute("SELECT COUNT(*) FROM grab").fetchone()[0], "gabelungen": self.db.execute("SELECT COUNT(*) FROM gabelung").fetchone()[0],
                 "verstoesse": self.db.execute("SELECT COALESCE(SUM(n), 0) FROM verstoss").fetchone()[0], "segmente": self.db.execute("SELECT COUNT(*) FROM segment").fetchone()[0],
                 "peers": self.db.execute("SELECT COUNT(*) FROM peer").fetchone()[0], "peers_erreichbar": self.db.execute("SELECT COUNT(*) FROM peer WHERE fehler = 0 AND zuletzt IS NOT NULL").fetchone()[0]}
        return {**d, "mitglieder": len(self.mitglieder())}

    def schliessen(self) -> None:
        with self.sperre:
            self.db.close()
