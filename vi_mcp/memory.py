"""The memory: every entry is an object (table object → class MemoryObject, mapping without ORM).

Fixed fields (id, kind, ts); changeable fields only via methods (tag, confirm, refute, link),
every change with reason and history. Every object carries hashtags kind:value; recall = filter language
`kind:value`, `!kind:value`, `(a OR b)`, prefix `kind:value*`, free text (FTS5).

Retrieval weighted by relevance + recency (decay) + importance — after Park et al. 2023
"Generative Agents" (arXiv 2304.03442). Objects with shared hashtags are linked (Zettelkasten, A-Mem).

One process, one connection: all accesses run under `lock` (threading.RLock). Because vi-mcp is the only
writer, this lock suffices — several processes on the same file are not intended (see
docs/ARCHITECTURE.md, "One process").
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import math
import os
import queue
import re
import secrets
import sqlite3
from typing import Any
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clingo_object.filters import parse_filter as _parse_filter

from . import anonymize, names
from .log_output import log

KINDS = ("experience", "answer", "insight", "rule", "reflex", "conversation", "search", "question", "self", "sleep", "model", "skill", "rating", "image", "page",
         "proposal", "machine")  # private virtual-machine state and snapshots
#: strittig = refuted by exactly one foreign instance (still appears, with a note); widerlegt = refuted by ≥ 2 independent foreign
#: lines (model families; no longer appears); zurueckgezogen = withdrawn by its author (no longer appears). 0.67.0: withdrawn and refuted
#: are two things — an author who takes a statement back removes the claim, it does not prove the opposite (kollektiv P13; before,
#: both were called widerlegt, and 16 of 17 refuted objects on production were in fact withdrawn by their author).
#: archiviert = stub (text, hashtags) stays, content compressed in the archive; visible only with modus:archiviert in the filter
#: aufgegangen = skill was merged into another one (fusion); stays with a reference, no longer appears in searches
#: quarantaene = imported and not yet released; appears in no search and no hint
MODES = ("active", "test", "off", "broken", "disputed", "refuted", "withdrawn", "archived", "merged", "quarantine")
#: modes that no longer appear in searches, hints and exports: one definition, used by every filter
GONE = ("refuted", "withdrawn")
GONE_SQL = "(" + ", ".join(f"'{m}'" for m in GONE) + ")"
#: Collective: who may read an object? privat = only the author instance (results may contain credentials),
#: geteilt = all instances. The loop (server) sees everything. Exhaustive for KINDS.
VISIBILITY_PER_KIND = {"experience": "private", "answer": "private", "insight": "shared", "rule": "shared", "reflex": "shared",
                "conversation": "shared", "search": "shared", "question": "shared", "self": "shared", "sleep": "shared", "model": "shared", "skill": "shared", "rating": "private", "image": "shared", "page": "shared", "proposal": "internal", "machine": "private"}
#: author of objects the server creates itself (loop) — a named instance, not NULL
SERVER_INSTANCE = "vi"
#: weight bonus per confirming line (0.69.3: one line per instance; the author's own instance counts SELF_WEIGHT, the server never)
BONUS_PER_INSTANCE = 0.2
BONUS_MAX = 0.6
#: 0.69.3 (the user's decision, 17.11.2026: "in our environment there is only Claude, so the AI must be able to check its own work"):
#: an instance's review of its own object counts, marked "self", at half the weight of another instance's
SELF_WEIGHT = 0.5
#: change history per object; older entries are trimmed and counted (daten.aenderungen_gekuerzt)
HISTORY_MAX = 50
DATA_MAX = 400_000
#: Recency by **power law** (Wixted & Ebbesen 1991; ACT-R: Anderson & Schooler 1991 — docs/FORSCHUNG.md A9):
#: recency = (1 + h)^(−DECAY_D), h = hours since the last access. Fast at first, slow afterwards:
#: 1 h 0.81 · 1 d 0.38 · 7 d 0.21 · 30 d 0.14 · 1 y 0.07. Up to 0.3.0 exponential 0.995^h (Park et al., there per
#: game hour) — that made anything older than 2 weeks practically vanish (30 d: 0.03). DECAY_D = 0.3 is a starting value.
DECAY_D = 0.3
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,30}:[^\s()]+$")
#: hashtags only the system sets (instanz: comes from the token) — Objekt.tag refuses them, so do logic proposals (0.63.0)
FIXED_TAG_PREFIXES = ("kind:", "tool:", "instance:", "origin:", "publisher:", "reviewer:", "mode:")
#: hashtags that are administration, not content (ignored for linking and drilldown)
ADMIN_PREFIXES = ("kind:", "cache:", "ok:", "serial:", "tag:", "instance:", "state:", "to:", "from:", "surprise:",
              "mode:", "origin:", "conflict:", "self:", "self_area:", "model:", "fusion:", "duplicate:", "scorer:", "target:", "grade:")

lock = threading.RLock()
_KINDS_CACHE: dict = {"t": float("-inf"), "kinds": frozenset()}
KINDS_TTL_S = 300
CONTENT_MAX = 200_000
_db: Any = None  # sqlite3.Connection, or db.PgConnection for a postgresql:// URL (0.50.0)
fts = False
#: active database and long-term archive (archive.py) — set by open_db(). For PostgreSQL: the URL, and the archive lives in the
#: schema archive_schema of the same database.
fpath_active: Path | str | None = None
archive_path: Path | str | None = None
archive_schema: str | None = None

#: the conversation (serial number) on whose behalf work is being done — set per request thread
current_conversation: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelles_gespraech", default=None)
#: the instance on whose behalf reading/writing happens. None = the server itself (loop): sees everything.
current_instance: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktuelle_instanz", default=None)


_now_last = [""]
_now_lock = threading.Lock()


def now() -> str:
    """ISO-8601 UTC with milliseconds: otherwise comparisons `zeit > since` (sleep, loop) do not separate what arose in the same
    second. Older entries (seconds, 0.1–0.3) sort correctly before them as text ('+' < '.').
    0.69.9: strictly increasing within the process — two calls in the same millisecond (a bulk import, a fast interpreter) got the
    same value, and "the newest" (ORDER BY ts, id) was decided by the random id. Measured on Python 3.14 (17.11.2026): test_dedup and
    test_hints failed depending on the order of the run (issue #3). A tie moves the later call 1 ms on; the clock going back (NTP)
    keeps the order instead of jumping back."""
    t = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with _now_lock:
        if t <= _now_last[0]:
            t = (datetime.fromisoformat(_now_last[0]) + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")
        _now_last[0] = t
    return t


def hash_value(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def db() -> Any:
    if _db is None:
        raise RuntimeError("memory not opened (open_db() missing)")
    return _db


#: 24.11.2026: read connections beside the one writing connection (SQLite, WAL). Under session churn every read waited for the global
#: lock while one ran (production 0.71.1: 180 threads); SQLite releases the GIL while it works, so reads on their own connections run
#: side by side and beside the writer. Measured on a production copy: 92 % of a hybrid vi_recall is SQLite time.
READERS = 4
_readers: queue.Queue | None = None


@contextlib.contextmanager
def reading():
    """A connection for a read of committed state. SQLite: one of READERS read connections (query_only), outside the global lock.
    The one connection under the lock, as before, when there is no pool (PostgreSQL, tests that never opened one) or when the writing
    connection holds an uncommitted change — a read must never miss what its own flow has written and not committed yet."""
    pool = _readers
    if pool is None or (_db is not None and _db.in_transaction):
        with lock:
            yield db()
        return
    con = pool.get()
    try:
        yield _Reader(con)
    finally:
        pool.put(con)


class _Rows:
    """A finished result: every row read, the statement closed. A statement left open (fetchone() on a pooled connection) keeps
    SQLite's read snapshot open, and every later read on that connection would see the old state."""

    def __init__(self, cur):
        try:
            self._rows = cur.fetchall()
        finally:
            cur.close()
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        out, self._i = self._rows[self._i:], len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


class _Reader:
    def __init__(self, con):
        self._con = con

    def execute(self, sql: str, params=()):
        return _Rows(self._con.execute(sql, params))


def _open_readers(fpath) -> queue.Queue:
    pool: queue.Queue = queue.Queue()
    for _ in range(READERS):
        r = sqlite3.connect(str(fpath), check_same_thread=False, timeout=30)
        r.execute("PRAGMA busy_timeout=30000")
        r.execute("PRAGMA query_only=ON")
        pool.put(r)
    return pool


def _close_readers() -> None:
    global _readers
    pool, _readers = _readers, None
    while pool is not None and not pool.empty():
        pool.get_nowait().close()


def open_db(fpath: Path | str) -> None:
    """Open or create the database. A file path: SQLite, file and companion files readable only by the owner (0600):
    the memory contains conversation histories and tool results, which may contain credentials.
    A postgresql:// URL (0.50.0, optional, psycopg 3): the tables in the URL's schema (search_path, default public), the long-term
    archive in the schema <schema>_lager of the same database (vi_mcp/db.py translates the SQLite SQL)."""
    global _db, _readers, fts, fpath_active, archive_path, archive_schema
    from . import db as dbmod
    _known_indexes.clear()  # 0.61.0: another database, other indexes
    from . import index
    index.forget()  # 24.11.2026: and another memory index
    _KINDS_CACHE.update(t=float("-inf"), kinds=frozenset())  # another database: other kinds
    _EXPLICIT_CACHE.update(t=float("-inf"), v={})  # 0.70.4: another database, other index scopes (a stale one leaked across)
    if dbmod.is_url(fpath):
        con = dbmod.connect(str(fpath))
        target, archive_target, archive_schema_ = str(fpath), str(fpath), f"{con.schema}_lager"
    else:
        fpath = Path(fpath)
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
        target, archive_target, archive_schema_ = fpath, fpath.with_name(f"{fpath.stem}-lager.db"), None
    names.migrate_db(con, names.TABLES, target, "memory")  # 0.67.0: a database of 0.66 or older gets its English names first
    con.commit()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS object (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, ts TEXT NOT NULL, last_at TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}', importance INTEGER NOT NULL DEFAULT 1,
            confirmed INTEGER NOT NULL DEFAULT 0, refuted INTEGER NOT NULL DEFAULT 0, accesses INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'active', changes TEXT NOT NULL DEFAULT '[]', conversation TEXT,
            instance TEXT NOT NULL DEFAULT 'vi', visibility TEXT NOT NULL DEFAULT 'shared', idx TEXT NOT NULL DEFAULT 'global');
        CREATE INDEX IF NOT EXISTS object_kind_ts ON object(kind, ts);
        CREATE TABLE IF NOT EXISTS tag (object_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (object_id, tag));
        CREATE INDEX IF NOT EXISTS tag_tag ON tag(tag);
        CREATE TABLE IF NOT EXISTS edge (a TEXT NOT NULL, b TEXT NOT NULL, reason TEXT NOT NULL, ts TEXT NOT NULL,
            PRIMARY KEY (a, b));
        CREATE TABLE IF NOT EXISTS conversation_raw (serial TEXT PRIMARY KEY, raw BLOB NOT NULL, length INTEGER NOT NULL);
    """)
    _migrate(con)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS object_fts USING fts5(id UNINDEXED, text)")
        fts = True
    except sqlite3.OperationalError as exc:
        fts = False
        log(f"FTS5 not available ({exc}) — full text via LIKE")
    con.commit()
    with lock:
        if _db is not None:
            _db.close()
        _close_readers()
        _db = con
        fpath_active, archive_path, archive_schema = target, archive_target, archive_schema_
        if not dbmod.is_url(fpath) and READERS > 0:  # READERS = 0: no pool, every read under the lock as before 24.11.2026
            _readers = _open_readers(fpath)


def backend() -> str:
    """'sqlite' or 'postgres' — for the few places that differ (full-text query, sizes, VACUUM)."""
    from . import db as dbmod
    return dbmod.backend(_db)


def refuted_mode(author: str, mode: str, data: dict, latest: str | None = None) -> str:
    """The mode after a refutation (one definition for refute() and the migration): ≥ 2 foreign instances → refuted; the author
    refuted (now or before) → withdrawn; else disputed. Lines as in MemoryObject._line_weights (0.69.3: per instance, before per
    model family — in an environment with one model family no object could ever be refuted; author and server excluded)."""
    own = (author, SERVER_INSTANCE)
    entries = data.get("refutations") or []
    covered = {e.get("instance") for e in entries}
    lines = {e.get("instance") for e in entries if e.get("instance") not in own}
    lines |= {i for i in (data.get("refuted_by") or {}) if i not in own and i not in covered}
    if len(lines) >= 2:
        return "refuted"
    if latest == author or mode == "withdrawn" or author in (data.get("refuted_by") or {}):
        return "withdrawn"
    return "disputed"


def _migrate(con: Any) -> None:
    """0.1.x → 0.2.0: add columns instance/visibility (author from the hashtag instance:, visibility from the kind). The cache hashtag
    frage:<hash> of 0.1 becomes cache:<hash> in the migration of 0.67.0 (names.migrate_tags), before any kind is translated."""
    columns = {r[1] for r in con.execute("PRAGMA table_info(object)")}
    if "instance" not in columns:
        con.execute("ALTER TABLE object ADD COLUMN instance TEXT NOT NULL DEFAULT 'vi'")
        con.execute("UPDATE object SET instance = COALESCE((SELECT substr(tag, 10) FROM tag WHERE object_id = object.id "
                    "AND tag LIKE 'instance:%' LIMIT 1), 'vi')")  # 10 = len("instance:") + 1 (0.67.0: the hashtag kind is English)
        log("migration: column instanz added")
    if "visibility" not in columns:
        con.execute("ALTER TABLE object ADD COLUMN visibility TEXT NOT NULL DEFAULT 'shared'")
        for kind, visibility in VISIBILITY_PER_KIND.items():
            con.execute("UPDATE object SET visibility = ? WHERE kind = ?", (visibility, kind))
        log("migration: column sicht added")
    con.execute("CREATE INDEX IF NOT EXISTS object_instance ON object(instance, visibility)")
    if "idx" not in columns:  # 0.61.0: the index of an object (vi_mcp/indexes.py); everything before is global
        con.execute("ALTER TABLE object ADD COLUMN idx TEXT NOT NULL DEFAULT 'global'")
        log("migration: column idx added (every object in index global)")
    con.execute("CREATE INDEX IF NOT EXISTS object_idx ON object(idx, kind)")
    # 0.61.0: the indexes themselves — name as primary key, with kind, description and tags (the user: "jeden Index auch Tags und
    # Beschreibung mitgeben, wenn sie in einer Tabelle stehen"). objekt.idx refers to it; an added column cannot become a real foreign key
    # in SQLite without rebuilding the table, so the reference is kept by the code (indexes.ensure) and checked by a test.
    con.execute("CREATE TABLE IF NOT EXISTS vi_index (name TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'project', "
                "description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL, "
                "source TEXT NOT NULL DEFAULT 'automatic')")
    if "explicit" not in {r[1] for r in con.execute("PRAGMA table_info(vi_index)")}:  # 0.70.3: searched only when named
        con.execute("ALTER TABLE vi_index ADD COLUMN explicit INTEGER NOT NULL DEFAULT 0")
        log("migration: column vi_index.explicit added (every index searched by default, as before)")
    con.execute("INSERT OR IGNORE INTO vi_index (name, kind, description, created, source) VALUES "
                "('global', 'global', 'shared knowledge of all projects', ?, 'system')", (now(),))
    # kind and source named: a database migrated from 0.66 keeps the German column defaults 'projekt' / 'automatisch' (24.11.2026)
    con.execute("INSERT OR IGNORE INTO vi_index (name, kind, created, source) SELECT DISTINCT idx, 'project', ?, 'automatic' FROM object "
                "WHERE idx <> 'global'", (now(),))
    # 0.37.0: an image is its own kind (bild); 0.35.x stored it as an insight with medium:bild. The id stays (edges, history, hints
    # refer to it); kind, art: hashtag and the now redundant medium:bild change.
    old = [r[0] for r in con.execute("SELECT id FROM object WHERE kind = 'insight' AND json_extract(data, '$.image') IS NOT NULL")]
    for oid in old:
        con.execute("UPDATE object SET kind = 'image' WHERE id = ?", (oid,))
        con.execute("DELETE FROM tag WHERE object_id = ? AND tag IN ('kind:insight', 'medium:bild')", (oid,))
        con.execute("INSERT OR IGNORE INTO tag (object_id, tag) VALUES (?, 'kind:image')", (oid,))
    if old:
        log(f"migration: {len(old)} image(s) from kind erkenntnis to kind bild (ids kept)")
    # 0.67.0: widerlegt split in two — an object its author refuted, without two foreign families, was withdrawn, not refuted; so
    # was an object of the server that the server itself discarded without any refutation record (sleep: a skill without content).
    # A quarantine discard (p2p.discard: a reviewer rejects foreign knowledge) keeps widerlegt.
    # Idempotent (only widerlegt rows are read); the history names the migration.
    moved = 0
    for oid, author, raw, hist in con.execute("SELECT id, instance, data, changes FROM object WHERE mode = 'refuted'").fetchall():
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            continue
        by_server = author == SERVER_INSTANCE and not (data.get("refuted_by") or {})  # the server discarded its own (sleep: empty skill)
        if not by_server and (author not in (data.get("refuted_by") or {}) or refuted_mode(author, "refuted", data) != "withdrawn"):
            continue
        changes = json.loads(hist or "[]") + [{"ts": now(), "who": "vi", "what": "withdrawn",
                                              "reason": "0.67.0: refuted only by its author — a withdrawal, not a refutation (kollektiv P13)"}]
        con.execute("UPDATE object SET mode = 'withdrawn', changes = ? WHERE id = ?", (json.dumps(changes, ensure_ascii=False), oid))
        moved += 1
    if moved:
        log(f"migration: {moved} object(s) widerlegt → zurueckgezogen (refuted only by their author)")
    # the table archiv (0.4–0.9) is replaced by the long-term archive; it is only dropped when empty
    if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'archiv'").fetchone():
        if con.execute("SELECT COUNT(*) FROM archiv").fetchone()[0] == 0:
            con.execute("DROP TABLE archiv")
        else:
            log("table archiv contains entries and is kept — please check")
    # flat view of observations (docs/TRAINING.md 4a): one source of truth (objekt/tag/daten), only read differently
    con.execute("DROP VIEW IF EXISTS beobachtung")  # the name up to 0.66; 0.67.0: observation, with English column names
    con.execute("DROP VIEW IF EXISTS observation")
    con.execute("""CREATE VIEW observation AS
        SELECT o.id AS experience_id, o.ts, o.instance,
               (SELECT substr(tag, 6) FROM tag WHERE object_id = o.id AND tag LIKE 'tool:%') AS tool,
               CASE WHEN EXISTS (SELECT 1 FROM tag WHERE object_id = o.id AND tag = 'ok:yes') THEN 1
                    WHEN EXISTS (SELECT 1 FROM tag WHERE object_id = o.id AND tag = 'ok:no') THEN 0 END AS ok,
               json_array_length(COALESCE(json_extract(o.data, '$.before.shown'), json_extract(o.data, '$.before.found'), '[]')) AS hint_n,
               json_extract(o.data, '$.surprise.level') AS surprise,
               json_extract(o.data, '$.before.router') AS router,
               json_extract(o.data, '$.before.exploration') AS exploration,
               json_extract(o.data, '$.before.triggers') AS triggers_json,
               json_extract(o.data, '$.before.shown') AS shown_json,
               json_extract(o.data, '$.before.candidates') AS candidates_json,
               json_extract(o.data, '$.before.from_memory') AS from_memory
        FROM object o WHERE o.kind = 'experience'""")
    con.commit()


#: Visibilities: privat (only the author instance), geteilt (all, also without a token in open-wiki mode, and every network),
#: intern (since 0.20.0: all instances with a token, never the tokenless instance — for company knowledge like Confluence; since 0.39.0 a
#: company network (art firma) carries it to its members, an open network never).
VISIBILITIES = ("private", "shared", "internal")
#: name of the tokenless instance in open-wiki mode (= config.OPEN; repeated here because config does not know this module).
OPEN_INSTANCE = "offen"


def visible_to(o: "Objekt", instance: str | None) -> bool:
    """May this instance read the object? None = the server itself."""
    return (instance is None or o.visibility == "shared" or o.instance == instance
            or (o.visibility == "internal" and instance != OPEN_INSTANCE))


def close_db() -> None:
    global _db
    from . import archive
    archive.close_db()
    with lock:
        _close_readers()
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
    mode: str = "active"
    changes: list = field(default_factory=list)
    conversation: str | None = None
    instance: str = SERVER_INSTANCE
    visibility: str = "shared"
    idx: str = "global"  # 0.61.0: the index (vi_mcp/indexes.py)

    @staticmethod
    def _require_reason(reason: str) -> None:
        if not (reason or "").strip():
            raise ValueError("reason is required — every change needs a sufficient reason")

    def change(self, who: str, what: str, reason: str) -> None:
        self._require_reason(reason)
        all_ = self.changes + [{"ts": now(), "who": who, "what": what, "reason": reason.strip()[:300]}]
        if len(all_) > HISTORY_MAX:  # nothing vanishes silently: the trimming is counted and named in vi_object
            self.data["changes_trimmed"] = self.data.get("changes_trimmed", 0) + len(all_) - HISTORY_MAX
            all_ = all_[-HISTORY_MAX:]
        self.changes = all_
        self.last_at = now()

    def tag(self, add: list[str], remove: list[str], who: str, reason: str) -> "Objekt":
        self._require_reason(reason)
        add, remove = [names.canonical_tag(t) for t in add], [names.canonical_tag(t) for t in remove]  # 0.67.0: German kinds of older callers
        for t in list(add) + list(remove):
            if not TAG.match(t):
                raise ValueError(f"hashtag {t!r} does not have the form kind:value")
            if t.startswith(FIXED_TAG_PREFIXES):
                raise ValueError(f"{t}: fixed hashtag (instance: is the author from the token; art:, tool:, herkunft:, herausgeber:, reviewer: and mode: are set by the system)")
        self.hashtags = sorted((set(self.hashtags) | set(add)) - set(remove))
        self.change(who, " ".join([f"+{t}" for t in add] + [f"-{t}" for t in remove]), reason)
        return save(self)

    def confirm(self, who: str, reason: str, instance: str | None = None, family: str | None = None, source: str | None = None) -> "Objekt":
        """Confirm. Counts per instance (data.confirmed_by); the weight comes from the lines (see _line_weights): another instance 1,
        the author's own instance SELF_WEIGHT as a self-review (0.69.3; before: none), the object's own source none."""
        self._require_reason(reason)  # check first, then change — a rejection leaves the object unchanged
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("confirmed_by") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["confirmed_by"] = from_
        same_source = bool(source) and _norm_source(source) == _norm_source(self.data.get("source"))
        self.data["confirmations"] = (list(self.data.get("confirmations") or []) + [
            {"instance": i, "family": family or i, **({"source": source.strip()[:300]} if source else {}), "ts": now()}])[-100:]
        self.confirmed += 1
        if self.mode == "disputed" and i != self.instance:
            self.mode = "active"  # a foreign confirmation settles the dispute — with history
        note = (" (same source as the object — not an independent line)" if same_source else
                f" (self-review, weight {SELF_WEIGHT})" if i == self.instance else
                " (by the server — no weight)" if i == SERVER_INSTANCE else "")
        self.change(who, "confirmed" + note, reason)
        return save(self)

    def refute(self, who: str, reason: str, instance: str | None = None, family: str | None = None) -> "Objekt":
        """Refute. ≥ 2 different foreign instances → refuted; the author itself → withdrawn (the claim is taken back, the opposite is not
        proven — 0.67.0, before both were refuted); both vanish from searches. Otherwise disputed (stays visible, with a note) — one
        instance alone does not erase the knowledge of another. 0.69.3: lines per instance, from 0.33.0 to 0.69.2 per model family.
        A withdrawn object stays withdrawn when one foreign instance refutes it too; two foreign instances make it refuted."""
        self._require_reason(reason)
        i = instance or SERVER_INSTANCE
        from_ = dict(self.data.get("refuted_by") or {})
        from_[i] = from_.get(i, 0) + 1
        self.data["refuted_by"] = from_
        self.data["refutations"] = (list(self.data.get("refutations") or []) + [{"instance": i, "family": family or i, "ts": now()}])[-100:]
        self.refuted += 1
        self.mode = refuted_mode(self.instance, self.mode, self.data, latest=i)
        self.change(who, self.mode, reason)
        return save(self)

    def _line_weights(self, entries_key: str, legacy_key: str, skip_same_source: bool = False) -> dict[str, float]:
        """{instance: weight} of the lines behind confirmations or refutations. 0.69.3: one line per instance (before 0.69.3 one per
        model family — with only Claude in use every confirmation was the same line). Another instance weighs 1, the author's own
        instance SELF_WEIGHT (a self-review, marked "self"), the server (`vi`, sleep) nothing — an automatic confirmation must not raise
        the weight. A confirmation citing the object's own source is no line (a common cause, Condorcet's independence condition)."""
        src = _norm_source(self.data.get("source"))
        w, covered = {}, set()
        for e in self.data.get(entries_key) or []:
            i = e.get("instance")
            covered.add(i)
            if i == SERVER_INSTANCE or (skip_same_source and e.get("source") and _norm_source(e["source"]) == src):
                continue
            w[i] = SELF_WEIGHT if i == self.instance else 1.0
        for i in self.data.get(legacy_key) or {}:  # stored before 0.33.0: no entry, the instance alone
            if i not in covered and i != SERVER_INSTANCE:
                w[i] = SELF_WEIGHT if i == self.instance else 1.0
        return w

    def _lines(self, entries_key: str, legacy_key: str, skip_same_source: bool = False) -> set[str]:
        """Foreign instances among the lines (author and server excluded)."""
        return {i for i in self._line_weights(entries_key, legacy_key, skip_same_source) if i != self.instance}

    def independent_lines(self) -> set[str]:
        """Foreign instances that confirmed, not from the object's own source."""
        return self._lines("confirmations", "confirmed_by", skip_same_source=True)

    def foreign_confirmations(self) -> int:
        """Number of foreign instances that confirmed (each its own line since 0.69.3)."""
        return len(self.independent_lines())

    def self_reviewed(self) -> bool:
        """The author's own instance confirmed it (a self-review, 0.69.3)."""
        return self.instance in self._line_weights("confirmations", "confirmed_by", skip_same_source=True)

    def confirmation_weight(self) -> float:
        """Weighted confirming lines: foreign instances 1 each, a self-review SELF_WEIGHT — the basis of the search bonus."""
        return sum(self._line_weights("confirmations", "confirmed_by", skip_same_source=True).values())

    def link(self, other_id: str, reason: str) -> None:
        with lock:
            for a, b in ((self.id, other_id), (other_id, self.id)):
                # evidence (grund "Beleg…") weighs more than an automatic edge and replaces it; never the other way round
                db().execute("INSERT INTO edge (a, b, reason, ts) VALUES (?,?,?,?) ON CONFLICT (a, b) DO UPDATE SET reason = excluded.reason, "
                             "ts = excluded.ts WHERE excluded.reason LIKE 'Beleg%' AND edge.reason NOT LIKE 'Beleg%'", (a, b, reason[:200], now()))
            db().commit()

    def access(self) -> None:
        """Recalled means reinforced: the access counts, zuletzt moves forward (consolidation). Incremented relatively —
        no lost counter, even if another thread reads the same object at the same time."""
        self.last_at = now()
        with lock:
            db().execute("UPDATE object SET accesses = accesses + 1, last_at = ? WHERE id = ?", (self.last_at, self.id))
            db().commit()
            self.accesses = db().execute("SELECT accesses FROM object WHERE id = ?", (self.id,)).fetchone()[0]

    def edges(self) -> list[tuple[str, str]]:
        with lock:
            return db().execute("SELECT b, reason FROM edge WHERE a = ?", (self.id,)).fetchall()


#: MemoryObject fields = database columns of table object, in the same order (0.67.0: one name for both; up to 0.66 the columns were German)
FIELDS = ("id", "kind", "ts", "last_at", "text", "data", "importance", "confirmed", "refuted", "accesses",
          "mode", "changes", "conversation", "instance", "visibility", "idx")
COLUMNS = FIELDS


def _fields_from_row(row) -> dict:
    d = dict(zip(FIELDS, row))
    d["data"] = json.loads(d["data"] or "{}")
    d["changes"] = json.loads(d["changes"] or "[]")
    return d


def _object_from_row(row) -> MemoryObject:
    o = MemoryObject(**_fields_from_row(row))
    with lock:
        o.hashtags = [r[0] for r in db().execute("SELECT tag FROM tag WHERE object_id = ? ORDER BY tag", (o.id,))]
    return o


def load(oid: str) -> MemoryObject | None:
    with lock:
        row = db().execute(f"SELECT {', '.join(COLUMNS)} FROM object WHERE id = ?", (oid,)).fetchone()
        return _object_from_row(row) if row else None


def _longest_list(d: dict) -> tuple[list | None, str]:
    """The list in daten (top level or one level down) with the longest JSON — the first candidate for shortening."""
    best, path, size = None, "", -1
    for k, v in d.items():
        for p, x in ([(k, v)] + ([(f"{k}.{k2}", v2) for k2, v2 in v.items()] if isinstance(v, dict) else [])):
            if isinstance(x, list) and len(x) > 1:
                n = len(json.dumps(x, ensure_ascii=False))
                if n > size:
                    best, path, size = x, p, n
    return best, path


def _data_json(o: MemoryObject) -> str:
    """Data that is too large is shortened, named: 0.53.1 drops the oldest half of the longest lists first (histories, evidence), so
    problem, solution and content stay; only if that is not enough the data is replaced. Truncating the JSON text made the object unreadable."""
    js = json.dumps(o.data, ensure_ascii=False)
    if len(js) <= DATA_MAX:
        return js
    size_before = len(js)
    for _ in range(40):
        lst, path = _longest_list(o.data)
        if lst is None:
            break
        drop = len(lst) // 2
        del lst[:drop]
        cut = o.data.setdefault("trimmed", {})
        cut[path] = int(cut.get(path) or 0) + drop
        js = json.dumps(o.data, ensure_ascii=False)
        if len(js) <= DATA_MAX:
            log(f"{o.id}: daten with {size_before} chars over limit {DATA_MAX} — oldest entries of long lists dropped ({cut})")
            return js
    log(f"{o.id}: daten with {size_before} chars over limit {DATA_MAX} — replaced")
    return json.dumps({"trimmed_chars": size_before, "reason": f"daten over {DATA_MAX} chars"})


def load_keyed(kind: str, key: str) -> MemoryObject | None:
    """An object with a known key (a conversation's serial, a skill's name, the router model): under its English id (0.67.0 and later)
    or under the German one it got before."""
    for oid in names.ids(kind, key):
        o = load(oid)
        if o is not None:
            return o
    return None


def keyed_id(kind: str, key: str) -> str:
    """The id of the object with this key: the existing one (German or English), else the English id a new object gets."""
    with lock:
        for oid in names.ids(kind, key):
            if db().execute("SELECT 1 FROM object WHERE id = ?", (oid,)).fetchone():
                return oid
    return names.new_id(kind, key)


def load_many(oids: list[str]) -> dict[str, MemoryObject]:
    """Several objects in two queries instead of two per object."""
    outputs: dict[str, MemoryObject] = {}
    with reading() as con:  # 24.11.2026: a read connection beside the writer (see reading)
        for i in range(0, len(oids), 900):
            part = oids[i:i + 900]
            markers = ",".join("?" * len(part))
            tags: dict[str, list[str]] = {}
            for oid, tag in con.execute(f"SELECT object_id, tag FROM tag WHERE object_id IN ({markers}) ORDER BY tag", part):
                tags.setdefault(oid, []).append(tag)
            for row in con.execute(f"SELECT {', '.join(COLUMNS)} FROM object WHERE id IN ({markers})", part):
                d = _fields_from_row(row)
                outputs[d["id"]] = MemoryObject(**d, hashtags=tags.get(d["id"], []))
    return outputs


#: 0.61.0: index names known to exist in vi_index (saves an INSERT per save)
_known_indexes: set[str] = set()

#: 0.70.3 (genius project, exaptation): what a knowledge object was BUILT FOR — the context tags of its first save, the instance and
#: the index, fixed there and never changed by a later save or data update. A later successful use outside it is a functional shift
#: ("not built by natural selection for its current role", Gould & Vrba 1982; forward measure after Mastrogiorgio & Gilsing 2016).
#: Without it the origin cannot be told from tags added later — the limit of the exaptation measurement G4 (18.11.2026).
#: Knowledge kinds only: an experience is its own context.
BUILT_FOR_KINDS = ("insight", "rule", "skill", "search", "page", "image")
BUILT_FOR_TAG_KINDS = ("host", "tool", "topic", "skill", "service", "error", "docs", "knowledge_kind")


def built_for_of(tags, instance: str, idx: str, ts: str) -> dict:
    """The origin record of a knowledge object: its context tags (kinds BUILT_FOR_TAG_KINDS), instance, index and time."""
    return {"tags": sorted({t for t in tags if t.split(":", 1)[0] in BUILT_FOR_TAG_KINDS}), "instance": instance, "index": idx, "ts": ts}


def _keep_built_for(o: MemoryObject, tags) -> None:
    """Set o.data['built_for'] on the first save, and on every later save restore the stored one — whatever the caller holds."""
    row = db().execute("SELECT data FROM object WHERE id = ?", (o.id,)).fetchone()
    stored = None
    if row:
        try:
            stored = (json.loads(row[0] or "{}") or {}).get("built_for")
        except ValueError:
            stored = None
    if stored:
        o.data["built_for"] = stored
    elif row:  # stored before 0.70.3: its tags today may include later ones — the origin is unknown, a named state, never guessed
        o.data["built_for"] = {"unknown": "stored before 0.70.3", "instance": o.instance, "index": o.idx, "ts": o.ts}
    else:
        o.data["built_for"] = built_for_of(tags, o.instance, o.idx, o.ts)


#: kinds the instructions' memory index lists (index.KINDS — not imported: index imports memory)
_INDEX_KINDS = frozenset(("insight", "rule", "skill", "image"))


def save(o: MemoryObject, *, commit: bool = True) -> MemoryObject:
    # 0.67.0: one form of stored data — the English keys of names.DATA_KEYS, whatever the caller wrote (and the history keys likewise);
    # the reports of sleep and model objects keep their keys until step 4b (names.REPORT_KINDS)
    if o.kind in names.DOMAIN_KINDS:
        o.data = names.data_keys(o.data)
    o.changes = names.history_keys(o.changes)
    # one form of the stored values too, as in new_object: a mode or visibility assigned directly (o.mode = "aktiv") is stored English;
    # learning.active() asks for mode "active", so a German mode silently switched the router off (0.67.0, _keep_champion)
    o.mode, o.visibility = names.english(names.MODES, o.mode), names.english(names.VISIBILITIES, o.visibility)
    tags = sorted(set(o.hashtags) | {f"kind:{o.kind}", f"instance:{o.instance}"})
    if o.idx not in _known_indexes:  # 0.61.0: every index an object refers to has its row (the primary key of vi_index)
        with lock:
            db().execute("INSERT OR IGNORE INTO vi_index (name, kind, created, source) VALUES (?, ?, ?, ?)",  # source named: see _migrate
                         (o.idx, "global" if o.idx == "global" else "project", now(), "system" if o.idx == "global" else "automatic"))
        _known_indexes.add(o.idx)
    with lock:
        if o.kind in BUILT_FOR_KINDS:
            _keep_built_for(o, tags)
        db().execute(f"INSERT OR REPLACE INTO object ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                     (o.id, o.kind, o.ts, o.last_at, o.text, _data_json(o), o.importance,
                      o.confirmed, o.refuted, o.accesses, o.mode, json.dumps(o.changes, ensure_ascii=False), o.conversation,
                      o.instance, o.visibility, o.idx))
        db().execute("DELETE FROM tag WHERE object_id = ?", (o.id,))
        db().executemany("INSERT OR IGNORE INTO tag (object_id, tag) VALUES (?, ?)", [(o.id, t) for t in tags])
        if fts:
            db().execute("DELETE FROM object_fts WHERE id = ?", (o.id,))
            db().execute("INSERT INTO object_fts (id, text) VALUES (?, ?)", (o.id, (o.text + "\n" + str(o.data.get("content") or "")
                                                                                + "".join("\n" + r.get("term", "") for r in o.data.get("regions") or []))[:300000]))
        if commit:
            db().commit()
    o.hashtags = tags
    if o.kind in _INDEX_KINDS:  # 24.11.2026: the instructions' memory index is cached (index.CACHE_S); new knowledge is listed at once
        from . import index
        index.forget()
    if _KINDS_CACHE["t"] != float("-inf"):  # cache loaded: a new kind counts at once, not only after KINDS_TTL_S
        new = {t.split(":", 1)[0] for t in tags} - _KINDS_CACHE["kinds"]
        if new:
            _KINDS_CACHE["kinds"] = _KINDS_CACHE["kinds"] | new
    return o


def update_data(oid: str, change) -> int:
    """Change the JSON field daten of one object in place: change(dict) edits it. Read and write under the lock, so counters do not get
    lost (one process writes the memory). Portable instead of SQLite's json_set/json_remove (0.50.0). Returns 1 if the object exists."""
    with lock:
        row = db().execute("SELECT data, kind FROM object WHERE id = ?", (oid,)).fetchone()
        if row is None:
            return 0
        d = json.loads(row[0] or "{}")
        origin = d.get("built_for")
        change(d)
        if origin is not None:  # 0.70.3: the origin record is immutable
            d["built_for"] = origin
        if row[1] in names.DOMAIN_KINDS:  # 0.67.0: one form of stored data, as in save()
            names.data_keys(d)
        return db().execute("UPDATE object SET data = ? WHERE id = ?", (json.dumps(d, ensure_ascii=False), oid)).rowcount


def delete(oids: list[str]) -> int:
    """Remove objects with hashtags, full text, edges and archive content — no dangling edges, no leftovers in the archive."""
    from . import archive
    archive.delete(oids)
    with lock:
        for a in oids:
            db().execute("DELETE FROM object WHERE id = ?", (a,))
            db().execute("DELETE FROM tag WHERE object_id = ?", (a,))
            db().execute("DELETE FROM edge WHERE a = ? OR b = ?", (a, a))
            if fts:
                db().execute("DELETE FROM object_fts WHERE id = ?", (a,))
        db().commit()
    return len(oids)


#: 0.61.0: the index new objects of this context land in when none is given (set per session from its project, see session.on_behalf)
current_index: contextvars.ContextVar[str | None] = contextvars.ContextVar("aktueller_index", default=None)


def _index_of(explicit: str | None) -> str:
    from . import indexes
    return indexes.normalize(explicit) or current_index.get() or indexes.GLOBAL


def new_object(kind: str, text: str, hashtags: list[str], data: dict | None = None, importance: int = 1,
                 who: str = "vi", reason: str = "", oid: str | None = None, mode: str = "active",
                 conversation: str | None = None, instance: str | None = None, visibility: str | None = None,
                 index: str | None = None, link: bool = True, commit: bool = True) -> MemoryObject:
    if not commit and link:
        raise ValueError("deferred commit requires link=False")
    kind, mode = names.english(names.KINDS, kind), names.english(names.MODES, mode)  # 0.67.0: German values of older callers
    visibility = names.english(names.VISIBILITIES, visibility)
    hashtags = [names.canonical_tag(t) for t in hashtags]
    if kind not in KINDS:
        raise ValueError(f"art must be one of {', '.join(KINDS)}")
    if visibility is not None and visibility not in VISIBILITIES:
        raise ValueError(f"sicht must be one of {', '.join(VISIBILITIES)}")
    for t in hashtags:
        if not TAG.match(t):
            raise ValueError(f"hashtag {t!r} does not have the form kind:value")
    # instanz: is not a free hashtag but the author (column instanz) — one thing, one place
    hashtags = [t for t in hashtags if not t.startswith("instance:")]
    text, data = anonymize.without_secrets(text), anonymize.without_secrets(data)  # credentials are never stored
    ts = now()
    # random part: two equal actions in the same second are two objects, not one (otherwise INSERT OR REPLACE
    # silently overwrites the first — found by test_eingebaute_werkzeuge_nie_aus_gedaechtnis)
    o = MemoryObject(id=oid or f"{names.id_prefix(kind)}:{hash_value(kind, text, ts, json.dumps(data or {}, sort_keys=True), secrets.token_hex(8))}", kind=kind, ts=ts,
               last_at=ts, text=text, data=data or {}, hashtags=list(hashtags), importance=max(0, min(3, importance)),
               mode=mode, conversation=conversation or current_conversation.get(),
               instance=instance or current_instance.get() or SERVER_INSTANCE, visibility=visibility or VISIBILITY_PER_KIND[kind],
               idx=_index_of(index),
               changes=[{"ts": ts, "who": who, "what": "created", "reason": (reason or "created")[:300]}])
    save(o) if commit else save(o, commit=False)
    if mode != "quarantine" and link:  # unreviewed content gets no link to own knowledge; code pieces (0.61.0) none either
        link_similar(o)
    return o


# ── Recurring findings: one object per key (0.23.0) ─────────────────────────
# vi_learn(key=…): the same key from the same instance updates that object instead of adding a new one. Stored fields (English
# from the start): data.key, data.repeats (how often it was learned), data.history (earlier states, oldest first).
MERGED = "merged"  # stored mode value (German, existing): merged into another object, out of searches
KEY_MODES = ("active", "test", "disputed")  # refuted, archived or merged objects are not continued — a new object starts
KEY_HISTORY_MAX = 200


def find_by_key(instance: str, key: str) -> MemoryObject | None:
    with lock:
        r = db().execute(f"SELECT id FROM object WHERE instance = ? AND kind = 'insight' AND mode IN ({','.join('?' * len(KEY_MODES))}) "
                         "AND json_extract(data, '$.key') = ? ORDER BY ts LIMIT 1", (instance, *KEY_MODES, key)).fetchone()
    return load(r[0]) if r else None


def _push_history(o: MemoryObject, entries: list[dict]) -> None:
    h = (o.data.get("history") or []) + entries
    if len(h) > KEY_HISTORY_MAX:  # nothing vanishes silently: the trimming is counted
        o.data["history_trimmed"] = o.data.get("history_trimmed", 0) + len(h) - KEY_HISTORY_MAX
        h = h[-KEY_HISTORY_MAX:]
    o.data["history"] = h


def _state(o: MemoryObject) -> dict:
    """The current state of an object as a history entry (text, source, content, time)."""
    return {"ts": o.last_at or o.ts, "text": o.text, **{k: o.data[k] for k in ("source", "content", "outcome") if k in o.data}}


def repeat(o: MemoryObject, text: str, hashtags: list[str], data: dict, importance: int, who: str) -> MemoryObject:
    """The same finding again: o keeps its id; its previous state goes into the history, the new text becomes the current one."""
    text, data = anonymize.without_secrets(text), anonymize.without_secrets(data)
    _push_history(o, [_state(o)])
    for k in ("source", "content", "outcome"):
        o.data.pop(k, None)
    o.data.update(data)
    o.data["repeats"] = int(o.data.get("repeats") or 1) + 1
    o.text = text
    # 17.11.2026: the hashtags of a repetition in their stored (English) form, as new_object stores them — before, a German kind
    # (thema:, fehler:, projekt:) given again under the same key stayed German and no filter found it until the next start migrated it
    o.hashtags = sorted(set(o.hashtags) | {names.canonical_tag(t) for t in hashtags if not t.startswith("instance:")})
    o.importance = max(o.importance, max(0, min(3, importance)))
    o.change(who, f"repeated ({o.data['repeats']}×), earlier text in the history", "vi_learn with the same key")
    save(o)
    link_similar(o)
    return o


def _norm_source(s) -> str:
    """Source text compared loosely: case, surrounding space and trailing punctuation do not make a different source."""
    return str(s or "").strip().lower().rstrip(" .,;/")


#: 0.30.0: visibilities that may be switched afterwards. "privat" belongs to its instance and is never switched by anyone else.
SWITCHABLE_VISIBILITY = ("shared", "internal")


def set_visibility(o: "MemoryObject", new: str, who: str, reason: str) -> bool:
    """Switch an object between geteilt and intern, recorded with reason in its history. False if it already has that visibility.
    intern stops further sharing with the network; copies already published are recalled with vi_net_forget."""
    new = names.english(names.VISIBILITIES, new)  # 0.67.0: geteilt/intern of older callers
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
        rows = db().execute(f"SELECT id, text FROM object WHERE instance = ? AND kind = 'insight' AND mode IN ({','.join('?' * len(KEY_MODES))}) "
                            "ORDER BY ts, id", (instance, *KEY_MODES)).fetchall()
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
        for f in ("source", "content", "outcome"):
            main.data.pop(f, None)
            if f in newest.data:
                main.data[f] = newest.data[f]
        main.text = newest.text
        main.data["repeats"] = int(main.data.get("repeats") or 1) + len(rest)
        main.hashtags = sorted(set().union(*[set(x.hashtags) for x in objs]) - {f"mode:{x.mode}" for x in objs})
        main.importance = max(x.importance for x in objs)
        main.accesses = sum(x.accesses for x in objs)
        main.confirmed = sum(x.confirmed for x in objs)
        main.change(who, f"merged {len(rest)} repetitions with the same key: {', '.join(x.id for x in rest)}"[:300], reason)
        save(main)
        for x in rest:
            x.mode = MERGED
            x.data["merged_into"] = main.id
            x.hashtags = [t for t in x.hashtags if not t.startswith("mode:")] + [f"mode:{MERGED}"]
            x.change(who, f"merged into {main.id}", reason)
            save(x)
            x.link(main.id, "merged into (same key)")
    return report


def link_similar(o: MemoryObject, at_least: int = 2, limit: int = 5) -> None:
    """Zettelkasten: objects sharing ≥ `at_least` content hashtags are linked (A-Mem idea)."""
    content = [t for t in o.hashtags if not t.startswith(ADMIN_PREFIXES)]  # otherwise instanz:/art: would link everything with everything
    if len(content) < at_least or o.kind in ("answer",):
        return
    with lock:
        rows = db().execute(
            f"SELECT object_id, COUNT(*) n FROM tag WHERE tag IN ({','.join('?' * len(content))}) AND object_id <> ? "
            f"GROUP BY object_id HAVING COUNT(*) >= ? ORDER BY n DESC LIMIT ?", (*content, o.id, at_least, limit)).fetchall()
    for oid, n in rows:
        o.link(oid, f"{n} shared hashtags")


# ── Recall: filter language + weighting ──────────────────────────────────────



def parse_filter(filter_text: str, kinds=None):
    """The filter language (clingo_object.filters), with the hashtags of clients of 0.66 or older read in their English form (0.67.0)."""
    return _parse_filter(names.canonical_filter(filter_text), kinds)


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




def _tag_condition(tag: str) -> tuple[str, tuple]:
    return ("tag LIKE ?", (tag[:-1] + "%",)) if tag.endswith("*") else ("tag = ?", (tag,))


#: 0.61.0: a search restricted to one index (vi_recall index=…) — read by _filter_sql, so full text and hybrid search obey it alike
search_index: contextvars.ContextVar[str | None] = contextvars.ContextVar("such_index", default=None)


#: 0.69.8: `index:<name>` in any filter is a condition like a hashtag — AND with everything else (the user, 17.11.2026: "Wenn man nur nach
#: einem Projekt suchen will, dürfen auch nur Projekteinträge gefunden werden. Das wäre dann eine AND-Verknüpfung."). The index is a
#: column, not a hashtag, so it is taken out of the filter text before the hashtag parser sees it.
INDEX_TOKEN = re.compile(r"(?<!\S)index:([a-z0-9][a-z0-9._-]{0,47})(?!\S)")


def split_index(filter_text: str) -> tuple[str, list[str]]:
    """(the filter without its index:… conditions, the indexes named). Several are ANDed — two different ones find nothing."""
    names_ = INDEX_TOKEN.findall(filter_text or "")
    return INDEX_TOKEN.sub(" ", filter_text or "").strip(), list(dict.fromkeys(names_))


#: 0.70.3: indexes searched ONLY when named (vi_index.explicit = 1) — a large external corpus (e.g. an imported Q&A site) lives in the
#: memory without flooding every search and every hint (the user, 19.11.2026: "Erst Index-Option bauen"). Cached briefly: _filter_sql
#: runs for every search and hint.
#: 0.70.4: the column vi_index.explicit holds ONE search scope per index, so no index can be "named only" and "searched" at once:
#: 0 = everywhere (as before), 1 = only when named, 2 = external — found by every user search (vi_recall, the web search) without
#: naming it, but never a hint, never embedded or labelled in sleep, no proximity edges (the user, 19.11.2026: "Eigentlich wollten
#: wir die Suche ohne explicit machen"). Its vectors come from an offline import, not the shared embedding service.
SCOPE_ALL, SCOPE_NAMED, SCOPE_EXTERNAL = 0, 1, 2
SCOPES = {"all": SCOPE_ALL, "named": SCOPE_NAMED, "external": SCOPE_EXTERNAL}
_EXPLICIT_CACHE: dict = {"t": float("-inf"), "v": {}}
EXPLICIT_TTL_S = 30.0
#: set by the searches a person or agent asks for (vi_recall, the internal web search): only they see external indexes unnamed.
#: Every other path — hints before an action, error hints, the prompt context — keeps them out by default, so a new hint path
#: cannot leak a large corpus into the hints by forgetting a flag.
user_search: contextvars.ContextVar[bool] = contextvars.ContextVar("user_search", default=False)


def index_scopes() -> dict[str, int]:
    """name → scope of every index that is not searched everywhere."""
    import time as _t
    if _t.monotonic() - _EXPLICIT_CACHE["t"] > EXPLICIT_TTL_S:
        with lock:
            try:
                v = {r[0]: int(r[1]) for r in db().execute("SELECT name, explicit FROM vi_index WHERE explicit <> 0")}
            except sqlite3.OperationalError:  # a database before the column (opened read-only, never migrated)
                v = {}
        _EXPLICIT_CACHE.update(t=_t.monotonic(), v=v)
    return _EXPLICIT_CACHE["v"]


def explicit_indexes() -> frozenset:
    """The names of the indexes that are searched only when named."""
    return frozenset(n for n, s in index_scopes().items() if s == SCOPE_NAMED)


def external_indexes() -> frozenset:
    """The names of the external indexes (0.70.4): in user searches, never in hints."""
    return frozenset(n for n, s in index_scopes().items() if s == SCOPE_EXTERNAL)


def invalidate_explicit() -> None:
    _EXPLICIT_CACHE["t"] = float("-inf")


def _filter_sql(groups: list, remove: list, viewer: str | None, indexes_: list[str] | None = None, per_id: bool = False) -> tuple[str, list]:
    """SQL for mode, visibility and hashtag conditions (without free text) — one source for recall(), ids_for_filter() and admitted().
    per_id (24.11.2026, admitted): the hashtag conditions as EXISTS per object instead of IN (list) — the same rows; for a few hundred
    ids the list form built the whole list first (kind:insight OR …: ~200,000 ids, 0.49 s per 900 ids on a production copy)."""
    sql, par = f"SELECT id FROM object WHERE mode NOT IN {GONE_SQL}", []
    named = ([search_index.get()] if search_index.get() else []) + list(indexes_ or [])
    for ix in named:
        sql += " AND idx = ?"
        par.append(ix)
    # 0.70.3: an explicit-only index stays out unless named; 0.70.4: an external one also, unless a user search asks
    if not named and (ex := explicit_indexes() | (frozenset() if user_search.get() else external_indexes())):
        sql += f" AND idx NOT IN ({','.join('?' * len(ex))})"
        par += sorted(ex)
    if not any("mode:quarantine" in grp for grp in groups):
        sql += " AND mode <> 'quarantine'"  # only via vi_quarantine
    if not any("mode:merged" in grp for grp in groups):
        sql += " AND mode <> 'merged'"  # merged skills only on request (reference is in the object)
    if not any("mode:archived" in grp for grp in groups):
        sql += " AND mode <> 'archived'"  # archived objects only on explicit request
    if viewer is not None:
        sql += " AND (visibility = 'shared' OR instance = ?" + (" OR visibility = 'internal')" if viewer != OPEN_INSTANCE else ")")
        par.append(viewer)
    for g in groups:
        parts = [_tag_condition(t) for t in g]
        cond = " OR ".join(b for b, _ in parts)
        sql += (f" AND EXISTS (SELECT 1 FROM tag WHERE tag.object_id = object.id AND ({cond}))" if per_id
                else f" AND id IN (SELECT object_id FROM tag WHERE {cond})")
        for _, p in parts:
            par += list(p)
    for t in remove:
        b, p = _tag_condition(t)
        sql += (f" AND NOT EXISTS (SELECT 1 FROM tag WHERE tag.object_id = object.id AND {b})" if per_id
                else f" AND id NOT IN (SELECT object_id FROM tag WHERE {b})")
        par += list(p)
    return sql, par


def ids_for_filter(filter_text: str, kinds: tuple[str, ...] = (), viewer: str | None = "aktuell") -> list[str]:
    """All visible ids for the filter's hashtag conditions, without an upper limit (candidates of the semantic search)."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    filter_text, idx_only = split_index(filter_text)
    groups, remove, _w = parse_filter(filter_text, known_kinds())
    if kinds:
        groups.append([f"kind:{names.english(names.KINDS, a)}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer, idx_only)
    with reading() as con:
        return [r[0] for r in con.execute(sql, par)]


def admitted(ids: list[str], filter_text: str, kinds: tuple[str, ...] = (), viewer: str | None = "aktuell") -> set[str]:
    """Which of these ids ids_for_filter() would return — the same conditions, checked for these ids only (in chunks of
    VISIBLE_CHUNK). 24.11.2026: the meaning search asks for its nearest vectors this way instead of listing every visible id first
    (197,036 ids, 1.46 s of a 3.05 s hybrid vi_recall on a production copy)."""
    if viewer == "aktuell":
        viewer = current_instance.get()
    filter_text, idx_only = split_index(filter_text)
    groups, remove, _w = parse_filter(filter_text, known_kinds())
    if kinds:
        groups.append([f"kind:{names.english(names.KINDS, a)}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer, idx_only, per_id=True)
    out: set[str] = set()
    with reading() as con:
        for i in range(0, len(ids), VISIBLE_CHUNK):
            part = ids[i:i + VISIBLE_CHUNK]
            out.update(r[0] for r in con.execute(f"{sql} AND id IN ({','.join('?' * len(part))})", [*par, *part]))
    return out


#: full-text hits fetched before the visibility filter (search-top4): enough to keep 500 visible ones in the usual case
FTS_POOL = 2000
#: ids per visibility query — below SQLite's variable limit (999 in older builds; a pool of 10^9 failed with "too many SQL variables")
VISIBLE_CHUNK = 900

#: True switches stop-word removal off for this context — the A/B measurement of the current code against the old behaviour only.
stop_words_off: contextvars.ContextVar[bool] = contextvars.ContextVar("stoppwoerter_aus", default=False)

#: How the last word search in this context ran: "and" (all words), "or" (fallback, because too few contained all words) or None.
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
    filter_text, idx_only = split_index(filter_text)
    groups, remove, words = parse_filter(filter_text, known_kinds())
    if not stop_words_off.get():
        # fts-stopwords (15.11.2026): function words leave the query, never the index — a natural question ANDed "wie", "ich",
        # "der"… and the OR fallback ranked by them (production copy: question Hit@4 0.293 → 0.547). Only stop words: unchanged.
        from .stopwords import content_words
        words = content_words(words)
    if kinds:
        groups.append([f"kind:{names.english(names.KINDS, a)}" for a in kinds])
    sql, par = _filter_sql(groups, remove, viewer, idx_only)
    # 24.11.2026: the same conditions per object (EXISTS) for the queries that check a few hundred ids only — the pool's visibility
    # and the final query; the list form built every matching id of the hashtag conditions first (0.47 + 0.49 s of a hybrid vi_recall
    # on a production copy, under the database lock)
    sql_id, par_id = _filter_sql(groups, remove, viewer, idx_only, per_id=True)
    word_hits: dict[str, float] = {}
    search_kind = None
    with reading() as con:  # 24.11.2026: a read connection beside the writer (see reading)
        if words:
            if fts:
                terms = ['"' + w.replace('"', '') + '"' for w in words]
                search_kind = "and"

                def _fts(q: str) -> dict[str, float]:
                    if backend() == "postgres":  # 0.50.0: tsvector ('simple': no stemming, like FTS5 unicode61); ts_rank instead of bm25
                        return {oid: float(rank) for oid, rank in con.execute(
                            f"SELECT id, ts_rank(tsv, q) AS r FROM object_fts, websearch_to_tsquery('simple', ?) q WHERE tsv @@ q AND id IN ({sql}) "
                            "ORDER BY r DESC LIMIT 500", (q, *par))}
                    # search-top4 (15.11.2026): the full-text index first, then the visibility filter on its hits only. Matching inside
                    # "id IN (all visible ids)" took 1,826 ms on a 500,310-object copy; MATCH alone 80 ms plus the filter on 2,000 ids
                    # 10 ms. When invisible or filtered rows exhaust the pool, the exact query runs — the ranking is the same either way.
                    pool = con.execute("SELECT id, rank FROM object_fts WHERE object_fts MATCH ? ORDER BY rank LIMIT ?", (q, FTS_POOL)).fetchall()
                    if pool:
                        visible = set()
                        ids = [r[0] for r in pool]
                        for i in range(0, len(ids), VISIBLE_CHUNK):  # chunks: SQLite's variable limit (999 in older builds)
                            part = ids[i:i + VISIBLE_CHUNK]
                            visible |= {r[0] for r in con.execute(f"{sql_id} AND id IN ({','.join('?' * len(part))})", (*par_id, *part))}
                        hits = [(oid, rank) for oid, rank in pool if oid in visible][:500]
                        if len(hits) >= 500 or len(pool) < FTS_POOL:
                            return {oid: -float(rank) for oid, rank in hits}
                    else:
                        return {}
                    return {oid: -float(rank) for oid, rank in con.execute(
                        f"SELECT id, rank FROM object_fts WHERE object_fts MATCH ? AND id IN ({sql}) ORDER BY rank LIMIT 500", (q, *par))}
                word_hits = _fts(" ".join(terms))
                if or_fallback and len(terms) > 1 and len(word_hits) < limit:
                    or_hits = _fts((" or " if backend() == "postgres" else " OR ").join(terms))
                    if len(or_hits) > len(word_hits):
                        # objects with all words stay in front: their rank is lifted above the highest OR rank
                        upper = max(or_hits.values(), default=0.0)
                        word_hits = {**or_hits, **{k: v + abs(upper) + 1 for k, v in word_hits.items()}}
                        search_kind = "or"
                sql = sql_id + (f" AND id IN ({','.join('?' * len(word_hits))})" if word_hits else " AND 1 = 0")
                par = par_id + list(word_hits)
            else:
                for w in words:
                    sql += " AND text LIKE ?"
                    par.append(f"%{w}%")
        if word_hits:
            # 0.57.0: with words, the candidates are the best by full-text rank, not the most recently used — before, of the 500 best
            # BM25 hits the 400 most recently touched were kept, so an old exact hit could drop out before it was rated
            matching = [r[0] for r in con.execute(sql, par)]
            ids = sorted(matching, key=lambda i: -word_hits.get(i, 0.0))[:max(400, int(limit))]
        else:
            ids = [r[0] for r in con.execute(sql + f" ORDER BY last_at DESC LIMIT {max(400, int(limit))}", par)]
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
        bonus = min(BONUS_MAX, BONUS_PER_INSTANCE * o.confirmation_weight())
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
