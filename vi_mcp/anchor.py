"""0.72.0: title anchor + one mention hop for vi_recall (goal Z6), switch `search_anchor`: auto (default) = on iff the release's gate passed.

Default auto: on exactly when the offline gate shipped with the release passed (`GATE`; user decision 25.11.2026).

A question that names a host is often about two pages: the host's own documentation page and the page of a host it mentions (a VM and
its Proxmox node). Plain hybrid search finds the first and rarely the second (PREREG_Z6, 22.11.2026, 846 test questions: both pages in
the top 4 for 6.4 %). Method M1 of that study reached 81.1 %:
  1. title index: every documentation page (`insight:doc-…`, text "LABEL: title — …") is keyed by the host names in its TITLE (fully
     qualified, at least three labels); a short name (first label) is a key only when it contains a digit — hosts here are named like
     web0042, everyday words like "system" were titles' first labels (found on development data);
  2. anchor = the page whose title names a host the question names (the shortest such title);
  3. hop = the pages titled with the OTHER hosts the anchor's text names, in order of first mention;
  4. anchor and hops are placed after the hybrid list's first `AT` hits (how many hops and where: `HOPS`, `AT`, chosen on
     development data only).
Unlike the study's script (which read the database directly), every anchor and hop passes the search's own filter and visibility
(`memory.admitted`: the viewer, the index searched alone, scoped indexes, mode), and pages of search-scoped indexes (named only,
external) are not in the title index — an external corpus is never a hint, and an anchor is placed like one.
Modes: auto (default: on exactly when GATE["state"] == "passed") · off (switched off: config and restart) · on (forced) · ab (a share
of conversations, by a hash of the conversation serial, so one conversation keeps one arm).
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

from . import memory as g

MODE = "auto"  # config search_anchor: auto | on | off | ab
SHARE = 0.0  # config search_anchor_share: with ab, the share of conversations that get the anchor (at most 0.5)
#: how many hop pages follow the anchor (chosen on development data, 25.11.2026: Z6 dev both@4 1 hop 84.5 %, 2 hops 85.1 %, 5 hops
#: 85.0 %; recall.json dev half equal for 1 and 2 — the second hop adds 5 of 826 and puts one more page before the hybrid hits)
HOPS = 1
#: where the anchor group goes: after the hybrid list's first AT hits, which keep their places (chosen on development data, 25.11.2026:
#: AT 0 cost recall.json dev Hit@1 41.7 → 40.3 % — the anchor took rank 1 from a correct hit; AT 1 keeps Hit@1 by construction and
#: gives the same Z6 dev both@4, 84.5 %)
AT = 1
#: hop pages considered per anchor (the study's limit)
HOPS_MAX = 5
CACHE_S = 300.0
#: measurement only (development data, the gate): a list → every hybrid search appends {query, ranked (before the anchor), plan}
CAPTURE: list | None = None
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]")
#: a host name: at least three labels, the last one alphabetic — not a version number (3.1.0) or an IP address (found on the
#: recall.json development half: "3.1.0", "08", "100" had become title keys)
FQDN = re.compile(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+\.[a-z]{2,}(?![a-z0-9\-])")
DOC_PREFIXES = ("insight:doc-", "erkenntnis:doc-")  # 0.67.0 renamed the id prefix; old ids stay valid

#: The offline gate's result (PREREG_Z6_GATE), fixed in the release that ships the switch: pending | passed | failed. With the default
#: mode auto this alone decides whether the anchor is on (user decision 25.11.2026: "automatic once the gate passes"); vi_stats and the
#: start-up log name the switch, its effective state, since when, and the gate.
#: PREREG_Z6_GATE (frozen 2026-11-25 18:07:45 UTC, sha256 3deb3738…a26), run 18:07–19:29 UTC on a fresh copy of the production database
#: of 22.11.2026 with commit 13e5f92: switch check 20/20; recall.json gate half (160 queries, page level) Hit@4 36.25 → 36.25 % and
#: Hit@1 25.0 → 25.0 % (no query won or lost); Z6 dev both@4 14.41 → 84.62 % (826, 581 won, 1 lost); 6 of 188 real agent searches
#: got an anchor. Result sha256 c138208a…cfa6.
GATE = {"state": "passed", "date": "2026-11-25",
        "summary": "Z6 both@4 14.4 → 84.6 %, recall Hit@4 36.3 → 36.3 % and Hit@1 25.0 → 25.0 % (PREREG_Z6_GATE)"}

_cache: dict = {"at": 0.0, "db": None, "index": {}}
_build = threading.Lock()


def _state_table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS anchor_state (id INTEGER PRIMARY KEY, mode TEXT NOT NULL, share REAL NOT NULL, "
                       "since TEXT NOT NULL)")
        g.db().commit()


def switch() -> str:
    """The effective switch: auto:on | auto:off | on | off | ab."""
    if MODE == "auto":
        return "auto:on" if GATE.get("state") == "passed" else "auto:off"
    return MODE


def record_mode() -> dict:
    """At start-up: the effective switch, and since when it is so (a change of it or of the share starts a new period)."""
    _state_table()
    sw = switch()
    with g.lock:
        r = g.db().execute("SELECT mode, share, since FROM anchor_state WHERE id = 1").fetchone()
        if r and r[0] == sw and float(r[1]) == float(SHARE):
            return {"mode": r[0], "share": float(r[1]), "since": r[2]}
        now = g.now()
        if r:
            g.db().execute("UPDATE anchor_state SET mode = ?, share = ?, since = ? WHERE id = 1", (sw, SHARE, now))
        else:
            g.db().execute("INSERT INTO anchor_state (id, mode, share, since) VALUES (1, ?, ?, ?)", (sw, SHARE, now))
        g.db().commit()
    return {"mode": sw, "share": SHARE, "since": now}


def line() -> str:
    """One line for vi_stats and the start-up log: the switch, its effective state since when, and the offline gate's result."""
    _state_table()
    sw = switch()
    with g.lock:
        r = g.db().execute("SELECT mode, share, since FROM anchor_state WHERE id = 1").fetchone()
    since = f" since {r[2][:16]}" if r and r[0] == sw and float(r[1]) == float(SHARE) else ""
    state = GATE.get("state", "pending")
    gate = f"gate {state}" + (f" {GATE['date']}" if GATE.get("date") else "") + (f": {GATE['summary']}" if GATE.get("summary") else "")
    if sw == "auto:on":
        text = f"auto → on{since} ({gate})"
    elif sw == "auto:off":
        text = f"auto → off{since} ({gate})"
    elif sw == "off":
        text = f"off{since} (switched off in the config; {gate}) — search_anchor = \"auto\" follows the gate"
    elif sw == "on":
        text = f"on{since} (forced in the config; {gate})" + ("" if state == "passed" else f" — WARNING: on although the offline gate is {state}")
    else:
        text = f"ab, share {SHARE:g}{since} ({gate})"
    return f"    search anchor (0.72.0, goal Z6): {text}"


def _keys(title: str) -> list[str]:
    """Host keys a page title gives: each fully qualified name, and its first label only when that contains a digit and a letter
    (web0042 — not "system", not "08"). Pure."""
    out = []
    for h in FQDN.findall(title.lower()):
        short = h.split(".")[0]
        out += [h, short] if any(c.isdigit() for c in short) and any(c.isalpha() for c in short) else [h]
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


def place(ranked: list[str], planned: list[dict], hops: int | None = None, at: int | None = None) -> list[str]:
    """Anchors, each followed by its first `hops` hop pages (default HOPS), placed after the hybrid list's first `at` hits (default
    AT; 0 = in front); no id twice. Pure."""
    n = HOPS if hops is None else hops
    k = AT if at is None else at
    group: list[str] = []
    for p in planned:
        for i in [p["anchor"], *p["hops"][:n]]:
            if i not in group:
                group.append(i)
    if not group:
        return list(ranked)
    head = list(ranked[:k])  # the hybrid's first k hits keep their places, whatever they are (also an anchor or hop page)
    group = [i for i in group if i not in head]
    return head + group + [i for i in ranked[k:] if i not in group]


def active(conversation: str | None) -> tuple[bool, str]:
    """Whether this search gets the anchor, and the arm named in the search note: (on?, "on"|"auto"|"off"|"ab:on"|"ab:off")."""
    if MODE == "on":
        return True, "on"
    if MODE == "auto":
        return (True, "auto") if GATE.get("state") == "passed" else (False, "off")
    if MODE == "ab" and SHARE > 0 and conversation:
        on = int(hashlib.sha256(f"anchor:{conversation}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < SHARE
        return on, "ab:on" if on else "ab:off"
    return False, "off"
