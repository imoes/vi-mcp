"""Das Gedächtnis: jeder Eintrag ist ein Objekt (Tabelle objekt → Klasse Objekt, Mapping ohne ORM).

Feste Felder (id, art, zeit); änderbare Felder nur über Methoden (markiere, bestaetige, widerlege, verknuepfe),
jede Änderung mit Grund und Geschichte. Jedes Objekt trägt Hashtags art:wert; erinnern = Filtersprache
`art:wert`, `!art:wert`, `(a OR b)`, Präfix `art:wert*`, Freitext (FTS5).

Abruf gewichtet nach Relevanz + Aktualität (exponentieller Verfall) + Wichtigkeit — nach Park et al. 2023
„Generative Agents“ (arXiv 2304.03442). Objekte mit gemeinsamen Hashtags werden verknüpft (Zettelkasten, A-Mem).

Ein Prozess, eine Verbindung: alle Zugriffe laufen unter `sperre` (threading.RLock). Weil vi-mcp der einzige
Schreiber ist, reicht diese Sperre — mehrere Prozesse auf derselben Datei sind nicht vorgesehen (siehe
docs/ARCHITEKTUR.md, „Ein Prozess“).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import anonymize
from .log_output import log

KINDS = ("erfahrung", "antwort", "erkenntnis", "regel", "reflex", "gespraech", "suche", "frage", "selbst", "schlaf", "modell", "skill", "bewertung")
#: strittig = von genau einer fremden Instanz widerlegt (erscheint weiter, mit Vermerk); widerlegt = vom Urheber
#: oder von ≥ 2 verschiedenen Instanzen widerlegt (erscheint nicht mehr)
#: archiviert = Stummel (Text, Hashtags) bleibt, Inhalt komprimiert in Tabelle archiv; nur mit modus:archiviert im Filter sichtbar
#: aufgegangen = Skill ist in einem anderen aufgegangen (Fusion); bleibt mit Verweis, erscheint nicht mehr in Suchen
#: quarantaene = importiert und noch nicht freigegeben; erscheint in keiner Suche und keinem Hinweis
MODES = ("aktiv", "test", "aus", "defekt", "strittig", "widerlegt", "archiviert", "aufgegangen", "quarantaene")
#: Kollektiv: wer darf ein Objekt lesen? privat = nur die Urheber-Instanz (Ergebnisse können Zugangsdaten enthalten),
#: geteilt = alle Instanzen. Der Loop (Server) sieht alles. Erschöpfend für ARTEN.
VISIBILITY_PER_KIND = {"erfahrung": "privat", "antwort": "privat", "erkenntnis": "geteilt", "regel": "geteilt", "reflex": "geteilt",
                "gespraech": "geteilt", "suche": "geteilt", "frage": "geteilt", "selbst": "geteilt", "schlaf": "geteilt", "modell": "geteilt", "skill": "geteilt", "bewertung": "privat"}
#: Urheber für Objekte, die der Server selbst anlegt (Loop) — eine benannte Instanz, kein NULL
SERVER_INSTANCE = "vi"
#: Gewichtbonus je verschiedener FREMDER Instanz, die bestätigt hat (Selbstbestätigung zählt nicht als Beleg)
BONUS_PER_INSTANCE = 0.2
BONUS_MAX = 0.6
#: Änderungsgeschichte je Objekt; ältere Einträge werden gezählt gekürzt (daten.aenderungen_gekuerzt)
HISTORY_MAX = 50
DATA_MAX = 400_000
#: Aktualität nach **Potenzgesetz** (Wixted & Ebbesen 1991; ACT-R: Anderson & Schooler 1991 — docs/FORSCHUNG.md A9):
#: aktualitaet = (1 + h)^(−VERFALL_D), h = Stunden seit dem letzten Zugriff. Schnell am Anfang, langsam danach:
#: 1 h 0,81 · 1 d 0,38 · 7 d 0,21 · 30 d 0,14 · 1 a 0,07. Bis 0.3.0 exponentiell 0,995^h (Park et al., dort je
#: Spielstunde) — das ließ Älteres als 2 Wochen praktisch verschwinden (30 d: 0,03). VERFALL_D = 0,3 ist ein Startwert.
DECAY_D = 0.3
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,30}:[^\s()]+$")
#: Hashtags, die Verwaltung sind und nicht Inhalt (für Verknüpfung und Trichter ignoriert)
ADMIN_PREFIXES = ("art:", "cache:", "ok:", "serial:", "tag:", "instanz:", "zustand:", "an:", "von:", "ueberraschung:",
              "modus:", "herkunft:", "konflikt:", "selbst:", "selbstbereich:", "modell:", "fusion:", "dublette:", "scorer:", "ziel:", "note:")

lock = threading.RLock()
CONTENT_MAX = 200_000
_db: sqlite3.Connection | None = None
fts = False
#: aktive Datenbank und Langzeitlager (lager.py) — gesetzt von oeffne()
fpath_active: Path | None = None
archive_path: Path | None = None

#: Das Gespräch (Seriennummer), in dessen Auftrag gerade gearbeitet wird — je Anfrage-Thread gesetzt
current_conversation: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelles_gespraech", default=None)
#: Die Instanz, in deren Auftrag gerade gelesen/geschrieben wird. None = der Server selbst (Loop): sieht alles.
current_instance: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelle_instanz", default=None)


def now() -> str:
    """ISO-8601 UTC mit Millisekunden: Vergleiche `zeit > seit` (Schlaf, Loop) trennen sonst nicht, was in derselben
    Sekunde entstand. Ältere Einträge (Sekunden, 0.1–0.3) sortieren als Text korrekt davor ('+' < '.')."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def hash_value(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def db() -> sqlite3.Connection:
    if _db is None:
        raise RuntimeError("Gedächtnis nicht geöffnet (oeffne() fehlt)")
    return _db


def open_db(fpath: Path) -> None:
    """Datenbank öffnen bzw. anlegen. Datei und Begleitdateien nur für den Eigentümer lesbar (0600):
    das Gedächtnis enthält Gesprächsverläufe und Werkzeugergebnisse, darin können Zugangsdaten stehen."""
    global _db, fts, fpath_active, archive_path
    fpath.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        con = sqlite3.connect(str(fpath), check_same_thread=False, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
    finally:
        os.umask(old_umask)
    for f in (fpath, Path(f"{fpath}-wal"), Path(f"{fpath}-shm")):
        if f.exists():
            os.chmod(f, 0o600)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS objekt (
            id TEXT PRIMARY KEY, art TEXT NOT NULL, zeit TEXT NOT NULL, zuletzt TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '', daten TEXT NOT NULL DEFAULT '{}', wichtigkeit INTEGER NOT NULL DEFAULT 1,
            bestaetigt INTEGER NOT NULL DEFAULT 0, widerlegt INTEGER NOT NULL DEFAULT 0, zugriffe INTEGER NOT NULL DEFAULT 0,
            modus TEXT NOT NULL DEFAULT 'aktiv', aenderungen TEXT NOT NULL DEFAULT '[]', gespraech TEXT,
            instanz TEXT NOT NULL DEFAULT 'vi', sicht TEXT NOT NULL DEFAULT 'geteilt');
        CREATE INDEX IF NOT EXISTS objekt_art_zeit ON objekt(art, zeit);
        CREATE TABLE IF NOT EXISTS tag (objekt_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (objekt_id, tag));
        CREATE INDEX IF NOT EXISTS tag_tag ON tag(tag);
        CREATE TABLE IF NOT EXISTS kante (a TEXT NOT NULL, b TEXT NOT NULL, grund TEXT NOT NULL, zeit TEXT NOT NULL,
            PRIMARY KEY (a, b));
        CREATE TABLE IF NOT EXISTS gespraech_roh (serial TEXT PRIMARY KEY, roh BLOB NOT NULL, laenge INTEGER NOT NULL);
    """)
    _migrate(con)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS objekt_fts USING fts5(id UNINDEXED, text)")
        fts = True
    except sqlite3.OperationalError as exc:
        fts = False
        log(f"FTS5 nicht verfügbar ({exc}) — Volltext über LIKE")
    con.commit()
    with lock:
        if _db is not None:
            _db.close()
        _db = con
        fpath_active, archive_path = fpath, fpath.with_name(f"{fpath.stem}-lager.db")


def _migrate(con: sqlite3.Connection) -> None:
    """0.1.x → 0.2.0: Spalten instanz/sicht nachrüsten (Urheber aus dem Hashtag instanz:, Sicht aus der Art);
    Cache-Hashtag frage:<hash> → cache:<hash> (frage ist jetzt eine Art)."""
    columns = {r[1] for r in con.execute("PRAGMA table_info(objekt)")}
    if "instanz" not in columns:
        con.execute("ALTER TABLE objekt ADD COLUMN instanz TEXT NOT NULL DEFAULT 'vi'")
        con.execute("UPDATE objekt SET instanz = COALESCE((SELECT substr(tag, 9) FROM tag WHERE objekt_id = objekt.id "
                    "AND tag LIKE 'instanz:%' LIMIT 1), 'vi')")
        log("Migration: Spalte instanz nachgerüstet")
    if "sicht" not in columns:
        con.execute("ALTER TABLE objekt ADD COLUMN sicht TEXT NOT NULL DEFAULT 'geteilt'")
        for kind, visibility in VISIBILITY_PER_KIND.items():
            con.execute("UPDATE objekt SET sicht = ? WHERE art = ?", (visibility, kind))
        log("Migration: Spalte sicht nachgerüstet")
    n = con.execute("UPDATE tag SET tag = 'cache:' || substr(tag, 7) WHERE tag LIKE 'frage:%'").rowcount
    if n:
        log(f"Migration: {n} Cache-Hashtags frage: → cache:")
    con.execute("CREATE INDEX IF NOT EXISTS objekt_instanz ON objekt(instanz, sicht)")
    # Die Tabelle archiv (0.4–0.9) ist durch das Langzeitlager ersetzt; sie wird nur entfernt, wenn sie leer ist
    if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'archiv'").fetchone():
        if con.execute("SELECT COUNT(*) FROM archiv").fetchone()[0] == 0:
            con.execute("DROP TABLE archiv")
        else:
            log("Tabelle archiv enthält Einträge und bleibt bestehen — bitte prüfen")
    # Flache Sicht auf Beobachtungen (docs/TRAINING.md 4a): eine Quelle der Wahrheit (objekt/tag/daten), nur anders gelesen
    con.execute("DROP VIEW IF EXISTS beobachtung")
    con.execute("""CREATE VIEW beobachtung AS
        SELECT o.id AS erfahrung_id, o.zeit, o.instanz,
               (SELECT substr(tag, 6) FROM tag WHERE objekt_id = o.id AND tag LIKE 'tool:%') AS tool,
               CASE WHEN EXISTS (SELECT 1 FROM tag WHERE objekt_id = o.id AND tag = 'ok:ja') THEN 1
                    WHEN EXISTS (SELECT 1 FROM tag WHERE objekt_id = o.id AND tag = 'ok:nein') THEN 0 END AS ok,
               json_array_length(COALESCE(json_extract(o.daten, '$.vorher.gezeigt'), json_extract(o.daten, '$.vorher.gefunden'), '[]')) AS hinweise_n,
               json_extract(o.daten, '$.ueberraschung.stufe') AS ueberraschung,
               json_extract(o.daten, '$.vorher.router') AS router,
               json_extract(o.daten, '$.vorher.exploration') AS exploration,
               json_extract(o.daten, '$.vorher.reize') AS reize_json,
               json_extract(o.daten, '$.vorher.gezeigt') AS gezeigt_json,
               json_extract(o.daten, '$.vorher.kandidaten') AS kandidaten_json,
               json_extract(o.daten, '$.vorher.aus_gedaechtnis') AS aus_gedaechtnis
        FROM objekt o WHERE o.art = 'erfahrung'""")
    con.commit()


#: Sichten: privat (nur die Urheber-Instanz), geteilt (alle, auch ohne Token im Open-Wiki-Modus, und das Netz),
#: intern (seit 0.20.0: alle Instanzen mit Token, nie die tokenlose Instanz und nie das Netz — für Firmenwissen wie Confluence).
VISIBILITIES = ("privat", "geteilt", "intern")
#: Name der tokenlosen Instanz im Open-Wiki-Modus (= konfig.OFFEN; hier wiederholt, weil konfig dieses Modul nicht kennt).
OPEN_INSTANCE = "offen"


def visible_to(o: "Objekt", instance: str | None) -> bool:
    """Darf diese Instanz das Objekt lesen? None = der Server selbst."""
    return (instance is None or o.visibility == "geteilt" or o.instance == instance
            or (o.visibility == "intern" and instance != OPEN_INSTANCE))


def close_db() -> None:
    global _db
    from . import archive
    archive.close_db()
    with lock:
        if _db is not None:
            _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _db.close()
            _db = None


@dataclass
class MemoryObject:
    """Ein Eintrag des Gedächtnisses. Feste Felder: id, art, zeit. Änderbar nur über Methoden (mit Geschichte)."""
    id: str
    kind: str
    ts: str
    last_at: str
    text: str = ""
    data: dict = field(default_factory=dict)
    hashtags: list = field(default_factory=list)
    importance: int = 1
    confirmed: int = 0
    refuted: int = 0
    accesses: int = 0
    mode: str = "aktiv"
    changes: list = field(default_factory=list)
    conversation: str | None = None
    instance: str = SERVER_INSTANCE
    visibility: str = "geteilt"

    @staticmethod
    def _require_reason(reason: str) -> None:
        if not (reason or "").strip():
            raise ValueError("Grund ist Pflicht — jede Änderung braucht einen zureichenden Grund")

    def change(self, who: str, what: str, reason: str) -> None:
        self._require_reason(reason)
        all_ = self.changes + [{"zeit": now(), "wer": who, "was": what, "grund": reason.strip()[:300]}]
        if len(all_) > HISTORY_MAX:  # nichts verschwindet still: die Kürzung wird gezählt und in vi_object genannt
            self.data["aenderungen_gekuerzt"] = self.data.get("aenderungen_gekuerzt", 0) + len(all_) - HISTORY_MAX
            all_ = all_[-HISTORY_MAX:]
        self.changes = all_
        self.last_at = now()

    def tag(self, add: list[str], remove: list[str], who: str, reason: str) -> "Objekt":
        self._require_reason(reason)
        for t in list(add) + list(remove):
            if not TAG.match(t):
                raise ValueError(f"Hashtag {t!r} hat nicht die Form art:wert")
            if t.startswith(("art:", "tool:", "instanz:", "herkunft:", "herausgeber:", "pruefer:", "modus:")):
                raise ValueError(f"{t}: fester Hashtag (instanz: ist der Urheber aus dem Token; art:, tool:, herkunft:, herausgeber:, pruefer: und modus: setzt das System)")
        self.hashtags = sorted((set(self.hashtags) | set(add)) - set(remove))
        self.change(who, " ".join([f"+{t}" for t in add] + [f"-{t}" for t in remove]), reason)
        return save(self)

    def confirm(self, who: str, reason: str, instance: str | None = None) -> "Objekt":
        """Bestätigen. Zählt je Instanz (daten.bestaetigt_von); Gewichtbonus nur für FREMDE Instanzen."""
        self._require_reason(reason)  # erst prüfen, dann ändern — eine Ablehnung lässt das Objekt unverändert
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("bestaetigt_von") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["bestaetigt_von"] = from_
        self.confirmed += 1
        if self.mode == "strittig" and i != self.instance:
            self.mode = "aktiv"  # eine fremde Bestätigung hebt den Streit auf — mit Geschichte
        self.change(who, "bestätigt" + (" (Selbstbestätigung, kein Gewichtbonus)" if i == self.instance else ""), reason)
        return save(self)

    def refute(self, who: str, reason: str, instance: str | None = None) -> "Objekt":
        """Widerlegen. Urheber selbst oder ≥ 2 verschiedene Instanzen → widerlegt (verschwindet aus Suchen);
        genau eine fremde Instanz → strittig (bleibt sichtbar, mit Vermerk) — eine Instanz allein löscht nicht
        das Wissen einer anderen."""
        self._require_reason(reason)
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("widerlegt_von") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["widerlegt_von"] = from_
        self.refuted += 1
        self.mode = "widerlegt" if (i == self.instance or len(from_) >= 2) else "strittig"
        self.change(who, self.mode, reason)
        return save(self)

    def foreign_confirmations(self) -> int:
        """Verschiedene fremde Instanzen, die bestätigt haben. Der Server (`vi`, Schlaf) zählt nicht als fremd —
        eine automatische Bestätigung soll das Gewicht nicht heben (keine Selbstbestätigung des Systems)."""
        return len([i for i in (self.data.get("bestaetigt_von") or {}) if i not in (self.instance, SERVER_INSTANCE)])

    def link(self, other_id: str, reason: str) -> None:
        with lock:
            for a, b in ((self.id, other_id), (other_id, self.id)):
                # Ein Beleg wiegt mehr als eine automatische Kante und ersetzt sie; umgekehrt nie
                db().execute("INSERT INTO kante (a, b, grund, zeit) VALUES (?,?,?,?) ON CONFLICT (a, b) DO UPDATE SET grund = excluded.grund, "
                             "zeit = excluded.zeit WHERE excluded.grund LIKE 'Beleg%' AND kante.grund NOT LIKE 'Beleg%'", (a, b, reason[:200], now()))
            db().commit()

    def access(self) -> None:
        """Erinnert heißt verstärkt: Zugriff zählt, zuletzt rückt vor (Konsolidierung). Relativ hochgezählt —
        kein verlorener Zähler, auch wenn ein anderer Thread dasselbe Objekt gleichzeitig liest."""
        self.last_at = now()
        with lock:
            db().execute("UPDATE objekt SET zugriffe = zugriffe + 1, zuletzt = ? WHERE id = ?", (self.last_at, self.id))
            db().commit()
            self.accesses = db().execute("SELECT zugriffe FROM objekt WHERE id = ?", (self.id,)).fetchone()[0]

    def edges(self) -> list[tuple[str, str]]:
        with lock:
            return db().execute("SELECT b, grund FROM kante WHERE a = ?", (self.id,)).fetchall()


#: Database columns of table objekt (stored format, stays German) and the MemoryObject field each one fills, in the same order
COLUMNS = ("id", "art", "zeit", "zuletzt", "text", "daten", "wichtigkeit", "bestaetigt", "widerlegt", "zugriffe",
           "modus", "aenderungen", "gespraech", "instanz", "sicht")
FIELDS = ("id", "kind", "ts", "last_at", "text", "data", "importance", "confirmed", "refuted", "accesses",
          "mode", "changes", "conversation", "instance", "visibility")


def _fields_from_row(row) -> dict:
    d = dict(zip(FIELDS, row))
    d["data"] = json.loads(d["data"] or "{}")
    d["changes"] = json.loads(d["changes"] or "[]")
    return d


def _object_from_row(row) -> MemoryObject:
    o = MemoryObject(**_fields_from_row(row))
    with lock:
        o.hashtags = [r[0] for r in db().execute("SELECT tag FROM tag WHERE objekt_id = ? ORDER BY tag", (o.id,))]
    return o


def load(oid: str) -> MemoryObject | None:
    with lock:
        row = db().execute(f"SELECT {', '.join(COLUMNS)} FROM objekt WHERE id = ?", (oid,)).fetchone()
        return _object_from_row(row) if row else None


def _data_json(o: MemoryObject) -> str:
    """Zu große Daten werden benannt ersetzt. Ein Abschneiden des JSON-Textes machte das Objekt unlesbar."""
    js = json.dumps(o.data, ensure_ascii=False)
    if len(js) <= DATA_MAX:
        return js
    log(f"{o.id}: daten mit {len(js)} Zeichen über Grenze {DATA_MAX} — ersetzt")
    return json.dumps({"gekuerzt_zeichen": len(js), "grund": f"daten über {DATA_MAX} Zeichen"})


def load_many(oids: list[str]) -> dict[str, MemoryObject]:
    """Mehrere Objekte in zwei Abfragen statt in zwei je Objekt."""
    outputs: dict[str, MemoryObject] = {}
    with lock:
        for i in range(0, len(oids), 900):
            part = oids[i:i + 900]
            markers = ",".join("?" * len(part))
            tags: dict[str, list[str]] = {}
            for oid, tag in db().execute(f"SELECT objekt_id, tag FROM tag WHERE objekt_id IN ({markers}) ORDER BY tag", part):
                tags.setdefault(oid, []).append(tag)
            for row in db().execute(f"SELECT {', '.join(COLUMNS)} FROM objekt WHERE id IN ({markers})", part):
                d = _fields_from_row(row)
                outputs[d["id"]] = MemoryObject(**d, hashtags=tags.get(d["id"], []))
    return outputs


def save(o: MemoryObject) -> MemoryObject:
    tags = sorted(set(o.hashtags) | {f"art:{o.kind}", f"instanz:{o.instance}"})
    with lock:
        db().execute(f"INSERT OR REPLACE INTO objekt ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                     (o.id, o.kind, o.ts, o.last_at, o.text, _data_json(o), o.importance,
                      o.confirmed, o.refuted, o.accesses, o.mode, json.dumps(o.changes, ensure_ascii=False), o.conversation,
                      o.instance, o.visibility))
        db().execute("DELETE FROM tag WHERE objekt_id = ?", (o.id,))
        db().executemany("INSERT OR IGNORE INTO tag (objekt_id, tag) VALUES (?, ?)", [(o.id, t) for t in tags])
        if fts:
            db().execute("DELETE FROM objekt_fts WHERE id = ?", (o.id,))
            db().execute("INSERT INTO objekt_fts (id, text) VALUES (?, ?)", (o.id, (o.text + "\n" + str(o.data.get("inhalt") or ""))[:300000]))
        db().commit()
    o.hashtags = tags
    return o


def delete(oids: list[str]) -> int:
    """Objekte samt Hashtags, Volltext, Kanten und Lagerinhalt entfernen — keine hängenden Kanten, keine Reste im Lager."""
    from . import archive
    archive.delete(oids)
    with lock:
        for a in oids:
            db().execute("DELETE FROM objekt WHERE id = ?", (a,))
            db().execute("DELETE FROM tag WHERE objekt_id = ?", (a,))
            db().execute("DELETE FROM kante WHERE a = ? OR b = ?", (a, a))
            if fts:
                db().execute("DELETE FROM objekt_fts WHERE id = ?", (a,))
        db().commit()
    return len(oids)


def new_object(kind: str, text: str, hashtags: list[str], data: dict | None = None, importance: int = 1,
                 who: str = "vi", reason: str = "", oid: str | None = None, mode: str = "aktiv",
                 conversation: str | None = None, instance: str | None = None, visibility: str | None = None) -> MemoryObject:
    if kind not in KINDS:
        raise ValueError(f"art muss {', '.join(KINDS)} sein")
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValueError(f"sicht muss eine von {', '.join(VISIBILITIES)} sein")
    for t in hashtags:
        if not TAG.match(t):
            raise ValueError(f"Hashtag {t!r} hat nicht die Form art:wert")
    # instanz: ist kein freier Hashtag, sondern der Urheber (Spalte instanz) — ein Ding, ein Ort
    hashtags = [t for t in hashtags if not t.startswith("instanz:")]
    text, data = anonymize.without_secrets(text), anonymize.without_secrets(data)  # Zugangsdaten werden nie gespeichert
    ts = now()
    # Zufallsanteil: zwei gleiche Handlungen in derselben Sekunde sind zwei Objekte, nicht eines (sonst überschreibt
    # INSERT OR REPLACE das erste still — gefunden von test_eingebaute_werkzeuge_nie_aus_gedaechtnis)
    o = MemoryObject(id=oid or f"{kind}:{hash_value(kind, text, ts, json.dumps(data or {}, sort_keys=True), secrets.token_hex(8))}", kind=kind, ts=ts,
               last_at=ts, text=text, data=data or {}, hashtags=list(hashtags), importance=max(0, min(3, importance)),
               mode=mode, conversation=conversation or current_conversation.get(),
               instance=instance or current_instance.get() or SERVER_INSTANCE, visibility=visibility or VISIBILITY_PER_KIND[kind],
               changes=[{"zeit": ts, "wer": who, "was": "angelegt", "grund": (reason or "angelegt")[:300]}])
    save(o)
    if mode != "quarantaene":  # Ungeprüftes bekommt keine Verbindung zum eigenen Wissen
        link_similar(o)
    return o


def link_similar(o: MemoryObject, at_least: int = 2, limit: int = 5) -> None:
    """Zettelkasten: Objekte, die ≥ `mindestens` inhaltliche Hashtags teilen, werden verbunden (A-Mem-Idee)."""
    content = [t for t in o.hashtags if not t.startswith(ADMIN_PREFIXES)]  # sonst verbände instanz:/art: alles mit allem
    if len(content) < at_least or o.kind in ("antwort",):
        return
    with lock:
        rows = db().execute(
            f"SELECT objekt_id, COUNT(*) n FROM tag WHERE tag IN ({','.join('?' * len(content))}) AND objekt_id <> ? "
            f"GROUP BY objekt_id HAVING n >= ? ORDER BY n DESC LIMIT ?", (*content, o.id, at_least, limit)).fetchall()
    for oid, n in rows:
        o.link(oid, f"{n} gemeinsame Hashtags")


# ── Erinnern: Filtersprache + Gewichtung ─────────────────────────────────────

def parse_filter(text: str) -> tuple[list[list[str]], list[str], list[str]]:
    """Filtertext → (UND-Gruppen aus ODER-Tags, Ausschluss-Tags, Freiwörter). `(a OR b) c !d wort`. Rein."""
    groups, remove, words = [], [], []
    for m in re.finditer(r"\(([^()]*)\)|(!?\S+)", text or ""):
        if m.group(1) is not None:
            old = [t for t in re.split(r"\s+OR\s+|\s+", m.group(1).strip()) if t and t != "OR"]
            if old:
                groups.append(old)
            continue
        tok = m.group(2)
        if tok.upper() == "OR":
            continue
        if tok.startswith("!"):
            remove.append(tok[1:])
        elif ":" in tok:
            groups.append([tok])
        else:
            words.append(tok)
    return groups, remove, words


def _tag_condition(tag: str) -> tuple[str, tuple]:
    return ("tag LIKE ?", (tag[:-1] + "%",)) if tag.endswith("*") else ("tag = ?", (tag,))


def _filter_sql(groups: list, remove: list, viewer: str | None) -> tuple[str, list]:
    """SQL für Modus, Sicht und Hashtag-Bedingungen (ohne Freitext) — eine Quelle für erinnere() und ids_zum_filter()."""
    sql, par = "SELECT id FROM objekt WHERE modus <> 'widerlegt'", []
    if not any("modus:quarantaene" in grp for grp in groups):
        sql += " AND modus <> 'quarantaene'"  # nur über vi_quarantine
    if not any("modus:aufgegangen" in grp for grp in groups):
        sql += " AND modus <> 'aufgegangen'"  # Aufgegangenes nur auf Nachfrage (Verweis steht im Objekt)
    if not any("modus:archiviert" in grp for grp in groups):
        sql += " AND modus <> 'archiviert'"  # Archiviertes nur auf ausdrückliche Nachfrage
    if viewer is not None:
        sql += " AND (sicht = 'geteilt' OR instanz = ?" + (" OR sicht = 'intern')" if viewer != OPEN_INSTANCE else ")")
        par.append(viewer)
    for g in groups:
        parts = [_tag_condition(t) for t in g]
        sql += " AND id IN (SELECT objekt_id FROM tag WHERE " + " OR ".join(b for b, _ in parts) + ")"
        for _, p in parts:
            par += list(p)
    for t in remove:
        b, p = _tag_condition(t)
        sql += f" AND id NOT IN (SELECT objekt_id FROM tag WHERE {b})"
        par += list(p)
    return sql, par


def ids_for_filter(filter_text: str, kinds: tuple[str, ...] = (), viewer: str | None = "aktuell") -> list[str]:
    """Alle sichtbaren IDs zu den Hashtag-Bedingungen des Filters, ohne Obergrenze (Kandidaten der semantischen Suche)."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    groups, remove, _w = parse_filter(filter_text)
    if kinds:
        groups.append([f"art:{a}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer)
    with lock:
        return [r[0] for r in db().execute(sql, par)]


#: Wie die letzte Wortsuche in diesem Kontext lief: "und" (alle Wörter), "oder" (Ersatz, weil zu wenig alle Wörter enthielten) oder None.
word_search: contextvars.ContextVar[str | None] = contextvars.ContextVar("wortsuche", default=None)


def recall(filter_text: str, limit: int = 10, kinds: tuple[str, ...] = (), viewer: str | None = "aktuell",
             or_fallback: bool = False) -> list[tuple[float, MemoryObject, dict]]:
    """Objekte zum Filter, gewichtet: Relevanz (Tag-/Worttreffer) + Aktualität + Wichtigkeit (Park et al. 2023)
    + Bonus je fremder bestätigender Instanz. Sichtbar ist, was geteilt ist oder dem Betrachter gehört
    (betrachter "aktuell" = Instanz der laufenden Anfrage; None = Server, sieht alles).
    Freitext verlangt alle Wörter (UND). oder_ersatz=True: enthalten weniger als `limit` Objekte alle Wörter, wird mit
    einer ODER-Suche aufgefüllt (BM25 ordnet Objekte mit mehr Wörtern nach vorn); `wortsuche` sagt danach, welche lief."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    groups, remove, words = parse_filter(filter_text)
    if kinds:
        groups.append([f"art:{a}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer)
    word_hits: dict[str, float] = {}
    search_kind = None
    with lock:
        if words:
            if fts:
                terms = ['"' + w.replace('"', '') + '"' for w in words]
                search_kind = "und"

                def _fts(q: str) -> dict[str, float]:
                    return {oid: -float(rank) for oid, rank in db().execute(
                        f"SELECT id, rank FROM objekt_fts WHERE objekt_fts MATCH ? AND id IN ({sql}) ORDER BY rank LIMIT 500", (q, *par))}
                word_hits = _fts(" ".join(terms))
                if or_fallback and len(terms) > 1 and len(word_hits) < limit:
                    or_hits = _fts(" OR ".join(terms))
                    if len(or_hits) > len(word_hits):
                        # Objekte mit allen Wörtern bleiben vorn: ihr Rang wird über den höchsten ODER-Rang gehoben
                        upper = max(or_hits.values(), default=0.0)
                        word_hits = {**or_hits, **{k: v + abs(upper) + 1 for k, v in word_hits.items()}}
                        search_kind = "oder"
                sql += f" AND id IN ({','.join('?' * len(word_hits))})" if word_hits else " AND 0"
                par += list(word_hits)
            else:
                for w in words:
                    sql += " AND text LIKE ?"
                    par.append(f"%{w}%")
        ids = [r[0] for r in db().execute(sql + f" ORDER BY zuletzt DESC LIMIT {max(400, int(limit))}", par)]
    word_search.set(search_kind)
    now_dt = datetime.now(timezone.utc)
    rated = []
    top_word = max(word_hits.values(), default=1.0) or 1.0
    mem_objects = load_many(ids)
    for oid in ids:
        o = mem_objects.get(oid)
        if not o:
            continue
        hours = max(0.0, (now_dt - datetime.fromisoformat(o.last_at)).total_seconds() / 3600)
        recency = (1.0 + hours) ** (-DECAY_D)
        bonus = min(BONUS_MAX, BONUS_PER_INSTANCE * o.foreign_confirmations())
        importance = min(1.0, o.importance / 3 * 0.6 + math.log1p(o.confirmed * 2 + o.accesses) / 6 - o.refuted * 0.5) + bonus
        relevance = (word_hits.get(oid, 0.0) / top_word) if words else 1.0
        rated.append((relevance + recency + importance, o, {"relevanz": round(relevance, 2), "aktualitaet": round(recency, 2),
                                                                   "wichtigkeit": round(importance, 2)}))
    rated.sort(key=lambda x: -x[0])
    return rated[:limit]


def most_salient_hashtag(hits: list, filter_text: str) -> str | None:
    """Der häufigste inhaltliche Hashtag der Treffer, der nicht schon im Filter steht (Trichter-Schritt). Rein."""
    in_filter = set(re.findall(r"[a-z][a-z0-9_-]*:[^\s()!]+", filter_text or ""))
    tally: dict[str, int] = {}
    for o in hits:
        for t in o.hashtags:
            if t.startswith(ADMIN_PREFIXES) or t in in_filter:
                continue
            tally[t] = tally.get(t, 0) + 1
    if not tally:
        return None
    best = max(tally.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0] if best[1] >= 2 or len(hits) == 1 else None


def drilldown(filter_text: str, levels: int = 3, limit: int = 5) -> list[dict]:
    """Trichter: suchen, auffälligsten Hashtag ergänzen, erneut suchen — bis nichts Neues mehr kommt."""
    levels_off, filt = [], (filter_text or "").strip()
    for _ in range(max(1, levels)):
        hits = [o for _, o, _g in recall(filt, limit=limit * 4)]
        next_try = most_salient_hashtag(hits, filt)
        levels_off.append({"filter": filt, "gesamt": len(hits), "treffer": hits[:limit], "naechster": next_try})
        if not next_try or len(hits) <= 1:
            break
        filt = f"{filt} {next_try}".strip()
    return levels_off
