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

from . import anonym
from .protokoll import log

ARTEN = ("erfahrung", "antwort", "erkenntnis", "regel", "reflex", "gespraech", "suche", "frage", "selbst", "schlaf", "modell", "skill", "bewertung")
#: strittig = von genau einer fremden Instanz widerlegt (erscheint weiter, mit Vermerk); widerlegt = vom Urheber
#: oder von ≥ 2 verschiedenen Instanzen widerlegt (erscheint nicht mehr)
#: archiviert = Stummel (Text, Hashtags) bleibt, Inhalt komprimiert in Tabelle archiv; nur mit modus:archiviert im Filter sichtbar
#: aufgegangen = Skill ist in einem anderen aufgegangen (Fusion); bleibt mit Verweis, erscheint nicht mehr in Suchen
#: quarantaene = importiert und noch nicht freigegeben; erscheint in keiner Suche und keinem Hinweis
MODI = ("aktiv", "test", "aus", "defekt", "strittig", "widerlegt", "archiviert", "aufgegangen", "quarantaene")
#: Kollektiv: wer darf ein Objekt lesen? privat = nur die Urheber-Instanz (Ergebnisse können Zugangsdaten enthalten),
#: geteilt = alle Instanzen. Der Loop (Server) sieht alles. Erschöpfend für ARTEN.
SICHT_JE_ART = {"erfahrung": "privat", "antwort": "privat", "erkenntnis": "geteilt", "regel": "geteilt", "reflex": "geteilt",
                "gespraech": "geteilt", "suche": "geteilt", "frage": "geteilt", "selbst": "geteilt", "schlaf": "geteilt", "modell": "geteilt", "skill": "geteilt", "bewertung": "privat"}
#: Urheber für Objekte, die der Server selbst anlegt (Loop) — eine benannte Instanz, kein NULL
SERVER_INSTANZ = "vi"
#: Gewichtbonus je verschiedener FREMDER Instanz, die bestätigt hat (Selbstbestätigung zählt nicht als Beleg)
BONUS_JE_INSTANZ = 0.2
BONUS_MAX = 0.6
#: Änderungsgeschichte je Objekt; ältere Einträge werden gezählt gekürzt (daten.aenderungen_gekuerzt)
GESCHICHTE_MAX = 50
DATEN_MAX = 400_000
#: Aktualität nach **Potenzgesetz** (Wixted & Ebbesen 1991; ACT-R: Anderson & Schooler 1991 — docs/FORSCHUNG.md A9):
#: aktualitaet = (1 + h)^(−VERFALL_D), h = Stunden seit dem letzten Zugriff. Schnell am Anfang, langsam danach:
#: 1 h 0,81 · 1 d 0,38 · 7 d 0,21 · 30 d 0,14 · 1 a 0,07. Bis 0.3.0 exponentiell 0,995^h (Park et al., dort je
#: Spielstunde) — das ließ Älteres als 2 Wochen praktisch verschwinden (30 d: 0,03). VERFALL_D = 0,3 ist ein Startwert.
VERFALL_D = 0.3
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,30}:[^\s()]+$")
#: Hashtags, die Verwaltung sind und nicht Inhalt (für Verknüpfung und Trichter ignoriert)
VERWALTUNG = ("art:", "cache:", "ok:", "serial:", "tag:", "instanz:", "zustand:", "an:", "von:", "ueberraschung:",
              "modus:", "herkunft:", "konflikt:", "selbst:", "selbstbereich:", "modell:", "fusion:", "dublette:", "scorer:", "ziel:", "note:")

sperre = threading.RLock()
INHALT_MAX = 200_000
_db: sqlite3.Connection | None = None
fts = False
#: aktive Datenbank und Langzeitlager (lager.py) — gesetzt von oeffne()
pfad_aktiv: Path | None = None
lager_pfad: Path | None = None

#: Das Gespräch (Seriennummer), in dessen Auftrag gerade gearbeitet wird — je Anfrage-Thread gesetzt
aktuelles_gespraech: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelles_gespraech", default=None)
#: Die Instanz, in deren Auftrag gerade gelesen/geschrieben wird. None = der Server selbst (Loop): sieht alles.
aktuelle_instanz: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelle_instanz", default=None)


def jetzt() -> str:
    """ISO-8601 UTC mit Millisekunden: Vergleiche `zeit > seit` (Schlaf, Loop) trennen sonst nicht, was in derselben
    Sekunde entstand. Ältere Einträge (Sekunden, 0.1–0.3) sortieren als Text korrekt davor ('+' < '.')."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def hashwert(*teile: str) -> str:
    return hashlib.sha256("\n".join(teile).encode()).hexdigest()[:24]


def db() -> sqlite3.Connection:
    if _db is None:
        raise RuntimeError("Gedächtnis nicht geöffnet (oeffne() fehlt)")
    return _db


def oeffne(pfad: Path) -> None:
    """Datenbank öffnen bzw. anlegen. Datei und Begleitdateien nur für den Eigentümer lesbar (0600):
    das Gedächtnis enthält Gesprächsverläufe und Werkzeugergebnisse, darin können Zugangsdaten stehen."""
    global _db, fts, pfad_aktiv, lager_pfad
    pfad.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    alte_umask = os.umask(0o077)
    try:
        con = sqlite3.connect(str(pfad), check_same_thread=False, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
    finally:
        os.umask(alte_umask)
    for f in (pfad, Path(f"{pfad}-wal"), Path(f"{pfad}-shm")):
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
    _migriere(con)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS objekt_fts USING fts5(id UNINDEXED, text)")
        fts = True
    except sqlite3.OperationalError as exc:
        fts = False
        log(f"FTS5 nicht verfügbar ({exc}) — Volltext über LIKE")
    con.commit()
    with sperre:
        if _db is not None:
            _db.close()
        _db = con
        pfad_aktiv, lager_pfad = pfad, pfad.with_name(f"{pfad.stem}-lager.db")


def _migriere(con: sqlite3.Connection) -> None:
    """0.1.x → 0.2.0: Spalten instanz/sicht nachrüsten (Urheber aus dem Hashtag instanz:, Sicht aus der Art);
    Cache-Hashtag frage:<hash> → cache:<hash> (frage ist jetzt eine Art)."""
    spalten = {r[1] for r in con.execute("PRAGMA table_info(objekt)")}
    if "instanz" not in spalten:
        con.execute("ALTER TABLE objekt ADD COLUMN instanz TEXT NOT NULL DEFAULT 'vi'")
        con.execute("UPDATE objekt SET instanz = COALESCE((SELECT substr(tag, 9) FROM tag WHERE objekt_id = objekt.id "
                    "AND tag LIKE 'instanz:%' LIMIT 1), 'vi')")
        log("Migration: Spalte instanz nachgerüstet")
    if "sicht" not in spalten:
        con.execute("ALTER TABLE objekt ADD COLUMN sicht TEXT NOT NULL DEFAULT 'geteilt'")
        for art, sicht in SICHT_JE_ART.items():
            con.execute("UPDATE objekt SET sicht = ? WHERE art = ?", (sicht, art))
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


def sichtbar_fuer(o: "Objekt", instanz: str | None) -> bool:
    """Darf diese Instanz das Objekt lesen? None = der Server selbst."""
    return instanz is None or o.sicht == "geteilt" or o.instanz == instanz


def schliesse() -> None:
    global _db
    from . import lager
    lager.schliesse()
    with sperre:
        if _db is not None:
            _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _db.close()
            _db = None


@dataclass
class Objekt:
    """Ein Eintrag des Gedächtnisses. Feste Felder: id, art, zeit. Änderbar nur über Methoden (mit Geschichte)."""
    id: str
    art: str
    zeit: str
    zuletzt: str
    text: str = ""
    daten: dict = field(default_factory=dict)
    hashtags: list = field(default_factory=list)
    wichtigkeit: int = 1
    bestaetigt: int = 0
    widerlegt: int = 0
    zugriffe: int = 0
    modus: str = "aktiv"
    aenderungen: list = field(default_factory=list)
    gespraech: str | None = None
    instanz: str = SERVER_INSTANZ
    sicht: str = "geteilt"

    @staticmethod
    def _grund_pflicht(grund: str) -> None:
        if not (grund or "").strip():
            raise ValueError("Grund ist Pflicht — jede Änderung braucht einen zureichenden Grund")

    def aendere(self, wer: str, was: str, grund: str) -> None:
        self._grund_pflicht(grund)
        alle = self.aenderungen + [{"zeit": jetzt(), "wer": wer, "was": was, "grund": grund.strip()[:300]}]
        if len(alle) > GESCHICHTE_MAX:  # nichts verschwindet still: die Kürzung wird gezählt und in vi_objekt genannt
            self.daten["aenderungen_gekuerzt"] = self.daten.get("aenderungen_gekuerzt", 0) + len(alle) - GESCHICHTE_MAX
            alle = alle[-GESCHICHTE_MAX:]
        self.aenderungen = alle
        self.zuletzt = jetzt()

    def markiere(self, hinzu: list[str], weg: list[str], wer: str, grund: str) -> "Objekt":
        self._grund_pflicht(grund)
        for t in list(hinzu) + list(weg):
            if not TAG.match(t):
                raise ValueError(f"Hashtag {t!r} hat nicht die Form art:wert")
            if t.startswith(("art:", "tool:", "instanz:", "herkunft:", "herausgeber:", "pruefer:", "modus:")):
                raise ValueError(f"{t}: fester Hashtag (instanz: ist der Urheber aus dem Token; art:, tool:, herkunft:, herausgeber:, pruefer: und modus: setzt das System)")
        self.hashtags = sorted((set(self.hashtags) | set(hinzu)) - set(weg))
        self.aendere(wer, " ".join([f"+{t}" for t in hinzu] + [f"-{t}" for t in weg]), grund)
        return speichere(self)

    def bestaetige(self, wer: str, grund: str, instanz: str | None = None) -> "Objekt":
        """Bestätigen. Zählt je Instanz (daten.bestaetigt_von); Gewichtbonus nur für FREMDE Instanzen."""
        self._grund_pflicht(grund)  # erst prüfen, dann ändern — eine Ablehnung lässt das Objekt unverändert
        i = instanz or SERVER_INSTANZ
        von = dict(self.daten.get("bestaetigt_von") or {})
        von[i] = von.get(i, 0) + 1
        self.daten["bestaetigt_von"] = von
        self.bestaetigt += 1
        if self.modus == "strittig" and i != self.instanz:
            self.modus = "aktiv"  # eine fremde Bestätigung hebt den Streit auf — mit Geschichte
        self.aendere(wer, "bestätigt" + (" (Selbstbestätigung, kein Gewichtbonus)" if i == self.instanz else ""), grund)
        return speichere(self)

    def widerlege(self, wer: str, grund: str, instanz: str | None = None) -> "Objekt":
        """Widerlegen. Urheber selbst oder ≥ 2 verschiedene Instanzen → widerlegt (verschwindet aus Suchen);
        genau eine fremde Instanz → strittig (bleibt sichtbar, mit Vermerk) — eine Instanz allein löscht nicht
        das Wissen einer anderen."""
        self._grund_pflicht(grund)
        i = instanz or SERVER_INSTANZ
        von = dict(self.daten.get("widerlegt_von") or {})
        von[i] = von.get(i, 0) + 1
        self.daten["widerlegt_von"] = von
        self.widerlegt += 1
        self.modus = "widerlegt" if (i == self.instanz or len(von) >= 2) else "strittig"
        self.aendere(wer, self.modus, grund)
        return speichere(self)

    def fremde_bestaetigungen(self) -> int:
        """Verschiedene fremde Instanzen, die bestätigt haben. Der Server (`vi`, Schlaf) zählt nicht als fremd —
        eine automatische Bestätigung soll das Gewicht nicht heben (keine Selbstbestätigung des Systems)."""
        return len([i for i in (self.daten.get("bestaetigt_von") or {}) if i not in (self.instanz, SERVER_INSTANZ)])

    def verknuepfe(self, anderes_id: str, grund: str) -> None:
        with sperre:
            for a, b in ((self.id, anderes_id), (anderes_id, self.id)):
                # Ein Beleg wiegt mehr als eine automatische Kante und ersetzt sie; umgekehrt nie
                db().execute("INSERT INTO kante (a, b, grund, zeit) VALUES (?,?,?,?) ON CONFLICT (a, b) DO UPDATE SET grund = excluded.grund, "
                             "zeit = excluded.zeit WHERE excluded.grund LIKE 'Beleg%' AND kante.grund NOT LIKE 'Beleg%'", (a, b, grund[:200], jetzt()))
            db().commit()

    def zugriff(self) -> None:
        """Erinnert heißt verstärkt: Zugriff zählt, zuletzt rückt vor (Konsolidierung). Relativ hochgezählt —
        kein verlorener Zähler, auch wenn ein anderer Thread dasselbe Objekt gleichzeitig liest."""
        self.zuletzt = jetzt()
        with sperre:
            db().execute("UPDATE objekt SET zugriffe = zugriffe + 1, zuletzt = ? WHERE id = ?", (self.zuletzt, self.id))
            db().commit()
            self.zugriffe = db().execute("SELECT zugriffe FROM objekt WHERE id = ?", (self.id,)).fetchone()[0]

    def kanten(self) -> list[tuple[str, str]]:
        with sperre:
            return db().execute("SELECT b, grund FROM kante WHERE a = ?", (self.id,)).fetchall()


SPALTEN = ("id", "art", "zeit", "zuletzt", "text", "daten", "wichtigkeit", "bestaetigt", "widerlegt", "zugriffe",
           "modus", "aenderungen", "gespraech", "instanz", "sicht")


def _objekt_aus(row) -> Objekt:
    d = dict(zip(SPALTEN, row))
    d["daten"] = json.loads(d["daten"] or "{}")
    d["aenderungen"] = json.loads(d["aenderungen"] or "[]")
    o = Objekt(**d)
    with sperre:
        o.hashtags = [r[0] for r in db().execute("SELECT tag FROM tag WHERE objekt_id = ? ORDER BY tag", (o.id,))]
    return o


def lade(oid: str) -> Objekt | None:
    with sperre:
        row = db().execute(f"SELECT {', '.join(SPALTEN)} FROM objekt WHERE id = ?", (oid,)).fetchone()
        return _objekt_aus(row) if row else None


def _daten_json(o: Objekt) -> str:
    """Zu große Daten werden benannt ersetzt. Ein Abschneiden des JSON-Textes machte das Objekt unlesbar."""
    js = json.dumps(o.daten, ensure_ascii=False)
    if len(js) <= DATEN_MAX:
        return js
    log(f"{o.id}: daten mit {len(js)} Zeichen über Grenze {DATEN_MAX} — ersetzt")
    return json.dumps({"gekuerzt_zeichen": len(js), "grund": f"daten über {DATEN_MAX} Zeichen"})


def lade_viele(oids: list[str]) -> dict[str, Objekt]:
    """Mehrere Objekte in zwei Abfragen statt in zwei je Objekt."""
    aus: dict[str, Objekt] = {}
    with sperre:
        for i in range(0, len(oids), 900):
            teil = oids[i:i + 900]
            marken = ",".join("?" * len(teil))
            tags: dict[str, list[str]] = {}
            for oid, tag in db().execute(f"SELECT objekt_id, tag FROM tag WHERE objekt_id IN ({marken}) ORDER BY tag", teil):
                tags.setdefault(oid, []).append(tag)
            for row in db().execute(f"SELECT {', '.join(SPALTEN)} FROM objekt WHERE id IN ({marken})", teil):
                d = dict(zip(SPALTEN, row))
                d["daten"] = json.loads(d["daten"] or "{}")
                d["aenderungen"] = json.loads(d["aenderungen"] or "[]")
                aus[d["id"]] = Objekt(**d, hashtags=tags.get(d["id"], []))
    return aus


def speichere(o: Objekt) -> Objekt:
    tags = sorted(set(o.hashtags) | {f"art:{o.art}", f"instanz:{o.instanz}"})
    with sperre:
        db().execute(f"INSERT OR REPLACE INTO objekt ({', '.join(SPALTEN)}) VALUES ({', '.join('?' * len(SPALTEN))})",
                     (o.id, o.art, o.zeit, o.zuletzt, o.text, _daten_json(o), o.wichtigkeit,
                      o.bestaetigt, o.widerlegt, o.zugriffe, o.modus, json.dumps(o.aenderungen, ensure_ascii=False), o.gespraech,
                      o.instanz, o.sicht))
        db().execute("DELETE FROM tag WHERE objekt_id = ?", (o.id,))
        db().executemany("INSERT OR IGNORE INTO tag (objekt_id, tag) VALUES (?, ?)", [(o.id, t) for t in tags])
        if fts:
            db().execute("DELETE FROM objekt_fts WHERE id = ?", (o.id,))
            db().execute("INSERT INTO objekt_fts (id, text) VALUES (?, ?)", (o.id, (o.text + "\n" + str(o.daten.get("inhalt") or ""))[:300000]))
        db().commit()
    o.hashtags = tags
    return o


def loesche(oids: list[str]) -> int:
    """Objekte samt Hashtags, Volltext, Kanten und Lagerinhalt entfernen — keine hängenden Kanten, keine Reste im Lager."""
    from . import lager
    lager.loesche(oids)
    with sperre:
        for a in oids:
            db().execute("DELETE FROM objekt WHERE id = ?", (a,))
            db().execute("DELETE FROM tag WHERE objekt_id = ?", (a,))
            db().execute("DELETE FROM kante WHERE a = ? OR b = ?", (a, a))
            if fts:
                db().execute("DELETE FROM objekt_fts WHERE id = ?", (a,))
        db().commit()
    return len(oids)


def neues_objekt(art: str, text: str, hashtags: list[str], daten: dict | None = None, wichtigkeit: int = 1,
                 wer: str = "vi", grund: str = "", oid: str | None = None, modus: str = "aktiv",
                 gespraech: str | None = None, instanz: str | None = None) -> Objekt:
    if art not in ARTEN:
        raise ValueError(f"art muss {', '.join(ARTEN)} sein")
    for t in hashtags:
        if not TAG.match(t):
            raise ValueError(f"Hashtag {t!r} hat nicht die Form art:wert")
    # instanz: ist kein freier Hashtag, sondern der Urheber (Spalte instanz) — ein Ding, ein Ort
    hashtags = [t for t in hashtags if not t.startswith("instanz:")]
    text, daten = anonym.ohne_geheimnisse(text), anonym.ohne_geheimnisse(daten)  # Zugangsdaten werden nie gespeichert
    zeit = jetzt()
    # Zufallsanteil: zwei gleiche Handlungen in derselben Sekunde sind zwei Objekte, nicht eines (sonst überschreibt
    # INSERT OR REPLACE das erste still — gefunden von test_eingebaute_werkzeuge_nie_aus_gedaechtnis)
    o = Objekt(id=oid or f"{art}:{hashwert(art, text, zeit, json.dumps(daten or {}, sort_keys=True), secrets.token_hex(8))}", art=art, zeit=zeit,
               zuletzt=zeit, text=text, daten=daten or {}, hashtags=list(hashtags), wichtigkeit=max(0, min(3, wichtigkeit)),
               modus=modus, gespraech=gespraech or aktuelles_gespraech.get(),
               instanz=instanz or aktuelle_instanz.get() or SERVER_INSTANZ, sicht=SICHT_JE_ART[art],
               aenderungen=[{"zeit": zeit, "wer": wer, "was": "angelegt", "grund": (grund or "angelegt")[:300]}])
    speichere(o)
    if modus != "quarantaene":  # Ungeprüftes bekommt keine Verbindung zum eigenen Wissen
        verknuepfe_aehnliche(o)
    return o


def verknuepfe_aehnliche(o: Objekt, mindestens: int = 2, limit: int = 5) -> None:
    """Zettelkasten: Objekte, die ≥ `mindestens` inhaltliche Hashtags teilen, werden verbunden (A-Mem-Idee)."""
    inhalt = [t for t in o.hashtags if not t.startswith(VERWALTUNG)]  # sonst verbände instanz:/art: alles mit allem
    if len(inhalt) < mindestens or o.art in ("antwort",):
        return
    with sperre:
        rows = db().execute(
            f"SELECT objekt_id, COUNT(*) n FROM tag WHERE tag IN ({','.join('?' * len(inhalt))}) AND objekt_id <> ? "
            f"GROUP BY objekt_id HAVING n >= ? ORDER BY n DESC LIMIT ?", (*inhalt, o.id, mindestens, limit)).fetchall()
    for oid, n in rows:
        o.verknuepfe(oid, f"{n} gemeinsame Hashtags")


# ── Erinnern: Filtersprache + Gewichtung ─────────────────────────────────────

def lies_filter(text: str) -> tuple[list[list[str]], list[str], list[str]]:
    """Filtertext → (UND-Gruppen aus ODER-Tags, Ausschluss-Tags, Freiwörter). `(a OR b) c !d wort`. Rein."""
    gruppen, weg, worte = [], [], []
    for m in re.finditer(r"\(([^()]*)\)|(!?\S+)", text or ""):
        if m.group(1) is not None:
            alt = [t for t in re.split(r"\s+OR\s+|\s+", m.group(1).strip()) if t and t != "OR"]
            if alt:
                gruppen.append(alt)
            continue
        tok = m.group(2)
        if tok.upper() == "OR":
            continue
        if tok.startswith("!"):
            weg.append(tok[1:])
        elif ":" in tok:
            gruppen.append([tok])
        else:
            worte.append(tok)
    return gruppen, weg, worte


def _tag_bedingung(tag: str) -> tuple[str, tuple]:
    return ("tag LIKE ?", (tag[:-1] + "%",)) if tag.endswith("*") else ("tag = ?", (tag,))


def _filter_sql(gruppen: list, weg: list, betrachter: str | None) -> tuple[str, list]:
    """SQL für Modus, Sicht und Hashtag-Bedingungen (ohne Freitext) — eine Quelle für erinnere() und ids_zum_filter()."""
    sql, par = "SELECT id FROM objekt WHERE modus <> 'widerlegt'", []
    if not any("modus:quarantaene" in grp for grp in gruppen):
        sql += " AND modus <> 'quarantaene'"  # nur über vi_quarantaene
    if not any("modus:aufgegangen" in grp for grp in gruppen):
        sql += " AND modus <> 'aufgegangen'"  # Aufgegangenes nur auf Nachfrage (Verweis steht im Objekt)
    if not any("modus:archiviert" in grp for grp in gruppen):
        sql += " AND modus <> 'archiviert'"  # Archiviertes nur auf ausdrückliche Nachfrage
    if betrachter is not None:
        sql += " AND (sicht = 'geteilt' OR instanz = ?)"
        par.append(betrachter)
    for g in gruppen:
        teile = [_tag_bedingung(t) for t in g]
        sql += " AND id IN (SELECT objekt_id FROM tag WHERE " + " OR ".join(b for b, _ in teile) + ")"
        for _, p in teile:
            par += list(p)
    for t in weg:
        b, p = _tag_bedingung(t)
        sql += f" AND id NOT IN (SELECT objekt_id FROM tag WHERE {b})"
        par += list(p)
    return sql, par


def ids_zum_filter(filtertext: str, arten: tuple[str, ...] = (), betrachter: str | None = "aktuell") -> list[str]:
    """Alle sichtbaren IDs zu den Hashtag-Bedingungen des Filters, ohne Obergrenze (Kandidaten der semantischen Suche)."""
    if betrachter == "aktuell":
        betrachter = aktuelle_instanz.get()
    gruppen, weg, _w = lies_filter(filtertext)
    if arten:
        gruppen.append([f"art:{a}" for a in arten])
    sql, par = _filter_sql(gruppen, weg, betrachter)
    with sperre:
        return [r[0] for r in db().execute(sql, par)]


#: Wie die letzte Wortsuche in diesem Kontext lief: "und" (alle Wörter), "oder" (Ersatz, weil zu wenig alle Wörter enthielten) oder None.
wortsuche: contextvars.ContextVar[str | None] = contextvars.ContextVar("wortsuche", default=None)


def erinnere(filtertext: str, limit: int = 10, arten: tuple[str, ...] = (), betrachter: str | None = "aktuell",
             oder_ersatz: bool = False) -> list[tuple[float, Objekt, dict]]:
    """Objekte zum Filter, gewichtet: Relevanz (Tag-/Worttreffer) + Aktualität + Wichtigkeit (Park et al. 2023)
    + Bonus je fremder bestätigender Instanz. Sichtbar ist, was geteilt ist oder dem Betrachter gehört
    (betrachter "aktuell" = Instanz der laufenden Anfrage; None = Server, sieht alles).
    Freitext verlangt alle Wörter (UND). oder_ersatz=True: enthalten weniger als `limit` Objekte alle Wörter, wird mit
    einer ODER-Suche aufgefüllt (BM25 ordnet Objekte mit mehr Wörtern nach vorn); `wortsuche` sagt danach, welche lief."""
    if betrachter == "aktuell":
        betrachter = aktuelle_instanz.get()
    gruppen, weg, worte = lies_filter(filtertext)
    if arten:
        gruppen.append([f"art:{a}" for a in arten])
    sql, par = _filter_sql(gruppen, weg, betrachter)
    wort_treffer: dict[str, float] = {}
    art_der_suche = None
    with sperre:
        if worte:
            if fts:
                begriffe = ['"' + w.replace('"', '') + '"' for w in worte]
                art_der_suche = "und"

                def _fts(q: str) -> dict[str, float]:
                    return {oid: -float(rank) for oid, rank in db().execute(
                        f"SELECT id, rank FROM objekt_fts WHERE objekt_fts MATCH ? AND id IN ({sql}) ORDER BY rank LIMIT 500", (q, *par))}
                wort_treffer = _fts(" ".join(begriffe))
                if oder_ersatz and len(begriffe) > 1 and len(wort_treffer) < limit:
                    oder = _fts(" OR ".join(begriffe))
                    if len(oder) > len(wort_treffer):
                        # Objekte mit allen Wörtern bleiben vorn: ihr Rang wird über den höchsten ODER-Rang gehoben
                        oben = max(oder.values(), default=0.0)
                        wort_treffer = {**oder, **{k: v + abs(oben) + 1 for k, v in wort_treffer.items()}}
                        art_der_suche = "oder"
                sql += f" AND id IN ({','.join('?' * len(wort_treffer))})" if wort_treffer else " AND 0"
                par += list(wort_treffer)
            else:
                for w in worte:
                    sql += " AND text LIKE ?"
                    par.append(f"%{w}%")
        ids = [r[0] for r in db().execute(sql + f" ORDER BY zuletzt DESC LIMIT {max(400, int(limit))}", par)]
    wortsuche.set(art_der_suche)
    jetzt_dt = datetime.now(timezone.utc)
    bewertet = []
    hoechste_wort = max(wort_treffer.values(), default=1.0) or 1.0
    objekte = lade_viele(ids)
    for oid in ids:
        o = objekte.get(oid)
        if not o:
            continue
        stunden = max(0.0, (jetzt_dt - datetime.fromisoformat(o.zuletzt)).total_seconds() / 3600)
        aktualitaet = (1.0 + stunden) ** (-VERFALL_D)
        bonus = min(BONUS_MAX, BONUS_JE_INSTANZ * o.fremde_bestaetigungen())
        wichtigkeit = min(1.0, o.wichtigkeit / 3 * 0.6 + math.log1p(o.bestaetigt * 2 + o.zugriffe) / 6 - o.widerlegt * 0.5) + bonus
        relevanz = (wort_treffer.get(oid, 0.0) / hoechste_wort) if worte else 1.0
        bewertet.append((relevanz + aktualitaet + wichtigkeit, o, {"relevanz": round(relevanz, 2), "aktualitaet": round(aktualitaet, 2),
                                                                   "wichtigkeit": round(wichtigkeit, 2)}))
    bewertet.sort(key=lambda x: -x[0])
    return bewertet[:limit]


def auffaelligster_hashtag(treffer: list, filtertext: str) -> str | None:
    """Der häufigste inhaltliche Hashtag der Treffer, der nicht schon im Filter steht (Trichter-Schritt). Rein."""
    im_filter = set(re.findall(r"[a-z][a-z0-9_-]*:[^\s()!]+", filtertext or ""))
    zaehl: dict[str, int] = {}
    for o in treffer:
        for t in o.hashtags:
            if t.startswith(VERWALTUNG) or t in im_filter:
                continue
            zaehl[t] = zaehl.get(t, 0) + 1
    if not zaehl:
        return None
    best = max(zaehl.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0] if best[1] >= 2 or len(treffer) == 1 else None


def vertiefe(filtertext: str, stufen: int = 3, limit: int = 5) -> list[dict]:
    """Trichter: suchen, auffälligsten Hashtag ergänzen, erneut suchen — bis nichts Neues mehr kommt."""
    stufen_aus, filt = [], (filtertext or "").strip()
    for _ in range(max(1, stufen)):
        treffer = [o for _, o, _g in erinnere(filt, limit=limit * 4)]
        naechster = auffaelligster_hashtag(treffer, filt)
        stufen_aus.append({"filter": filt, "gesamt": len(treffer), "treffer": treffer[:limit], "naechster": naechster})
        if not naechster or len(treffer) <= 1:
            break
        filt = f"{filt} {naechster}".strip()
    return stufen_aus
