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

from . import memory as g
from .log_output import log

DAYS = {"erfahrung": 30, "schlaf": 90, "erkenntnis": 180, "regel": 180, "suche": 180, "skill": 180}
DAYS_RAW = 30
KNOWLEDGE = ("erkenntnis", "regel", "suche", "skill")
STUB_CHARS = 200
#: Freier Anteil der Hauptdatei, ab dem sie neu geschrieben wird
VACUUM_FROM = 0.25
#: Kanten dieser Ziele schützen eine Erfahrung, wenn sie Beleg sind
EVIDENCE_TARGETS = ("erkenntnis:", "regel:", "suche:", "skill:", "selbst:")

_con: sqlite3.Connection | None = None
_fpath: Path | None = None


def db() -> sqlite3.Connection:
    global _con, _fpath
    if g.archive_path is None:
        raise RuntimeError("Gedächtnis nicht geöffnet")
    if _con is None or _fpath != g.archive_path:
        if _con is not None:
            _con.close()
        old_umask_value = os.umask(0o077)
        try:
            _con = sqlite3.connect(str(g.archive_path), check_same_thread=False, timeout=30)
        finally:
            os.umask(old_umask_value)
        os.chmod(g.archive_path, 0o600)
        _fpath = g.archive_path
        _con.executescript("""
            CREATE TABLE IF NOT EXISTS objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, instanz TEXT NOT NULL, sicht TEXT NOT NULL,
                eingelagert TEXT NOT NULL, modus_vorher TEXT NOT NULL, grund TEXT NOT NULL, roh BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS gespraech_roh (serial TEXT PRIMARY KEY, eingelagert TEXT NOT NULL, roh BLOB NOT NULL, laenge INTEGER NOT NULL);
        """)
        _con.commit()
    return _con


def close_db() -> None:
    global _con, _fpath
    with g.lock:
        if _con is not None:
            _con.close()
        _con, _fpath = None, None


def store_in_archive(o: g.MemoryObject, reason: str) -> None:
    """Inhalt ins Lager, Stummel im Gedächtnis."""
    if o.mode == "archiviert":
        return
    from . import vector
    raw = zlib.compress(json.dumps({"text": o.text, "daten": o.data, "hashtags": o.hashtags}, ensure_ascii=False).encode())
    with g.lock:
        db().execute("INSERT OR REPLACE INTO objekt (id, art, instanz, sicht, eingelagert, modus_vorher, grund, roh) VALUES (?,?,?,?,?,?,?,?)",
                     (o.id, o.kind, o.instance, o.visibility, g.now(), o.mode, reason[:300], raw))
        db().commit()
    o.data = {"lager": True, "eingelagert": g.now(), "grund": reason[:300], "bytes": len(raw)}
    o.text = o.text[:STUB_CHARS]
    o.mode = "archiviert"
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:archiviert"]
    o.change("vi", "ins Langzeitlager", reason)
    g.save(o)
    vector.remove_entry(o.id)


def content(oid: str) -> dict | None:
    with g.lock:
        row = db().execute("SELECT art, instanz, sicht, eingelagert, modus_vorher, grund, roh FROM objekt WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    return {"art": row[0], "instanz": row[1], "sicht": row[2], "eingelagert": row[3], "modus_vorher": row[4], "grund": row[5],
            **json.loads(zlib.decompress(row[6]))}


def retrieve(oid: str, who: str, reason: str) -> g.MemoryObject:
    """Vollständigen Inhalt und alten Modus wiederherstellen. Der Eintrag zählt danach als gerade verwendet."""
    if not (reason or "").strip():
        raise ValueError("Grund ist Pflicht")
    d = content(oid)
    o = g.load(oid)
    if not d or not o or o.mode != "archiviert":
        raise ValueError(f"{oid} liegt nicht im Langzeitlager")
    o.text, o.data, o.hashtags, o.mode = d["text"], d["daten"], d["hashtags"], d["modus_vorher"]
    o.change(who, "aus dem Langzeitlager geholt", reason)
    g.save(o)
    with g.lock:
        db().execute("DELETE FROM objekt WHERE id = ?", (oid,))
        db().commit()
    return o


def delete(oids: list[str]) -> None:
    """Gehört zum Löschen im Gedächtnis: was gelöscht wird, darf nicht im Lager überleben."""
    if g.archive_path is None or not oids:
        return
    with g.lock:
        db().executemany("DELETE FROM objekt WHERE id = ?", [(o,) for o in oids])
        db().commit()


def delete_raw(serial: str) -> None:
    with g.lock:
        db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
        db().commit()


def raw(serial: str) -> bytes | None:
    with g.lock:
        row = db().execute("SELECT roh FROM gespraech_roh WHERE serial = ?", (serial,)).fetchone()
    return row[0] if row else None


def _bound(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")


def _unused() -> list[tuple[str, str]]:
    outputs: list[tuple[str, str]] = []
    evidence = " OR ".join(f"k.b LIKE '{p}%'" for p in EVIDENCE_TARGETS)
    with g.lock:
        for kind in ("erfahrung", "schlaf"):
            bound = _bound(DAYS[kind])
            sql = "SELECT id FROM objekt o WHERE art = ? AND modus <> 'archiviert' AND zeit < ?"
            if kind == "erfahrung":
                sql += f" AND zugriffe = 0 AND NOT EXISTS (SELECT 1 FROM kante k WHERE k.a = o.id AND k.grund LIKE 'Beleg%' AND ({evidence}))"
            outputs += [(r[0], f"Housekeeping: {kind}, älter als {DAYS[kind]} Tage, nicht verwendet") for r in g.db().execute(sql, (kind, bound))]
        for kind in KNOWLEDGE:
            bound = _bound(DAYS[kind])
            outputs += [(r[0], f"Housekeeping: {kind}, {DAYS[kind]} Tage weder abgerufen, geändert noch gezeigt") for r in g.db().execute(
                "SELECT id FROM objekt o WHERE art = ? AND modus NOT IN ('archiviert', 'quarantaene') AND zuletzt < ? "
                "AND COALESCE(json_extract(daten, '$.zuletzt_gezeigt'), '') < ? "
                "AND NOT EXISTS (SELECT 1 FROM kante k WHERE k.a = o.id AND k.b LIKE 'selbst:%')", (kind, bound, bound))]
    return outputs


def _raw_histories() -> int:
    from . import session
    open_ = {s.serial for s in session.open_items()}
    bound = _bound(DAYS_RAW)
    with g.lock:
        lines = g.db().execute("SELECT r.serial, r.roh, r.laenge FROM gespraech_roh r JOIN objekt o ON o.id = 'gespraech:' || r.serial "
                                "WHERE o.zuletzt < ?", (bound,)).fetchall()
    n = 0
    for serial, content_raw, length in lines:
        if serial in open_:
            continue
        with g.lock:
            db().execute("INSERT OR REPLACE INTO gespraech_roh (serial, eingelagert, roh, laenge) VALUES (?,?,?,?)", (serial, g.now(), content_raw, length))
            db().commit()
            g.db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
            g.db().commit()
        n += 1
    return n


def _condense() -> bool:
    with g.lock:
        pages = g.db().execute("PRAGMA page_count").fetchone()[0]
        free = g.db().execute("PRAGMA freelist_count").fetchone()[0]
        if not pages or free / pages < VACUUM_FROM:
            return False
        g.db().commit()
        g.db().execute("VACUUM")
    return True


def cleanup() -> dict:
    """Schlaf-Schritt 5."""
    counter: dict[str, int] = {}
    for oid, reason in _unused():
        o = g.load(oid)
        if o:
            store_in_archive(o, reason)
            counter[o.kind] = counter.get(o.kind, 0) + 1
    r = _raw_histories()
    v = _condense()
    n = sum(counter.values())
    if n or r or v:
        log(f"Housekeeping: {n} Einträge und {r} Rohverläufe ins Langzeitlager{', Hauptdatei verdichtet' if v else ''}")
    return {"eingelagert": n, "je_art": counter, "rohverlaeufe": r, "verdichtet": v}


def hint(triggers: list[str]) -> list[str]:
    """Eine Zeile für `vi_vorher`, wenn gelagertes Wissen zur Handlung passt."""
    if not triggers:
        return []
    hits = [o for _, o, _g in g.recall("(" + " OR ".join(triggers) + ") modus:archiviert", limit=3, kinds=KNOWLEDGE)]
    if not hits:
        return []
    return ["Im Langzeitlager passen: " + "; ".join(f"[{o.id}] {o.text[:80]}" for o in hits) + " — vi_lager_hole(id, grund) holt einen Eintrag zurück"]


def progress() -> dict:
    with g.lock:
        n = db().execute("SELECT COUNT(*) FROM objekt").fetchone()[0]
        r = db().execute("SELECT COUNT(*) FROM gespraech_roh").fetchone()[0]
    size = lambda p: os.path.getsize(p) if p and os.path.exists(p) else 0
    return {"objekte": n, "rohverlaeufe": r, "lager_bytes": size(g.archive_path), "aktiv_bytes": size(g.fpath_active) + size(f"{g.fpath_active}-wal")}


def line() -> str:
    s = progress()
    return f"{s['objekte']} Einträge, {s['rohverlaeufe']} Rohverläufe, {s['lager_bytes'] // 1024} KB (aktiver Speicher {s['aktiv_bytes'] // 1024} KB)"
