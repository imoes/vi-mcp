"""Triggers for documentation (0.26.0): imported documentation gets host: and thema: hashtags so it can appear before matching actions.

Imported documentation (Confluence company docs, vendor docs, manuals) carried only administrative hashtags (space:, seite:, bereich:).
Hints before an action are found through triggers (tool:, host:, thema:), so documentation hardly ever appeared unasked — measured
10.11.2026: 73 of 12,994 Confluence objects ever recalled. This sleep step adds triggers, conservatively:

- host: only hosts the memory already knows from outside the documentation (host: hashtags of experiences, insights, rules, skills), found
  in text or content as the full name or as a first label with a digit (e.g. db0137 for db0137.example.org). No new hosts are guessed.
- thema: only topics that learned knowledge already uses (insights, rules, skills outside the documentation, at least THEMA_MIN objects),
  found as a whole word in the object's text (title line) — not in the body, which mentions far too much. Experiences are not a source:
  their thema: values come from shell words (thema:for, thema:from).
- Links are removed first (the wiki's own host name is in every page link). A host found in more than HOST_DF_MAX, a topic in more than
  THEMA_DF_MAX of all documentation says nothing specific and is skipped (measured: thema:lanao would have hit every Stibo page).
- At most HOST_MAX / THEMA_MAX per object; recorded in data.derived_triggers and in the change history. No edges are created
  (edge explosion of 09.11.2026: 2.49 M edges).
"""
from __future__ import annotations

import re

from . import memory as g

VERSION = 1
DOC_TAGS = ("art_wissen:firmendoku", "art_wissen:doku-extern", "art_wissen:handbuch")
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
    return f"SELECT objekt_id FROM tag WHERE tag IN ({','.join('?' * len(DOC_TAGS))})"


def vocabulary() -> tuple[dict[str, str], set[str]]:
    """(name → host: value, thema words). Names: full host names and unambiguous first labels that contain a digit."""
    with g.lock:
        hosts = [r[0][5:].lower() for r in g.db().execute(
            f"SELECT DISTINCT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'host:%' "
            f"AND o.art IN ('erfahrung', 'erkenntnis', 'regel', 'skill') AND o.id NOT IN ({_doc_ids_sql()})", DOC_TAGS)]
        themen = {r[0][6:].lower() for r in g.db().execute(
            f"SELECT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'thema:%' "
            f"AND o.art IN ('erkenntnis', 'regel', 'skill') AND o.id NOT IN ({_doc_ids_sql()}) "
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
    return names, {t for t in themen if len(t) >= 3}


def derive(text: str, content: str, names: dict[str, str], themen: set[str], limit: bool = True) -> tuple[list[str], list[str]]:
    tokens = set(_TOKEN.findall(_URL.sub(" ", f"{text}\n{content}").lower()))
    hosts = sorted({names[t] for t in tokens if t in names})[:HOST_MAX if limit else None]
    words = set(_WORD.findall(text.lower()))
    topics = sorted(t for t in themen if t in words)[:THEMA_MAX if limit else None]
    return hosts, topics


def run(batch: int = BATCH) -> dict:
    """One sleep step: documentation objects not yet processed with this VERSION, oldest first, at most `batch`."""
    names, themen = vocabulary()
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            f"SELECT id FROM objekt WHERE id IN ({_doc_ids_sql()}) AND modus NOT IN ('aufgegangen', 'widerlegt') "
            "AND COALESCE(json_extract(daten, '$.derived_triggers.version'), 0) < ? ORDER BY zeit LIMIT ?", (*DOC_TAGS, VERSION, batch))]
    too_common_h: set[str] = set()
    too_common_t: set[str] = set()
    if ids:  # document frequency over all documentation: what fits too much of it is no specific trigger
        with g.lock:
            rows = g.db().execute(f"SELECT text, json_extract(daten, '$.inhalt') FROM objekt WHERE id IN ({_doc_ids_sql()})", DOC_TAGS).fetchall()
        hdf: dict[str, int] = {}
        tdf: dict[str, int] = {}
        for text, content in rows:
            h, t = derive(text or "", content or "", names, themen, limit=False)
            for x in h:
                hdf[x] = hdf.get(x, 0) + 1
            for x in t:
                tdf[x] = tdf.get(x, 0) + 1
        if len(rows) >= DF_MIN_DOCS:
            too_common_h = {x for x, n in hdf.items() if n > HOST_DF_MAX * len(rows)}
            too_common_t = {x for x, n in tdf.items() if n > THEMA_DF_MAX * len(rows)}
        names = {k: v for k, v in names.items() if v not in too_common_h}
        themen = themen - too_common_t
    report = {"geprueft": 0, "mit_host": 0, "mit_thema": 0, "hashtags_neu": 0, "bekannte_hosts": len(set(names.values())), "themen": len(themen),
              "zu_haeufig": sorted(too_common_h | too_common_t)[:20]}
    for oid in ids:
        o = g.load(oid)
        if o is None:
            continue
        report["geprueft"] += 1
        hosts, topics = derive(o.text, str(o.data.get("inhalt") or ""), names, themen)
        new = [f"host:{h}" for h in hosts] + [f"thema:{t}" for t in topics]
        new = [t for t in new if t not in o.hashtags and g.TAG.match(t)]
        o.data["derived_triggers"] = {"version": VERSION, "host": hosts, "thema": topics}
        if new:
            report["mit_host"] += bool(hosts)
            report["mit_thema"] += bool(topics)
            report["hashtags_neu"] += len(new)
            o.hashtags = sorted(set(o.hashtags) | set(new))
            o.change("vi", "derived triggers: " + " ".join(f"+{t}" for t in new), "sleep: known hosts and topics found in the documentation")
        g.save(o)  # without link_similar: no new edges
    report["offen"] = _remaining()
    return report


def _remaining() -> int:
    with g.lock:
        return g.db().execute(
            f"SELECT COUNT(*) FROM objekt WHERE id IN ({_doc_ids_sql()}) AND modus NOT IN ('aufgegangen', 'widerlegt') "
            "AND COALESCE(json_extract(daten, '$.derived_triggers.version'), 0) < ?", (*DOC_TAGS, VERSION)).fetchone()[0]
