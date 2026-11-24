"""The domain lexicon of VIL (0.67.0): the entity words of the memory, so VIL is a technical language and not only a query syntax.

The user asked (16.11.2026) to take more words — entities — into VIL, since it is meant to be a technical language. The words are already in
memory as hashtag values: hosts, sites, monitored services, applications, error keys, projects, areas, networks. The lexicon reads them
(with their counts), cleans out what is not a name (file paths that a host extractor tagged as host:), and links a free-text question to
them: "which hosts are at SITE-1?" → location:SITE-1; "hardware of web1" → host:web1.<domain>.

Linking never changes the search order (every reordering measured so far lowered MRR, VI erkenntnis:30ccfa8b…); it names the entities
the question is about — in the search note, and for the collect mode, which gathers everything about one of them."""
from __future__ import annotations

import re
import threading
import time

from . import memory as g

#: entity kinds of the lexicon (stored hashtag kinds, English since 0.67.0) and what a value of each names
KINDS = {
    "host": "a machine, by its fully qualified name; a question may name its first label (web1 for web1.example.org)",
    "location": "a site code (e.g. SITE-1)",
    "service": "a monitored service or check",
    "app": "an application or its instance",
    "project": "a project",
    "area": "an area of the documentation (team, site or product)",
    "net": "a network zone (dmz, intern)",
    "error": "a normalised error key",
}
#: kinds whose entity a collect question can gather everything about; area, net and error name thousands of objects
COLLECT_KINDS = ("host", "location", "service", "app", "project")
_HOST = re.compile(r"[a-z0-9][a-z0-9.-]*[a-z0-9]")
_MIN_LEN = 3
_MIN_ERROR_LEN = 8
#: everyday words that are never read as a host name, even where a host of that name exists (English: VIL is English)
_WORDS = {"which", "where", "there", "about", "hosts", "server", "servers", "hardware", "equipment", "problems", "error", "errors",
          "timeout", "backup", "update", "status", "service", "services", "running", "located"}
TTL_S = 300.0
_cache: dict = {"at": 0.0, "db": None, "data": None}


def normalize(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^\w.# ]+", " ", s)
    return " ".join(s.split())


def _load() -> dict:
    data: dict = {"values": {}, "hosts": {}, "first_label": {}, "rejected": {}}
    for kind in KINDS:
        with g.reading() as con:  # 24.11.2026: a read connection beside the writer
            rows = con.execute("SELECT tag, COUNT(*) FROM tag WHERE tag LIKE ? GROUP BY tag", (f"{kind}:%",)).fetchall()
        for tag, n in rows:
            value = tag.split(":", 1)[1]
            if kind == "host":
                if not _HOST.fullmatch(value):
                    data["rejected"][kind] = data["rejected"].get(kind, 0) + 1  # e.g. a file path tagged as host — not a name
                    continue
                data["hosts"][value] = (tag, n)
                label = value.split(".")[0]
                if len(label) >= 4 and "." in value:
                    data["first_label"].setdefault(label, []).append((tag, n))
                continue
            nv = normalize(value).replace("#", "").strip()
            # an error key as short as an everyday word ("timeout") would link every question that uses the word (probe, 16.11.2026)
            if len(nv) < (_MIN_ERROR_LEN if kind == "error" else _MIN_LEN) or nv.replace(" ", "").isdigit():
                data["rejected"][kind] = data["rejected"].get(kind, 0) + 1
                continue
            data["values"].setdefault(kind, {})[nv] = (tag, n)
            if "." in value and kind != "error":  # fully qualified like a host (app instances): its first label names it too
                label = normalize(value.split(".")[0])
                if len(label) >= 4:
                    data["values"][kind].setdefault(label, (tag, n))
    return data


#: 24.11.2026: one rebuild at a time; while it runs, the other searches use the lexicon they had (same database) instead of waiting —
#: on expiry every concurrent vi_recall rebuilt it with full GROUP BY scans of the tag table (14 threads at once on a production copy)
_build = threading.Lock()


def lexicon() -> dict:
    """The lexicon of the open memory, rebuilt after TTL_S seconds or when another database is open."""
    # keyed by the database itself, not by id(): Python reuses the address of a closed connection, so a new database looked like the
    # old one and the cache answered with its words (found by the test suite, 16.11.2026)
    db = (str(getattr(g, "fpath_active", "") or ""), id(g.db()))
    fresh = lambda: _cache["data"] is not None and _cache["db"] == db and time.monotonic() - _cache["at"] <= TTL_S  # noqa: E731
    if fresh():
        return _cache["data"]
    same_db = _cache["data"] is not None and _cache["db"] == db
    if not _build.acquire(blocking=not same_db):
        return _cache["data"]  # another search is rebuilding it: the previous lexicon of this database meanwhile
    try:
        if not fresh():
            _cache.update(at=time.monotonic(), db=db, data=_load())
    finally:
        _build.release()
    return _cache["data"]


def clear() -> None:
    _cache.update(at=0.0, db=None, data=None)


def link(text: str, kinds: tuple[str, ...] | None = None) -> list[dict]:
    """The entities a free text names: [{kind, value, tag, count}], longest first, each tag once."""
    lx = lexicon()
    kinds = kinds or tuple(KINDS)
    found: dict[str, dict] = {}
    if "host" in kinds:
        for tok in dict.fromkeys(t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]", text or "")):
            # a short word without a digit is language, not a host name (a two- or three-letter word matched a host of that first label, probe 16.11.2026)
            if tok in _WORDS or (len(tok) < 5 and "." not in tok and not any(ch.isdigit() for ch in tok)):
                continue
            exact = lx["hosts"].get(tok)
            cands = [exact] if exact else [v for k, v in lx["hosts"].items() if k.startswith(tok + ".")]
            if not cands and tok in lx["first_label"]:
                cands = lx["first_label"][tok]
            if not cands and not exact and any(ch.isdigit() for ch in tok):
                cands = [v for k, v in lx["hosts"].items() if k.split(".")[0] == tok]
            for tag, n in cands[:5]:
                found[tag] = {"kind": "host", "value": tag.split(":", 1)[1], "tag": tag, "count": n}
    padded = f" {normalize(text)} "
    for kind in kinds:
        if kind == "host":
            continue
        for nv, (tag, n) in sorted(lx["values"].get(kind, {}).items(), key=lambda kv: -len(kv[0])):
            if f" {nv} " in padded and tag not in found:
                found[tag] = {"kind": kind, "value": tag.split(":", 1)[1], "tag": tag, "count": n}
    # the lexicon is built from every object's hashtags; a name counts only if the asking instance can see an object carrying it —
    # otherwise the search note would tell it a private or internal host name it may not read
    visible = [e for e in found.values() if g.ids_for_filter(e["tag"])[:1]]
    return sorted(visible, key=lambda e: (-len(e["value"]), e["tag"]))


def describe() -> str:
    """The lexicon in one paragraph (vi_vocabulary, the manual): kinds, how many words each, what was rejected and why."""
    lx = lexicon()
    parts = [f"host ({len(lx['hosts'])})"] + [f"{k} ({len(lx['values'].get(k, {}))})" for k in KINDS if k != "host"]
    rej = ", ".join(f"{n} {k}" for k, n in lx["rejected"].items())
    return ("VIL domain lexicon — entity words from the memory's hashtags: " + ", ".join(parts)
            + (f"; not names, left out: {rej} (paths tagged as host, numbers, values under {_MIN_LEN} characters, error keys under {_MIN_ERROR_LEN})" if rej else ""))
