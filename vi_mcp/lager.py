"""Langzeitlager — Housekeeping: nicht mehr verwendete Einträge verlassen den aktiven Speicher, ohne zu verschwinden.

Eine eigene SQLite-Datei neben dem Gedächtnis (`<db>-lager.db`, 0600). Der aktive Speicher bleibt klein und schnell.
Läuft im Schlaf (Schritt 5), also im einen Loop-Thread; es gibt weiter nur einen Schreiber.

Was „nicht mehr verwendet“ heißt (Startwerte in TAGE, per Konfiguration `lager_tage` änderbar):
  erfahrung                         30 Tage alt, nie abgerufen, ist kein Beleg
  schlaf (Berichte)                 90 Tage alt
  erkenntnis, regel, suche, skill  180 Tage weder abgerufen, geändert noch als Hinweis gezeigt
  Gesprächs-Rohverläufe             30 Tage seit der letzten Änderung, Gespräch nicht offen
Nie automatisch: selbst, modell, frage (eigener Lebenszyklus), reflex (würde ein Verhalten still abschalten), gespraech
(die Zusammenfassung bleibt). Was als Beleg dient, bleibt ebenfalls: nur Kanten mit Grund „Beleg…“ zählen.

Im Gedächtnis bleibt ein Stummel: gekürzter Text, Hashtags, Zeit, Grund, `modus:archiviert`. Er erscheint nur, wenn der
Filter `modus:archiviert` enthält. Passt ein gelagerter Wissenseintrag zu einer Handlung, nennt `vi_vorher` das in einer
Zeile. Zurück kommt ein Eintrag mit `vi_lager_hole` (mit Grund, in seinem alten Modus). Gelöscht wird im Lager nur
über die Löschwege für Gespräche und Instanzen.
Reihenfolge über die zwei Dateien: erst das Ziel schreiben, dann die Quelle ändern. Ein Absturz dazwischen hinterlässt
eine Dublette, die der nächste Lauf überschreibt, aber keinen Verlust.
"""
from __future__ import annotations

import json
import os
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import gedaechtnis as g
from .protokoll import log

TAGE = {"erfahrung": 30, "schlaf": 90, "erkenntnis": 180, "regel": 180, "suche": 180, "skill": 180}
TAGE_ROH = 30
WISSEN = ("erkenntnis", "regel", "suche", "skill")
STUMMEL_ZEICHEN = 200
#: Freier Anteil der Hauptdatei, ab dem sie neu geschrieben wird
VACUUM_AB = 0.25
#: Kanten dieser Ziele schützen eine Erfahrung, wenn sie Beleg sind
BELEG_ZIELE = ("erkenntnis:", "regel:", "suche:", "skill:", "selbst:")

_con: sqlite3.Connection | None = None
_pfad: Path | None = None


def db() -> sqlite3.Connection:
    global _con, _pfad
    if g.lager_pfad is None:
        raise RuntimeError("Gedächtnis nicht geöffnet")
    if _con is None or _pfad != g.lager_pfad:
        if _con is not None:
            _con.close()
        alte = os.umask(0o077)
        try:
            _con = sqlite3.connect(str(g.lager_pfad), check_same_thread=False, timeout=30)
        finally:
            os.umask(alte)
        os.chmod(g.lager_pfad, 0o600)
        _pfad = g.lager_pfad
        _con.executescript("""
            CREATE TABLE IF NOT EXISTS objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, instanz TEXT NOT NULL, sicht TEXT NOT NULL,
                eingelagert TEXT NOT NULL, modus_vorher TEXT NOT NULL, grund TEXT NOT NULL, roh BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS gespraech_roh (serial TEXT PRIMARY KEY, eingelagert TEXT NOT NULL, roh BLOB NOT NULL, laenge INTEGER NOT NULL);
        """)
        _con.commit()
    return _con


def schliesse() -> None:
    global _con, _pfad
    with g.sperre:
        if _con is not None:
            _con.close()
        _con, _pfad = None, None


def einlagern(o: g.Objekt, grund: str) -> None:
    """Inhalt ins Lager, Stummel im Gedächtnis."""
    if o.modus == "archiviert":
        return
    from . import vektor
    roh = zlib.compress(json.dumps({"text": o.text, "daten": o.daten, "hashtags": o.hashtags}, ensure_ascii=False).encode())
    with g.sperre:
        db().execute("INSERT OR REPLACE INTO objekt (id, art, instanz, sicht, eingelagert, modus_vorher, grund, roh) VALUES (?,?,?,?,?,?,?,?)",
                     (o.id, o.art, o.instanz, o.sicht, g.jetzt(), o.modus, grund[:300], roh))
        db().commit()
    o.daten = {"lager": True, "eingelagert": g.jetzt(), "grund": grund[:300], "bytes": len(roh)}
    o.text = o.text[:STUMMEL_ZEICHEN]
    o.modus = "archiviert"
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:archiviert"]
    o.aendere("vi", "ins Langzeitlager", grund)
    g.speichere(o)
    vektor.entferne(o.id)


def inhalt(oid: str) -> dict | None:
    with g.sperre:
        row = db().execute("SELECT art, instanz, sicht, eingelagert, modus_vorher, grund, roh FROM objekt WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    return {"art": row[0], "instanz": row[1], "sicht": row[2], "eingelagert": row[3], "modus_vorher": row[4], "grund": row[5],
            **json.loads(zlib.decompress(row[6]))}


def zurueckholen(oid: str, wer: str, grund: str) -> g.Objekt:
    """Vollständigen Inhalt und alten Modus wiederherstellen. Der Eintrag zählt danach als gerade verwendet."""
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    d = inhalt(oid)
    o = g.lade(oid)
    if not d or not o or o.modus != "archiviert":
        raise ValueError(f"{oid} liegt nicht im Langzeitlager")
    o.text, o.daten, o.hashtags, o.modus = d["text"], d["daten"], d["hashtags"], d["modus_vorher"]
    o.aendere(wer, "aus dem Langzeitlager geholt", grund)
    g.speichere(o)
    with g.sperre:
        db().execute("DELETE FROM objekt WHERE id = ?", (oid,))
        db().commit()
    return o


def loesche(oids: list[str]) -> None:
    """Gehört zum Löschen im Gedächtnis: was gelöscht wird, darf nicht im Lager überleben."""
    if g.lager_pfad is None or not oids:
        return
    with g.sperre:
        db().executemany("DELETE FROM objekt WHERE id = ?", [(o,) for o in oids])
        db().commit()


def loesche_roh(serial: str) -> None:
    with g.sperre:
        db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
        db().commit()


def roh(serial: str) -> bytes | None:
    with g.sperre:
        row = db().execute("SELECT roh FROM gespraech_roh WHERE serial = ?", (serial,)).fetchone()
    return row[0] if row else None


def _grenze(tage: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(timespec="milliseconds")


def _ungenutzt() -> list[tuple[str, str]]:
    aus: list[tuple[str, str]] = []
    beleg = " OR ".join(f"k.b LIKE '{p}%'" for p in BELEG_ZIELE)
    with g.sperre:
        for art in ("erfahrung", "schlaf"):
            grenze = _grenze(TAGE[art])
            sql = "SELECT id FROM objekt o WHERE art = ? AND modus <> 'archiviert' AND zeit < ?"
            if art == "erfahrung":
                sql += f" AND zugriffe = 0 AND NOT EXISTS (SELECT 1 FROM kante k WHERE k.a = o.id AND k.grund LIKE 'Beleg%' AND ({beleg}))"
            aus += [(r[0], f"Housekeeping: {art}, älter als {TAGE[art]} Tage, nicht verwendet") for r in g.db().execute(sql, (art, grenze))]
        for art in WISSEN:
            grenze = _grenze(TAGE[art])
            aus += [(r[0], f"Housekeeping: {art}, {TAGE[art]} Tage weder abgerufen, geändert noch gezeigt") for r in g.db().execute(
                "SELECT id FROM objekt o WHERE art = ? AND modus NOT IN ('archiviert', 'quarantaene') AND zuletzt < ? "
                "AND COALESCE(json_extract(daten, '$.zuletzt_gezeigt'), '') < ? "
                "AND NOT EXISTS (SELECT 1 FROM kante k WHERE k.a = o.id AND k.b LIKE 'selbst:%')", (art, grenze, grenze))]
    return aus


def _rohverlaeufe() -> int:
    from . import sitzung
    offen = {s.serial for s in sitzung.offene()}
    grenze = _grenze(TAGE_ROH)
    with g.sperre:
        zeilen = g.db().execute("SELECT r.serial, r.roh, r.laenge FROM gespraech_roh r JOIN objekt o ON o.id = 'gespraech:' || r.serial "
                                "WHERE o.zuletzt < ?", (grenze,)).fetchall()
    n = 0
    for serial, inhalt_roh, laenge in zeilen:
        if serial in offen:
            continue
        with g.sperre:
            db().execute("INSERT OR REPLACE INTO gespraech_roh (serial, eingelagert, roh, laenge) VALUES (?,?,?,?)", (serial, g.jetzt(), inhalt_roh, laenge))
            db().commit()
            g.db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
            g.db().commit()
        n += 1
    return n


def _verdichten() -> bool:
    with g.sperre:
        seiten = g.db().execute("PRAGMA page_count").fetchone()[0]
        frei = g.db().execute("PRAGMA freelist_count").fetchone()[0]
        if not seiten or frei / seiten < VACUUM_AB:
            return False
        g.db().commit()
        g.db().execute("VACUUM")
    return True


def aufraeumen() -> dict:
    """Schlaf-Schritt 5."""
    zaehler: dict[str, int] = {}
    for oid, grund in _ungenutzt():
        o = g.lade(oid)
        if o:
            einlagern(o, grund)
            zaehler[o.art] = zaehler.get(o.art, 0) + 1
    r = _rohverlaeufe()
    v = _verdichten()
    n = sum(zaehler.values())
    if n or r or v:
        log(f"Housekeeping: {n} Einträge und {r} Rohverläufe ins Langzeitlager{', Hauptdatei verdichtet' if v else ''}")
    return {"eingelagert": n, "je_art": zaehler, "rohverlaeufe": r, "verdichtet": v}


def hinweis(reize: list[str]) -> list[str]:
    """Eine Zeile für `vi_vorher`, wenn gelagertes Wissen zur Handlung passt."""
    if not reize:
        return []
    treffer = [o for _, o, _g in g.erinnere("(" + " OR ".join(reize) + ") modus:archiviert", limit=3, arten=WISSEN)]
    if not treffer:
        return []
    return ["Im Langzeitlager passen: " + "; ".join(f"[{o.id}] {o.text[:80]}" for o in treffer) + " — vi_lager_hole(id, grund) holt einen Eintrag zurück"]


def stand() -> dict:
    with g.sperre:
        n = db().execute("SELECT COUNT(*) FROM objekt").fetchone()[0]
        r = db().execute("SELECT COUNT(*) FROM gespraech_roh").fetchone()[0]
    groesse = lambda p: os.path.getsize(p) if p and os.path.exists(p) else 0
    return {"objekte": n, "rohverlaeufe": r, "lager_bytes": groesse(g.lager_pfad), "aktiv_bytes": groesse(g.pfad_aktiv) + groesse(f"{g.pfad_aktiv}-wal")}


def zeile() -> str:
    s = stand()
    return f"{s['objekte']} Einträge, {s['rohverlaeufe']} Rohverläufe, {s['lager_bytes'] // 1024} KB (aktiver Speicher {s['aktiv_bytes'] // 1024} KB)"
