"""0.72.0: title anchor + one mention hop for vi_recall (goal Z6) — behind the switch `search_anchor` (config), off by default.

A question that names a host is often about two pages: the host's own documentation page and the page of a host it mentions (a VM and
its Proxmox node). Plain hybrid search finds the first and rarely the second (PREREG_Z6, 22.11.2026, 846 test questions: both pages in
the top 4 for 6.4 %). Method M1 of that study reached 81.1 %:
  1. title index: every documentation page (`insight:doc-…`, text "LABEL: title — …") is keyed by the host names in its TITLE (fully
     qualified, at least three labels); a short name (first label) is a key only when it contains a digit — hosts here are named like
     web0042, everyday words like "system" were titles' first labels (found on development data);
  2. anchor = the page whose title names a host the question names (the shortest such title);
  3. hop = the pages titled with the OTHER hosts the anchor's text names, in order of first mention;
  4. anchor and hops are placed in front of the hybrid list (how many hops, and where: `HOPS`, chosen on development data only).
Unlike the study's script (which read the database directly), every anchor and hop passes the search's own filter and visibility
(`memory.admitted`: the viewer, the index searched alone, scoped indexes, mode), and pages of search-scoped indexes (named only,
external) are not in the title index — an external corpus is never a hint, and an anchor is placed like one.
Modes: off (default) · on · ab (a share of conversations, by a hash of the conversation serial, so one conversation keeps one arm).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

from . import memory as g

MODE = "off"  # config search_anchor: off | on | ab
SHARE = 0.0  # config search_anchor_share: with ab, the share of conversations that get the anchor (at most 0.5)
#: how many hop pages follow the anchor in front of the hybrid list (chosen on development data, see CHANGELOG 0.72.0)
HOPS = 1
#: hop pages considered per anchor (the study's limit)
HOPS_MAX = 5
CACHE_S = 300.0
#: measurement only (development data, the gate): a list → every hybrid search appends {query, ranked (before the anchor), plan}
CAPTURE: list | None = None
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]")
FQDN = re.compile(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+){2,}")
DOC_PREFIXES = ("insight:doc-", "erkenntnis:doc-")  # 0.67.0 renamed the id prefix; old ids stay valid

_cache: dict = {"at": 0.0, "db": None, "index": {}}
_build = threading.Lock()


def _keys(title: str) -> list[str]:
    """Host keys a page title gives: each fully qualified name, and its first label only when that contains a digit. Pure."""
    out = []
    for h in FQDN.findall(title.lower()):
        short = h.split(".")[0]
        out += [h, short] if any(c.isdigit() for c in short) else [h]
    return out


def title_of(text: str) -> str:
    """The title of a documentation page's key statement ("LABEL: title — first words"). Pure."""
    head = (text or "").split(" — ", 1)[0]
    return head.split(": ", 1)[1] if ": " in head else head


def _load() -> dict[str, str]:
    best: dict[str, tuple[str, int]] = {}
    like = " OR ".join("id LIKE ?" for _ in DOC_PREFIXES)
    with g.reading() as con:
        rows = con.execute(f"SELECT id, substr(text, 1, 400) FROM object WHERE ({like}) AND mode = 'active' "
                           "AND idx NOT IN (SELECT name FROM vi_index WHERE explicit <> 0)", [p + "%" for p in DOC_PREFIXES]).fetchall()
    for oid, text in rows:
        title = title_of(text)
        for key in _keys(title):
            if key not in best or len(title) < best[key][1]:
                best[key] = (oid, len(title))
    return {k: v[0] for k, v in best.items()}


def title_index() -> dict[str, str]:
    """host key → page id; built once per CACHE_S (one build at a time; the others use the previous index of the same database)."""
    db = (str(getattr(g, "fpath_active", "") or ""), id(g.db()))
    fresh = lambda: _cache["db"] == db and time.monotonic() - _cache["at"] <= CACHE_S  # noqa: E731
    if fresh():
        return _cache["index"]
    same_db = _cache["db"] == db
    if not _build.acquire(blocking=not same_db):
        return _cache["index"]
    try:
        if not fresh():
            _cache.update(at=time.monotonic(), db=db, index=_load())
    finally:
        _build.release()
    return _cache["index"]


def forget() -> None:
    _cache.update(at=0.0, db=None, index={})


def plan(question: str, admit) -> list[dict]:
    """For each host the question names (in order): {word, anchor, hops} — anchor and hops are page ids that `admit` lets through
    (admit(ids) -> the admitted subset: the search's filter and visibility). Hops: at most HOPS_MAX, in order of first mention."""
    index = title_index()
    out, seen = [], set()
    for w in dict.fromkeys(x.lower() for x in WORD.findall(question or "")):
        a = index.get(w)
        if not a or a in seen:
            continue
        o = g.load_many([a]).get(a)
        body = (o.text + "\n" + str(o.data.get("content") or "")) if o else ""
        hops: list[str] = []
        for h in WORD.findall(body):
            b = index.get(h.lower())
            if b and b != a and b not in hops:
                hops.append(b)
                if len(hops) >= HOPS_MAX:
                    break
        ok = admit([a, *hops])
        if a not in ok:
            continue  # the anchor itself is not visible here or not in the filter: no anchor, and no hops from a page the viewer can't see
        seen.add(a)
        out.append({"word": w, "anchor": a, "hops": [b for b in hops if b in ok]})
    return out


def place(ranked: list[str], planned: list[dict], hops: int | None = None) -> list[str]:
    """Anchors, each followed by its first `hops` hop pages (default HOPS), in front of the hybrid list; no id twice. Pure."""
    n = HOPS if hops is None else hops
    front: list[str] = []
    for p in planned:
        for i in [p["anchor"], *p["hops"][:n]]:
            if i not in front:
                front.append(i)
    return front + [i for i in ranked if i not in front]


def active(conversation: str | None) -> tuple[bool, str]:
    """Whether this search gets the anchor, and the arm named in the search note: (on?, "on"|"off"|"ab:on"|"ab:off")."""
    if MODE == "on":
        return True, "on"
    if MODE == "ab" and SHARE > 0 and conversation:
        on = int(hashlib.sha256(f"anchor:{conversation}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < SHARE
        return on, "ab:on" if on else "ab:off"
    return False, "off"
