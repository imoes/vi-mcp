"""The memory: every entry is an object (table objekt → class MemoryObject, mapping without ORM).

Fixed fields (id, art, zeit); changeable fields only via methods (tag, confirm, refute, link),
every change with reason and history. Every object carries hashtags kind:value; recall = filter language
`kind:value`, `!kind:value`, `(a OR b)`, prefix `kind:value*`, free text (FTS5).

Retrieval weighted by relevance + recency (decay) + importance — after Park et al. 2023
"Generative Agents" (arXiv 2304.03442). Objects with shared hashtags are linked (Zettelkasten, A-Mem).

One process, one connection: all accesses run under `lock` (threading.RLock). Because vi-mcp is the only
writer, this lock suffices — several processes on the same file are not intended (see
docs/ARCHITECTURE.md, "One process").
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
#: strittig = refuted by exactly one foreign instance (still appears, with a note); widerlegt = refuted by the author
#: or by ≥ 2 different instances (no longer appears)
#: archiviert = stub (text, hashtags) stays, content compressed in the archive; visible only with modus:archiviert in the filter
#: aufgegangen = skill was merged into another one (fusion); stays with a reference, no longer appears in searches
#: quarantaene = imported and not yet released; appears in no search and no hint
MODES = ("aktiv", "test", "aus", "defekt", "strittig", "widerlegt", "archiviert", "aufgegangen", "quarantaene")
#: Collective: who may read an object? privat = only the author instance (results may contain credentials),
#: geteilt = all instances. The loop (server) sees everything. Exhaustive for KINDS.
VISIBILITY_PER_KIND = {"erfahrung": "privat", "antwort": "privat", "erkenntnis": "geteilt", "regel": "geteilt", "reflex": "geteilt",
                "gespraech": "geteilt", "suche": "geteilt", "frage": "geteilt", "selbst": "geteilt", "schlaf": "geteilt", "modell": "geteilt", "skill": "geteilt", "bewertung": "privat"}
#: author of objects the server creates itself (loop) — a named instance, not NULL
SERVER_INSTANCE = "vi"
#: weight bonus per different FOREIGN instance that confirmed (self-confirmation does not count as evidence)
BONUS_PER_INSTANCE = 0.2
BONUS_MAX = 0.6
#: change history per object; older entries are trimmed and counted (daten.aenderungen_gekuerzt)
HISTORY_MAX = 50
DATA_MAX = 400_000
#: Recency by **power law** (Wixted & Ebbesen 1991; ACT-R: Anderson & Schooler 1991 — docs/FORSCHUNG.md A9):
#: recency = (1 + h)^(−DECAY_D), h = hours since the last access. Fast at first, slow afterwards:
#: 1 h 0.81 · 1 d 0.38 · 7 d 0.21 · 30 d 0.14 · 1 y 0.07. Up to 0.3.0 exponential 0.995^h (Park et al., there per
#: game hour) — that made anything older than 2 weeks practically vanish (30 d: 0.03). DECAY_D = 0.3 is a starting value.
DECAY_D = 0.3
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,30}:[^\s()]+$")
#: hashtags that are administration, not content (ignored for linking and drilldown)
ADMIN_PREFIXES = ("art:", "cache:", "ok:", "serial:", "tag:", "instanz:", "zustand:", "an:", "von:", "ueberraschung:",
              "modus:", "herkunft:", "konflikt:", "selbst:", "selbstbereich:", "modell:", "fusion:", "dublette:", "scorer:", "ziel:", "note:")

lock = threading.RLock()
_KINDS_CACHE: dict = {"t": float("-inf"), "kinds": frozenset()}
KINDS_TTL_S = 300
CONTENT_MAX = 200_000
_db: sqlite3.Connection | None = None
fts = False
#: active database and long-term archive (archive.py) — set by open_db()
fpath_active: Path | None = None
archive_path: Path | None = None

#: the conversation (serial number) on whose behalf work is being done — set per request thread
current_conversation: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelles_gespraech", default=None)
#: the instance on whose behalf reading/writing happens. None = the server itself (loop): sees everything.
current_instance: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelle_instanz", default=None)


def now() -> str:
    """ISO-8601 UTC with milliseconds: otherwise comparisons `zeit > since` (sleep, loop) do not separate what arose in the same
    second. Older entries (seconds, 0.1–0.3) sort correctly before them as text ('+' < '.')."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def hash_value(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def db() -> sqlite3.Connection:
    if _db is None:
        raise RuntimeError("memory not opened (open_db() missing)")
    return _db


def open_db(fpath: Path) -> None:
    """Open or create the database. File and companion files readable only by the owner (0600):
    the memory contains conversation histories and tool results, which may contain credentials."""
    global _db, fts, fpath_active, archive_path
    _KINDS_CACHE.update(t=float("-inf"), kinds=frozenset())  # another database: other kinds
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
        log(f"FTS5 not available ({exc}) — full text via LIKE")
    con.commit()
    with lock:
        if _db is not None:
            _db.close()
        _db = con
        fpath_active, archive_path = fpath, fpath.with_name(f"{fpath.stem}-lager.db")


def _migrate(con: sqlite3.Connection) -> None:
    """0.1.x → 0.2.0: add columns instanz/sicht (author from the hashtag instanz:, visibility from the kind);
    cache hashtag frage:<hash> → cache:<hash> (frage is now a kind)."""
    columns = {r[1] for r in con.execute("PRAGMA table_info(objekt)")}
    if "instanz" not in columns:
        con.execute("ALTER TABLE objekt ADD COLUMN instanz TEXT NOT NULL DEFAULT 'vi'")
        con.execute("UPDATE objekt SET instanz = COALESCE((SELECT substr(tag, 9) FROM tag WHERE objekt_id = objekt.id "
                    "AND tag LIKE 'instanz:%' LIMIT 1), 'vi')")
        log("migration: column instanz added")
    if "sicht" not in columns:
        con.execute("ALTER TABLE objekt ADD COLUMN sicht TEXT NOT NULL DEFAULT 'geteilt'")
        for kind, visibility in VISIBILITY_PER_KIND.items():
            con.execute("UPDATE objekt SET sicht = ? WHERE art = ?", (visibility, kind))
        log("migration: column sicht added")
    n = con.execute("UPDATE tag SET tag = 'cache:' || substr(tag, 7) WHERE tag LIKE 'frage:%'").rowcount
    if n:
        log(f"migration: {n} cache hashtags frage: → cache:")
    con.execute("CREATE INDEX IF NOT EXISTS objekt_instanz ON objekt(instanz, sicht)")
    # the table archiv (0.4–0.9) is replaced by the long-term archive; it is only dropped when empty
    if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'archiv'").fetchone():
        if con.execute("SELECT COUNT(*) FROM archiv").fetchone()[0] == 0:
            con.execute("DROP TABLE archiv")
        else:
            log("table archiv contains entries and is kept — please check")
    # flat view of observations (docs/TRAINING.md 4a): one source of truth (objekt/tag/daten), only read differently
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


#: Visibilities: privat (only the author instance), geteilt (all, also without a token in open-wiki mode, and the network),
#: intern (since 0.20.0: all instances with a token, never the tokenless instance and never the network — for company knowledge like Confluence).
VISIBILITIES = ("privat", "geteilt", "intern")
#: name of the tokenless instance in open-wiki mode (= config.OPEN; repeated here because config does not know this module).
OPEN_INSTANCE = "offen"


def visible_to(o: "Objekt", instance: str | None) -> bool:
    """May this instance read the object? None = the server itself."""
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
    """One memory entry. Fixed fields: id, kind, ts. Changeable only via methods (with history)."""
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
            raise ValueError("reason is required — every change needs a sufficient reason")

    def change(self, who: str, what: str, reason: str) -> None:
        self._require_reason(reason)
        all_ = self.changes + [{"zeit": now(), "wer": who, "was": what, "grund": reason.strip()[:300]}]
        if len(all_) > HISTORY_MAX:  # nothing vanishes silently: the trimming is counted and named in vi_object
            self.data["aenderungen_gekuerzt"] = self.data.get("aenderungen_gekuerzt", 0) + len(all_) - HISTORY_MAX
            all_ = all_[-HISTORY_MAX:]
        self.changes = all_
        self.last_at = now()

    def tag(self, add: list[str], remove: list[str], who: str, reason: str) -> "Objekt":
        self._require_reason(reason)
        for t in list(add) + list(remove):
            if not TAG.match(t):
                raise ValueError(f"hashtag {t!r} does not have the form kind:value")
            if t.startswith(("art:", "tool:", "instanz:", "herkunft:", "herausgeber:", "pruefer:", "modus:")):
                raise ValueError(f"{t}: fixed hashtag (instanz: is the author from the token; art:, tool:, herkunft:, herausgeber:, pruefer: and modus: are set by the system)")
        self.hashtags = sorted((set(self.hashtags) | set(add)) - set(remove))
        self.change(who, " ".join([f"+{t}" for t in add] + [f"-{t}" for t in remove]), reason)
        return save(self)

    def confirm(self, who: str, reason: str, instance: str | None = None, family: str | None = None, source: str | None = None) -> "Objekt":
        """Confirm. Counts per instance (daten.bestaetigt_von); weight bonus only for independent lines (0.33.0, see independent_lines)."""
        self._require_reason(reason)  # check first, then change — a rejection leaves the object unchanged
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("bestaetigt_von") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["bestaetigt_von"] = from_
        same_source = bool(source) and _norm_source(source) == _norm_source(self.data.get("quelle"))
        self.data["bestaetigungen"] = (list(self.data.get("bestaetigungen") or []) + [
            {"instanz": i, "familie": family or i, **({"quelle": source.strip()[:300]} if source else {}), "zeit": now()}])[-100:]
        self.confirmed += 1
        if self.mode == "strittig" and i != self.instance:
            self.mode = "aktiv"  # a foreign confirmation settles the dispute — with history
        note = (" (self-confirmation, no weight bonus)" if i == self.instance else
                " (same source as the object — not an independent line)" if same_source else "")
        self.change(who, "confirmed" + note, reason)
        return save(self)

    def refute(self, who: str, reason: str, instance: str | None = None, family: str | None = None) -> "Objekt":
        """Refute. The author itself or ≥ 2 different families → widerlegt (vanishes from searches); otherwise strittig (stays visible,
        with a note) — one family alone does not erase the knowledge of another (0.33.0: before, two instances, even of the same model)."""
        self._require_reason(reason)
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("widerlegt_von") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["widerlegt_von"] = from_
        self.data["widerlegungen"] = (list(self.data.get("widerlegungen") or []) + [{"instanz": i, "familie": family or i, "zeit": now()}])[-100:]
        self.refuted += 1
        self.mode = "widerlegt" if (i == self.instance or len(self._lines("widerlegungen", "widerlegt_von")) >= 2) else "strittig"
        self.change(who, self.mode, reason)
        return save(self)

    def _lines(self, entries_key: str, legacy_key: str, skip_same_source: bool = False) -> set[str]:
        """Families of foreign instances (author and server excluded). Entries before 0.33.0 have no family: each instance is its own."""
        own = (self.instance, SERVER_INSTANCE)
        src = _norm_source(self.data.get("quelle"))
        lines, covered = set(), set()
        for e in self.data.get(entries_key) or []:
            covered.add(e.get("instanz"))
            if e.get("instanz") in own or (skip_same_source and e.get("quelle") and _norm_source(e["quelle"]) == src):
                continue
            lines.add(e.get("familie") or e.get("instanz"))
        lines |= {i for i in (self.data.get(legacy_key) or {}) if i not in own and i not in covered}
        return lines

    def independent_lines(self) -> set[str]:
        """0.33.0 (Condorcet's independence condition): foreign confirmations grouped by model family; a confirmation citing the object's
        own source is no independent line (a common cause). What counts as one family is declared per instance (config "familie")."""
        return self._lines("bestaetigungen", "bestaetigt_von", skip_same_source=True)

    def foreign_confirmations(self) -> int:
        """Independent lines that confirmed (0.33.0; before: different foreign instances). The server (`vi`, sleep) never counts —
        an automatic confirmation must not raise the weight (no self-confirmation of the system)."""
        return len(self.independent_lines())

    def link(self, other_id: str, reason: str) -> None:
        with lock:
            for a, b in ((self.id, other_id), (other_id, self.id)):
                # evidence (grund "Beleg…") weighs more than an automatic edge and replaces it; never the other way round
                db().execute("INSERT INTO kante (a, b, grund, zeit) VALUES (?,?,?,?) ON CONFLICT (a, b) DO UPDATE SET grund = excluded.grund, "
                             "zeit = excluded.zeit WHERE excluded.grund LIKE 'Beleg%' AND kante.grund NOT LIKE 'Beleg%'", (a, b, reason[:200], now()))
            db().commit()

    def access(self) -> None:
        """Recalled means reinforced: the access counts, zuletzt moves forward (consolidation). Incremented relatively —
        no lost counter, even if another thread reads the same object at the same time."""
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
    """Data that is too large is replaced, named. Truncating the JSON text made the object unreadable."""
    js = json.dumps(o.data, ensure_ascii=False)
    if len(js) <= DATA_MAX:
        return js
    log(f"{o.id}: daten with {len(js)} chars over limit {DATA_MAX} — replaced")
    return json.dumps({"gekuerzt_zeichen": len(js), "grund": f"daten over {DATA_MAX} chars"})


def load_many(oids: list[str]) -> dict[str, MemoryObject]:
    """Several objects in two queries instead of two per object."""
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
    if _KINDS_CACHE["t"] != float("-inf"):  # cache loaded: a new kind counts at once, not only after KINDS_TTL_S
        new = {t.split(":", 1)[0] for t in tags} - _KINDS_CACHE["kinds"]
        if new:
            _KINDS_CACHE["kinds"] = _KINDS_CACHE["kinds"] | new
    return o


def delete(oids: list[str]) -> int:
    """Remove objects with hashtags, full text, edges and archive content — no dangling edges, no leftovers in the archive."""
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
        raise ValueError(f"art must be one of {', '.join(KINDS)}")
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValueError(f"sicht must be one of {', '.join(VISIBILITIES)}")
    for t in hashtags:
        if not TAG.match(t):
            raise ValueError(f"hashtag {t!r} does not have the form kind:value")
    # instanz: is not a free hashtag but the author (column instanz) — one thing, one place
    hashtags = [t for t in hashtags if not t.startswith("instanz:")]
    text, data = anonymize.without_secrets(text), anonymize.without_secrets(data)  # credentials are never stored
    ts = now()
    # random part: two equal actions in the same second are two objects, not one (otherwise INSERT OR REPLACE
    # silently overwrites the first — found by test_eingebaute_werkzeuge_nie_aus_gedaechtnis)
    o = MemoryObject(id=oid or f"{kind}:{hash_value(kind, text, ts, json.dumps(data or {}, sort_keys=True), secrets.token_hex(8))}", kind=kind, ts=ts,
               last_at=ts, text=text, data=data or {}, hashtags=list(hashtags), importance=max(0, min(3, importance)),
               mode=mode, conversation=conversation or current_conversation.get(),
               instance=instance or current_instance.get() or SERVER_INSTANCE, visibility=visibility or VISIBILITY_PER_KIND[kind],
               changes=[{"zeit": ts, "wer": who, "was": "created", "grund": (reason or "created")[:300]}])
    save(o)
    if mode != "quarantaene":  # unreviewed content gets no link to own knowledge
        link_similar(o)
    return o


# ── Recurring findings: one object per key (0.23.0) ─────────────────────────
# vi_learn(key=…): the same key from the same instance updates that object instead of adding a new one. Stored fields (English
# from the start): data.key, data.repeats (how often it was learned), data.history (earlier states, oldest first).
MERGED = "aufgegangen"  # stored mode value (German, existing): merged into another object, out of searches
KEY_MODES = ("aktiv", "test", "strittig")  # refuted, archived or merged objects are not continued — a new object starts
KEY_HISTORY_MAX = 200


def find_by_key(instance: str, key: str) -> MemoryObject | None:
    with lock:
        r = db().execute(f"SELECT id FROM objekt WHERE instanz = ? AND art = 'erkenntnis' AND modus IN ({','.join('?' * len(KEY_MODES))}) "
                         "AND json_extract(daten, '$.key') = ? ORDER BY zeit LIMIT 1", (instance, *KEY_MODES, key)).fetchone()
    return load(r[0]) if r else None


def _push_history(o: MemoryObject, entries: list[dict]) -> None:
    h = (o.data.get("history") or []) + entries
    if len(h) > KEY_HISTORY_MAX:  # nothing vanishes silently: the trimming is counted
        o.data["history_trimmed"] = o.data.get("history_trimmed", 0) + len(h) - KEY_HISTORY_MAX
        h = h[-KEY_HISTORY_MAX:]
    o.data["history"] = h


def _state(o: MemoryObject) -> dict:
    """The current state of an object as a history entry (text, source, content, time)."""
    return {"ts": o.last_at or o.ts, "text": o.text, **{k: o.data[k] for k in ("quelle", "inhalt", "ausgang") if k in o.data}}


def repeat(o: MemoryObject, text: str, hashtags: list[str], data: dict, importance: int, who: str) -> MemoryObject:
    """The same finding again: o keeps its id; its previous state goes into the history, the new text becomes the current one."""
    text, data = anonymize.without_secrets(text), anonymize.without_secrets(data)
    _push_history(o, [_state(o)])
    for k in ("quelle", "inhalt", "ausgang"):
        o.data.pop(k, None)
    o.data.update(data)
    o.data["repeats"] = int(o.data.get("repeats") or 1) + 1
    o.text = text
    o.hashtags = sorted(set(o.hashtags) | {t for t in hashtags if not t.startswith("instanz:")})
    o.importance = max(o.importance, max(0, min(3, importance)))
    o.change(who, f"repeated ({o.data['repeats']}×), earlier text in the history", "vi_learn with the same key")
    save(o)
    link_similar(o)
    return o


def _norm_source(s) -> str:
    """Source text compared loosely: case, surrounding space and trailing punctuation do not make a different source."""
    return str(s or "").strip().lower().rstrip(" .,;/")


#: 0.30.0: visibilities that may be switched afterwards. "privat" belongs to its instance and is never switched by anyone else.
SWITCHABLE_VISIBILITY = ("geteilt", "intern")


def set_visibility(o: "MemoryObject", new: str, who: str, reason: str) -> bool:
    """Switch an object between geteilt and intern, recorded with reason in its history. False if it already has that visibility.
    intern stops further sharing with the network; copies already published are recalled with vi_net_forget."""
    if new not in SWITCHABLE_VISIBILITY:
        raise ValueError(f"visibility {new!r}: only shared or internal can be set")
    if o.visibility not in SWITCHABLE_VISIBILITY:
        raise ValueError(f"{o.id} is {o.visibility} — a private object stays with its instance")
    if o.visibility == new:
        return False
    o.change(who, f"visibility {o.visibility} → {new}", reason)
    o.visibility = new
    save(o)
    return True


def merge_by_key(instance: str, key_of, who: str, reason: str, apply: bool = False) -> dict:
    """One-time clean-up: group the insights of `instance` by key_of(text) (None = no key) and merge each group into its oldest object.
    The oldest keeps its id and gets the newest text; all earlier states go into its history; the others get mode MERGED
    with a reference (data.merged_into) and drop out of searches — nothing is deleted. apply=False only counts."""
    with lock:
        rows = db().execute(f"SELECT id, text FROM objekt WHERE instanz = ? AND art = 'erkenntnis' AND modus IN ({','.join('?' * len(KEY_MODES))}) "
                            "ORDER BY zeit, id", (instance, *KEY_MODES)).fetchall()
    groups: dict[str, list[str]] = {}
    for oid, text in rows:
        k = key_of(text)
        if k:
            groups.setdefault(k, []).append(oid)
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    report = {"objects": len(rows), "with_key": sum(len(v) for v in groups.values()), "keys": len(groups),
              "keys_repeated": len(multi), "merged": sum(len(v) - 1 for v in multi.values()), "applied": apply}
    if not apply:
        return report
    for k, ids in multi.items():
        objs = [load(i) for i in ids]
        main, rest = objs[0], objs[1:]
        newest = rest[-1]
        main.data["key"] = k
        _push_history(main, [_state(x) for x in objs[:-1]])  # every state except the newest, oldest first
        for f in ("quelle", "inhalt", "ausgang"):
            main.data.pop(f, None)
            if f in newest.data:
                main.data[f] = newest.data[f]
        main.text = newest.text
        main.data["repeats"] = int(main.data.get("repeats") or 1) + len(rest)
        main.hashtags = sorted(set().union(*[set(x.hashtags) for x in objs]) - {f"modus:{x.mode}" for x in objs})
        main.importance = max(x.importance for x in objs)
        main.accesses = sum(x.accesses for x in objs)
        main.confirmed = sum(x.confirmed for x in objs)
        main.change(who, f"merged {len(rest)} repetitions with the same key: {', '.join(x.id for x in rest)}"[:300], reason)
        save(main)
        for x in rest:
            x.mode = MERGED
            x.data["merged_into"] = main.id
            x.hashtags = [t for t in x.hashtags if not t.startswith("modus:")] + [f"modus:{MERGED}"]
            x.change(who, f"merged into {main.id}", reason)
            save(x)
            x.link(main.id, "merged into (same key)")
    return report


def link_similar(o: MemoryObject, at_least: int = 2, limit: int = 5) -> None:
    """Zettelkasten: objects sharing ≥ `at_least` content hashtags are linked (A-Mem idea)."""
    content = [t for t in o.hashtags if not t.startswith(ADMIN_PREFIXES)]  # otherwise instanz:/art: would link everything with everything
    if len(content) < at_least or o.kind in ("antwort",):
        return
    with lock:
        rows = db().execute(
            f"SELECT objekt_id, COUNT(*) n FROM tag WHERE tag IN ({','.join('?' * len(content))}) AND objekt_id <> ? "
            f"GROUP BY objekt_id HAVING n >= ? ORDER BY n DESC LIMIT ?", (*content, o.id, at_least, limit)).fetchall()
    for oid, n in rows:
        o.link(oid, f"{n} shared hashtags")


# ── Recall: filter language + weighting ──────────────────────────────────────



def known_kinds() -> frozenset[str]:
    """Hashtag kinds that occur in the memory (cached KINDS_TTL_S)."""
    import time as _t
    if _t.monotonic() - _KINDS_CACHE["t"] > KINDS_TTL_S:
        with lock:
            rows = db().execute("SELECT DISTINCT substr(tag, 1, instr(tag, ':') - 1) FROM tag").fetchall()
        _KINDS_CACHE.update(t=_t.monotonic(), kinds=frozenset(r[0] for r in rows if r[0]))
    return _KINDS_CACHE["kinds"]


def as_text_tokens(text: str, kinds: frozenset[str] | None = None) -> list[str]:
    """0.26.0: words with a colon that are no hashtag condition (wrong form or unknown kind) — searched as free text, named in answers."""
    kinds = known_kinds() if kinds is None else kinds
    out = []
    for m in re.finditer(r"\(([^()]*)\)|(!?\S+)", text or ""):
        tok = m.group(2)
        if tok and ":" in tok and not tok.startswith("!") and not _is_condition(tok, kinds):
            out.append(tok)
    return out


def _is_condition(tok: str, kinds: frozenset[str] | None) -> bool:
    return bool(TAG.match(tok)) and (kinds is None or tok.split(":", 1)[0] in kinds)


def parse_filter(text: str, kinds: frozenset[str] | None = None) -> tuple[list[list[str]], list[str], list[str]]:
    """Filter text → (AND groups of OR tags, exclusion tags, free words). `(a OR b) c !d word`. Pure when `kinds` is given or None.
    0.26.0: a word with a colon is a hashtag condition only in the form kind:value (TAG) and, if `kinds` is given, with a kind that occurs
    in the memory — otherwise it is free text. Before, "Hosts: 62.153.216.33" in a question emptied the whole search silently (reported by
    the AIKB benchmark session, 10.11.2026)."""
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
        elif ":" in tok and _is_condition(tok, kinds):
            groups.append([tok])
        else:
            words.append(tok)
    return groups, remove, words


def _tag_condition(tag: str) -> tuple[str, tuple]:
    return ("tag LIKE ?", (tag[:-1] + "%",)) if tag.endswith("*") else ("tag = ?", (tag,))


def _filter_sql(groups: list, remove: list, viewer: str | None) -> tuple[str, list]:
    """SQL for mode, visibility and hashtag conditions (without free text) — one source for recall() and ids_for_filter()."""
    sql, par = "SELECT id FROM objekt WHERE modus <> 'widerlegt'", []
    if not any("modus:quarantaene" in grp for grp in groups):
        sql += " AND modus <> 'quarantaene'"  # only via vi_quarantine
    if not any("modus:aufgegangen" in grp for grp in groups):
        sql += " AND modus <> 'aufgegangen'"  # merged skills only on request (reference is in the object)
    if not any("modus:archiviert" in grp for grp in groups):
        sql += " AND modus <> 'archiviert'"  # archived objects only on explicit request
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
    """All visible ids for the filter's hashtag conditions, without an upper limit (candidates of the semantic search)."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    groups, remove, _w = parse_filter(filter_text, known_kinds())
    if kinds:
        groups.append([f"art:{a}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer)
    with lock:
        return [r[0] for r in db().execute(sql, par)]


#: How the last word search in this context ran: "und" (all words), "oder" (fallback, because too few contained all words) or None.
word_search: contextvars.ContextVar[str | None] = contextvars.ContextVar("wortsuche", default=None)


def recall(filter_text: str, limit: int = 10, kinds: tuple[str, ...] = (), viewer: str | None = "aktuell",
             or_fallback: bool = False) -> list[tuple[float, MemoryObject, dict]]:
    """Objects for the filter, weighted: relevance (tag/word hits) + recency + importance (Park et al. 2023)
    + bonus per foreign confirming instance. Visible is what is shared or belongs to the viewer
    (viewer "aktuell" = instance of the running request; None = server, sees everything).
    Free text requires all words (AND). or_fallback=True: if fewer than `limit` objects contain all words, the result is
    filled up with an OR search (BM25 ranks objects with more words first); `word_search` then says which one ran."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    groups, remove, words = parse_filter(filter_text, known_kinds())
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
                        # objects with all words stay in front: their rank is lifted above the highest OR rank
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
    """The most frequent content hashtag of the hits that is not already in the filter (drilldown step). Pure."""
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
    """Drilldown: search, add the most salient hashtag, search again — until nothing new comes."""
    levels_off, filt = [], (filter_text or "").strip()
    for _ in range(max(1, levels)):
        hits = [o for _, o, _g in recall(filt, limit=limit * 4)]
        next_try = most_salient_hashtag(hits, filt)
        levels_off.append({"filter": filt, "gesamt": len(hits), "treffer": hits[:limit], "naechster": next_try})
        if not next_try or len(hits) <= 1:
            break
        filt = f"{filt} {next_try}".strip()
    return levels_off
