"""Triggers for documentation (0.26.0): imported documentation gets host: and topic: hashtags so it can appear before matching actions.

Imported documentation (Confluence company docs, vendor docs, manuals) carried only administrative hashtags (space:, seite:, area:).
Hints before an action are found through triggers (tool:, host:, topic:), so documentation hardly ever appeared unasked — measured
10.11.2026: 73 of 12,994 Confluence objects ever recalled. This sleep step adds triggers, conservatively:

- host: only hosts the memory already knows from outside the documentation (host: hashtags of experiences, insights, rules, skills), found
  in text or content as the full name or as a first label with a digit (e.g. db0137 for db0137.example.org). No new hosts are guessed.
- topic: only topics that learned knowledge already uses (insights, rules, skills outside the documentation, at least THEMA_MIN objects),
  found as a whole word in the object's text (title line) — not in the body, which mentions far too much. Experiences are not a source:
  their topic: values come from shell words (topic:for, topic:from).
- Links are removed first (the wiki's own host name is in every page link). A host found in more than HOST_DF_MAX, a topic in more than
  THEMA_DF_MAX of all documentation says nothing specific and is skipped (measured: topic:lanao would have hit every Stibo page).
- At most HOST_MAX / THEMA_MAX per object; recorded in data.derived_triggers and in the change history. No edges are created
  (edge explosion of 09.11.2026: 2.49 M edges).
"""
from __future__ import annotations

import re

from . import memory as g

VERSION = 2  # 2 (0.69.1): STOPWORDS — function and filler words are never a topic trigger (an import of 17.11.2026 set topic:for,
#              topic:old, topic:error on documentation because learned knowledge carried them as topics)
#: 0.70.10: SYSTEM_TOPICS — a topic an agent assigns by meaning is never derived from a page's words (Stack Exchange pages with
#: "requirement" in the title became topic:requirement and filled the index section of the user's decisions: 13 of 111,735 pages on
#: 19.11.2026). No VERSION bump for 13 pages: run() takes the pages that carry a derived system topic along with the stale ones.
#: topics with a fixed meaning set by an agent or the server (rule 6: topic:requirement = what the user decided) — never a derived trigger
SYSTEM_TOPICS = frozenset({"requirement", "open", "offen"})
#: words that are no topic however often learned knowledge used them as one (English and German function and filler words)
STOPWORDS = frozenset("""
a an and are as at be by for from has have in into is it its new no not of old on or out so the to up use used using was were
what when where which with error errors info note notes page pages part step steps test tests example examples general other
der die das den dem des ein eine einer und oder mit von vom zu zur zum im in ist sind für fuer auf aus bei nach über ueber
unter wie was wer neu alt fehler hinweis seite teil beispiel test allgemein sonstiges
""".split())
DOC_TAGS = ("knowledge_kind:company-docs", "knowledge_kind:external-docs", "knowledge_kind:manual")
HOST_MAX, THEMA_MAX = 5, 5
THEMA_MIN = 3
BATCH = 3000
HOST_DF_MAX, THEMA_DF_MAX = 0.02, 0.05
DF_MIN_DOCS = 200  # below this, shares say nothing
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)
_HOST_OK = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,10}$")
_TOKEN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")
_WORD = re.compile(r"[a-zäöüß0-9][a-zäöüß0-9._-]*[a-zäöüß0-9]|[a-zäöüß0-9]")


def _doc_ids_sql() -> str:
    return f"SELECT object_id FROM tag WHERE tag IN ({','.join('?' * len(DOC_TAGS))})"


def vocabulary() -> tuple[dict[str, str], set[str]]:
    """(name → host: value, thema words). Names: full host names and unambiguous first labels that contain a digit."""
    with g.lock:
        hosts = [r[0][5:].lower() for r in g.db().execute(
            f"SELECT DISTINCT t.tag FROM tag t JOIN object o ON o.id = t.object_id WHERE t.tag LIKE 'host:%' "
            f"AND o.kind IN ('experience', 'insight', 'rule', 'skill') AND o.id NOT IN ({_doc_ids_sql()})", DOC_TAGS)]
        themen = {r[0][6:].lower() for r in g.db().execute(
            f"SELECT t.tag FROM tag t JOIN object o ON o.id = t.object_id WHERE t.tag LIKE 'topic:%' "
            f"AND o.kind IN ('insight', 'rule', 'skill') AND o.id NOT IN ({_doc_ids_sql()}) "
            f"GROUP BY t.tag HAVING COUNT(DISTINCT o.id) >= ?", (*DOC_TAGS, THEMA_MIN))}
    names: dict[str, str] = {}
    short: dict[str, set[str]] = {}
    for h in hosts:
        if not _HOST_OK.match(h):
            continue
        names[h] = h
        first = h.split(".", 1)[0]
        if len(first) >= 4 and any(ch.isdigit() for ch in first):
            short.setdefault(first, set()).add(h)
    for first, full in short.items():
        if len(full) == 1 and first not in names:
            names[first] = next(iter(full))
    return names, {t for t in themen if len(t) >= 3 and t not in STOPWORDS and t not in SYSTEM_TOPICS}


def common_sets(names: dict[str, str], themen: set[str]) -> tuple[set[str], set[str]]:
    """Hosts and topics found in more than HOST_DF_MAX / THEMA_DF_MAX of all documentation (with at least DF_MIN_DOCS documents) —
    no specific trigger. Also used by the documentation import (0.69.1), which keeps the result for an hour."""
    with g.lock:
        rows = g.db().execute(f"SELECT text, json_extract(data, '$.content') FROM object WHERE id IN ({_doc_ids_sql()})", DOC_TAGS).fetchall()
    hdf: dict[str, int] = {}
    tdf: dict[str, int] = {}
    for text, content in rows:
        h, t = derive(text or "", content or "", names, themen, limit=False)
        for x in h:
            hdf[x] = hdf.get(x, 0) + 1
        for x in t:
            tdf[x] = tdf.get(x, 0) + 1
    if len(rows) < DF_MIN_DOCS:
        return set(), set()
    common = ({x for x, n in hdf.items() if n > HOST_DF_MAX * len(rows)}, {x for x, n in tdf.items() if n > THEMA_DF_MAX * len(rows)})
    _last_common[:] = sorted(common[0] | common[1])
    return common


def derive(text: str, content: str, names: dict[str, str], themen: set[str], limit: bool = True) -> tuple[list[str], list[str]]:
    tokens = set(_TOKEN.findall(_URL.sub(" ", f"{text}\n{content}").lower()))
    hosts = sorted({names[t] for t in tokens if t in names})[:HOST_MAX if limit else None]
    words = set(_WORD.findall(text.lower()))
    topics = sorted(t for t in themen if t in words and t not in STOPWORDS)[:THEMA_MAX if limit else None]
    return hosts, topics


def run(batch: int = BATCH) -> dict:
    """One sleep step: documentation objects not yet processed with this VERSION, oldest first, at most `batch`."""
    names, themen = vocabulary()
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            f"SELECT id FROM object WHERE id IN ({_doc_ids_sql()}) AND mode NOT IN ('merged', 'refuted', 'withdrawn') "
            "AND COALESCE(CAST(json_extract(data, '$.derived_triggers.version') AS REAL), 0) < ? ORDER BY ts LIMIT ?", (*DOC_TAGS, VERSION, batch))]
        system = tuple(f"topic:{t}" for t in sorted(SYSTEM_TOPICS))
        carrying = [r[0] for r in g.db().execute(  # 0.70.10: pages an earlier run gave a system topic — only a derived one is taken off
            f"SELECT DISTINCT object_id FROM tag WHERE tag IN ({','.join('?' * len(system))}) AND object_id IN ({_doc_ids_sql()})",
            (*system, *DOC_TAGS)) if r[0] not in ids][:batch]
    for oid, o in g.load_many(carrying).items():
        if SYSTEM_TOPICS & set((o.data.get("derived_triggers") or {}).get("topic") or []):
            ids.append(oid)
    too_common_h: set[str] = set()
    too_common_t: set[str] = set()
    if ids:  # document frequency over all documentation: what fits too much of it is no specific trigger
        too_common_h, too_common_t = common_sets(names, themen)
        names = {k: v for k, v in names.items() if v not in too_common_h}
        themen = themen - too_common_t
    report = {"geprueft": 0, "mit_host": 0, "mit_thema": 0, "hashtags_neu": 0, "bekannte_hosts": len(set(names.values())), "themen": len(themen),
              "zu_haeufig": sorted(too_common_h | too_common_t)[:20]}
    for oid in ids:
        o = g.load(oid)
        if o is None:
            continue
        report["geprueft"] += 1
        hosts, topics = derive(o.text, str(o.data.get("content") or ""), names, themen)
        # 0.69.1: topics an earlier version derived that are filler words now (topic:for, topic:old …) are taken off again
        stale = [f"topic:{t}" for t in (o.data.get("derived_triggers") or {}).get("topic") or [] if t in STOPWORDS | SYSTEM_TOPICS]
        stale = [t for t in stale if t in o.hashtags]
        if stale:
            o.hashtags = [t for t in o.hashtags if t not in stale]
            o.change("vi", "derived triggers removed: " + " ".join(stale), "sleep: filler words are no topic (doc_triggers.STOPWORDS)")
            report["entfernt"] = report.get("entfernt", 0) + len(stale)
        new = [f"host:{h}" for h in hosts] + [f"topic:{t}" for t in topics]
        new = [t for t in new if t not in o.hashtags and g.TAG.match(t)]
        o.data["derived_triggers"] = {"version": VERSION, "host": hosts, "topic": topics}
        if new:
            report["mit_host"] += bool(hosts)
            report["mit_thema"] += bool(topics)
            report["hashtags_neu"] += len(new)
            o.hashtags = sorted(set(o.hashtags) | set(new))
            o.change("vi", "derived triggers: " + " ".join(f"+{t}" for t in new), "sleep: known hosts and topics found in the documentation")
        g.save(o)  # without link_similar: no new edges
    report["offen"] = _remaining()
    return report


_cache: dict = {"at": 0.0, "db": None, "names": {}, "topics": set()}


def cached_vocabulary(max_age: float = 3600.0) -> tuple[dict[str, str], set[str]]:
    """vocabulary() without the hosts and topics too common in the documentation (common_sets), kept for an hour per database — for the
    paths that tag one object at a time: the documentation import (0.69.0) and the qualification on access (0.69.2)."""
    import time
    now = time.monotonic()
    if _cache["db"] is not g.db() or now - _cache["at"] > max_age:
        names, themen = vocabulary()
        common_h, common_t = common_sets(names, themen)
        _cache.update(at=now, db=g.db(), names={k: v for k, v in names.items() if v not in common_h}, topics=themen - common_t)
    return _cache["names"], _cache["topics"]


def is_doc(o) -> bool:
    return any(t in o.hashtags for t in DOC_TAGS)


def stale(o) -> bool:
    """A documentation object whose triggers were derived by an older version (or never)."""
    return is_doc(o) and float(((o.data.get("derived_triggers") or {}).get("version")) or 0) < VERSION


def refresh(o, who: str = "vi", why: str = "on access") -> list[str]:
    """Derive the triggers of one documentation object now (the rules of run(), the cached vocabulary): add host:/topic:, take filler
    topics an earlier version derived off again, record data.derived_triggers. Returns the hashtags added (and "-tag" for removed)."""
    names, themen = cached_vocabulary()
    hosts, topics = derive(o.text, str(o.data.get("content") or ""), names, themen)
    removed = [f"topic:{t}" for t in ((o.data.get("derived_triggers") or {}).get("topic") or []) if t in STOPWORDS | SYSTEM_TOPICS]
    removed = [t for t in removed if t in o.hashtags]
    new = [t for t in [f"host:{h}" for h in hosts] + [f"topic:{t}" for t in topics] if t not in o.hashtags and g.TAG.match(t)]
    o.hashtags = sorted((set(o.hashtags) - set(removed)) | set(new))
    o.data["derived_triggers"] = {"version": VERSION, "host": hosts, "topic": topics, "at": why}
    if new or removed:
        o.change(who, "derived triggers: " + " ".join([f"+{t}" for t in new] + [f"-{t}" for t in removed]), f"{why}: doc_triggers v{VERSION}")
    g.save(o)
    return new + [f"-{t}" for t in removed]


#: 0.69.0: what the last run found too common to be a specific trigger — the import (doc_import) leaves it out as well
_last_common: list[str] = []


def too_common() -> list[str]:
    """Hosts and topics the last sleep step found in too much of the documentation (empty until it ran in this process)."""
    return list(_last_common)


def _remaining() -> int:
    with g.lock:
        return g.db().execute(
            f"SELECT COUNT(*) FROM object WHERE id IN ({_doc_ids_sql()}) AND mode NOT IN ('merged', 'refuted', 'withdrawn') "
            "AND COALESCE(CAST(json_extract(data, '$.derived_triggers.version') AS REAL), 0) < ?", (*DOC_TAGS, VERSION)).fetchone()[0]
