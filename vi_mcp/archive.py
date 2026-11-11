"""Long-term archive — housekeeping: entries no longer used leave the active store without vanishing.

A separate SQLite file next to the memory (`<db>-lager.db`, 0600). The active store stays small and fast.
Runs during sleep (step 5), i.e. in the one loop thread; there is still only one writer.

What "no longer used" means (initial values in DAYS, changeable via the configuration `archive_days`):
  erfahrung                         30 days old, never recalled, is not evidence
  schlaf (reports)                  90 days old
  erkenntnis, regel, suche, skill  180 days neither recalled, changed nor shown as a hint
  raw conversation transcripts      30 days since the last change, conversation not open
Never automatically: selbst, modell, frage (own life cycle), reflex (would silently switch off a behaviour), gespraech
(the summary stays). What serves as evidence also stays: only edges with reason "Beleg…" count.

A stub stays in memory: shortened text, hashtags, time, reason, `modus:archiviert`. It appears only if the
filter contains `modus:archiviert`. If an archived knowledge entry fits an action, `vi_before` says so in one
line. An entry comes back with `vi_archive_restore` (with a reason, in its old mode). Deletion in the archive happens only
via the deletion paths for conversations and instances.
Order across the two files: write the target first, then change the source. A crash in between leaves
a duplicate that the next run overwrites, but no loss.
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

DAYS = {"erfahrung": 30, "schlaf": 90, "erkenntnis": 180, "regel": 180, "suche": 180, "skill": 180, "bild": 180}
DAYS_RAW = 30
KNOWLEDGE = ("erkenntnis", "regel", "suche", "skill", "bild")
STUB_CHARS = 200
#: Free share of the main file from which it is rewritten
VACUUM_FROM = 0.25
#: Edges to these targets protect an experience if they are evidence
EVIDENCE_TARGETS = ("erkenntnis:", "regel:", "suche:", "skill:", "selbst:")

_con = None  # sqlite3.Connection or db.PgConnection
_fpath: Path | None = None


def db():
    global _con, _fpath
    if g.archive_path is None:
        raise RuntimeError("memory not opened")
    if _con is None or _fpath != g.archive_path:
        if _con is not None:
            _con.close()
        from . import db as dbmod
        if dbmod.is_url(g.archive_path):  # 0.50.0: PostgreSQL — the archive is a schema of the same database
            _con = dbmod.connect(g.archive_path, schema=g.archive_schema)
        else:
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
    """Content to the archive, stub in memory."""
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
    o.change("vi", "moved to the long-term archive", reason)
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
    """Restore the full content and the old mode. Afterwards the entry counts as just used."""
    if not (reason or "").strip():
        raise ValueError("a reason is required")
    d = content(oid)
    o = g.load(oid)
    if not d or not o or o.mode != "archiviert":
        raise ValueError(f"{oid} is not in the long-term archive")
    o.text, o.data, o.hashtags, o.mode = d["text"], d["daten"], d["hashtags"], d["modus_vorher"]
    o.change(who, "restored from the long-term archive", reason)
    g.save(o)
    with g.lock:
        db().execute("DELETE FROM objekt WHERE id = ?", (oid,))
        db().commit()
    return o


def delete(oids: list[str]) -> None:
    """Part of deleting in memory: what is deleted must not survive in the archive."""
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
            outputs += [(r[0], f"housekeeping: {kind}, older than {DAYS[kind]} days, not used") for r in g.db().execute(sql, (kind, bound))]
        for kind in KNOWLEDGE:
            bound = _bound(DAYS[kind])
            outputs += [(r[0], f"housekeeping: {kind}, {DAYS[kind]} days neither recalled, changed nor shown") for r in g.db().execute(
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
    if g.backend() == "postgres":
        return False  # autovacuum reclaims space; a VACUUM FULL would lock the tables
    with g.lock:
        pages = g.db().execute("PRAGMA page_count").fetchone()[0]
        free = g.db().execute("PRAGMA freelist_count").fetchone()[0]
        if not pages or free / pages < VACUUM_FROM:
            return False
        g.db().commit()
        g.db().execute("VACUUM")
    return True


def cleanup() -> dict:
    """Sleep step 5."""
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
        log(f"Housekeeping: {n} entries and {r} raw transcripts moved to the long-term archive{', main file compacted' if v else ''}")
    return {"eingelagert": n, "je_art": counter, "rohverlaeufe": r, "verdichtet": v}


def hint(triggers: list[str]) -> list[str]:
    """One line for `vi_before` if archived knowledge fits the action."""
    if not triggers:
        return []
    hits = [o for _, o, _g in g.recall("(" + " OR ".join(triggers) + ") modus:archiviert", limit=3, kinds=KNOWLEDGE)]
    if not hits:
        return []
    return ["Matching in the long-term archive: " + "; ".join(f"[{o.id}] {o.text[:80]}" for o in hits) + " — vi_archive_restore(id, reason) brings an entry back"]


def progress() -> dict:
    with g.lock:
        n = db().execute("SELECT COUNT(*) FROM objekt").fetchone()[0]
        r = db().execute("SELECT COUNT(*) FROM gespraech_roh").fetchone()[0]
    if g.backend() == "postgres":
        size_of = "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() AND c.relkind = 'r'"
        with g.lock:
            return {"objekte": n, "rohverlaeufe": r, "lager_bytes": int(db().execute(size_of).fetchone()[0]), "aktiv_bytes": int(g.db().execute(size_of).fetchone()[0])}
    size = lambda p: os.path.getsize(p) if p and os.path.exists(p) else 0
    return {"objekte": n, "rohverlaeufe": r, "lager_bytes": size(g.archive_path), "aktiv_bytes": size(g.fpath_active) + size(f"{g.fpath_active}-wal")}


def line() -> str:
    s = progress()
    return f"{s['objekte']} entries, {s['rohverlaeufe']} raw transcripts, {s['lager_bytes'] // 1024} KB (active store {s['aktiv_bytes'] // 1024} KB)"
