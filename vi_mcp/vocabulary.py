"""The vocabulary of the memory (0.62.0) — "what is there, what can I search?" before searching.

The user (13.11.2026): "bekannte Vokabeln in der DB suchen und daraus eine Frage formulieren, wie eine Autovervollständigung bei einer
Suche. Zuerst: Was gibt es und was kann ich suchen? Und dann etwas suchen."

The words of the search language are the hashtags `kind:value` the memory holds. This module counts them — always over what the asking
instance may see (memory._filter_sql: shared, internal with a token, its own private; never someone else's private object, quarantine or
archive), so a word never betrays an object its asker could not open.

- kinds(): the kinds with the number of distinct values and of objects;
- values(kind, prefix): the values of one kind, most frequent first;
- complete(text): completion of a half-typed word — kinds, values of a kind, or values of any kind that start with the text;
- unknown_terms(filter): the hashtag terms of a search that no visible object carries, with "did you mean" suggestions. A search without
  hits is then classified: `unbekannt` (it asked for a word the memory does not know — "nothing known" is the right answer) or
  `verfehlt` (every word is known, but nothing matches them together — a search problem). Measured on production on 13.11.2026: all 111
  searches without hits asked for hosts the memory did not know; the old single rate of 26 % mixed both.
"""
from __future__ import annotations

import difflib

from . import memory as g

#: kinds that are bookkeeping, not vocabulary (instance names, serials, cache keys …); `art:` stays — it is the kind of object
HIDDEN = tuple(p for p in g.ADMIN_PREFIXES if p != "art:")
MAX_CANDIDATES = 5000


def _visible(viewer: str | None) -> tuple[str, list]:
    return g._filter_sql([], [], viewer)


def _like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _shown(tag: str) -> bool:
    return not tag.startswith(HIDDEN)


def kinds(viewer: str | None = "aktuell", limit: int = 60) -> list[tuple[str, int, int]]:
    """(kind, distinct values, objects) for the kinds the viewer can see, most used first."""
    viewer = g.current_instance.get() if viewer == "aktuell" else viewer
    vis, par = _visible(viewer)
    with g.lock:
        rows = g.db().execute(
            f"SELECT substr(tag, 1, instr(tag, ':') - 1) AS k, COUNT(DISTINCT tag), COUNT(*) FROM tag WHERE objekt_id IN ({vis}) "
            "GROUP BY substr(tag, 1, instr(tag, ':') - 1) ORDER BY COUNT(*) DESC", par).fetchall()
    return [(k, int(nv), int(no)) for k, nv, no in rows if k and _shown(k + ":")][:limit]


def values(kind: str, prefix: str = "", viewer: str | None = "aktuell", limit: int = 30) -> list[tuple[str, int]]:
    """(kind:value, objects) of one kind, values starting with `prefix`, most used first."""
    viewer = g.current_instance.get() if viewer == "aktuell" else viewer
    kind = kind.strip().rstrip(":")
    if not kind or not _shown(kind + ":"):
        return []
    vis, par = _visible(viewer)
    with g.lock:
        rows = g.db().execute(f"SELECT tag, COUNT(*) FROM tag WHERE tag LIKE ? ESCAPE '\\' AND objekt_id IN ({vis}) "
                              "GROUP BY tag ORDER BY COUNT(*) DESC, tag LIMIT ?", (_like(f"{kind}:{prefix}"), *par, int(limit))).fetchall()
    return [(t, int(n)) for t, n in rows]


def complete(text: str, viewer: str | None = "aktuell", limit: int = 20) -> list[tuple[str, int]]:
    """Completions of a half-typed word: `host:llam` → values of host; `ho` → kinds starting with it and values of any kind starting with it."""
    viewer = g.current_instance.get() if viewer == "aktuell" else viewer
    t = (text or "").strip().lstrip("!(#@")
    if ":" in t:
        k, _, v = t.partition(":")
        return values(k, v, viewer, limit)
    out = [(f"{k}:", n) for k, _nv, n in kinds(viewer, 200) if k.startswith(t.lower())]
    if t:
        vis, par = _visible(viewer)
        with g.lock:
            rows = g.db().execute(f"SELECT tag, COUNT(*) FROM tag WHERE substr(tag, instr(tag, ':') + 1) LIKE ? ESCAPE '\\' AND objekt_id IN ({vis}) "
                                  "GROUP BY tag ORDER BY COUNT(*) DESC LIMIT ?", (_like(t), *par, int(limit) * 3)).fetchall()
        out += [(tag, int(n)) for tag, n in rows if _shown(tag)]
    return out[:limit]


def _terms(filter_text: str) -> list[str]:
    """The positive, exact hashtag terms of a filter (prefix terms `kind:val*` are completions, not words)."""
    groups, _remove, _words = g.parse_filter(filter_text or "", g.known_kinds() | {t.split(":")[0] for t in (filter_text or "").split() if ":" in t})
    return [t for grp in groups for t in grp if ":" in t and not t.endswith("*")]


def unknown_terms(filter_text: str, viewer: str | None = "aktuell") -> list[tuple[str, list[str]]]:
    """(term, up to 3 suggestions) for every hashtag term of the filter that no object visible to the viewer carries."""
    viewer = g.current_instance.get() if viewer == "aktuell" else viewer
    vis, par = _visible(viewer)
    out = []
    for term in dict.fromkeys(_terms(filter_text)):
        with g.lock:
            known = g.db().execute(f"SELECT 1 FROM tag WHERE tag = ? AND objekt_id IN ({vis}) LIMIT 1", (term, *par)).fetchone()
        if known:
            continue
        kind, _, val = term.partition(":")
        pool = [t.partition(":")[2] for t, _n in values(kind, "", viewer, MAX_CANDIDATES)]
        out.append((term, [f"{kind}:{v}" for v in suggest(val, pool)]))
    return out


def suggest(value: str, pool: list[str], n: int = 3) -> list[str]:
    """Close values, judged by the part that tells them apart: host names share their domain ("web3.example" is not close to
    "db1.example" because both end in .example), so the first label decides, the whole value only breaks ties. `pool` is ordered by
    use; equal scores keep that order."""
    def head(v: str) -> str:
        return v.split(".", 1)[0]
    scored = []
    for i, c in enumerate(pool):
        h = difflib.SequenceMatcher(None, head(value), head(c)).ratio()
        whole = difflib.SequenceMatcher(None, value, c).ratio()
        if h >= 0.6 and whole >= 0.6:
            scored.append((-h, -whole, i, c))
    return [c for *_k, c in sorted(scored)[:n]]


def empty_reason(filter_text: str, viewer: str | None = "aktuell") -> tuple[str, list[tuple[str, list[str]]]]:
    """Why a search found nothing: ('unbekannt', unknown terms) — it asked for words the memory does not know, or free text of which no
    word occurs (the full-text search falls back to OR, so none matched); ('verfehlt', []) — the words are known, not together."""
    unknown = unknown_terms(filter_text, viewer)
    if unknown:
        return "unbekannt", unknown
    groups, _remove, words = g.parse_filter(filter_text or "", g.known_kinds())
    if words and not groups:
        return "unbekannt", []
    return "verfehlt", []


def lines(prefix: str = "", kind: str = "", viewer: str | None = "aktuell", limit: int = 30) -> list[str]:
    """For vi_vocabulary: kinds (no argument), values of a kind, or completions of a prefix."""
    if kind:
        rows = values(kind, prefix, viewer, limit)
        head = f"values of {kind}:" + (f" starting with “{prefix}”" if prefix else "") + " (objects you can see)"
        if not rows:
            return [f"no values of {kind}:{prefix}… — vi_vocabulary without arguments lists the kinds"]
        from . import word_weights
        out = [head + " · weight = measured success after showing knowledge with this word (own and from the network)"]
        for t, n in rows:
            c = word_weights.combined(t)
            y, no = c["eigen"]
            out.append(f"  {t}  ({n})" + (f"  · weight {c['gewicht']} ({int(y + no)} ratings" + (f", {c['netz']} server(s)" if c["netz"] else "") + ")"
                                         if y + no or c["netz"] else ""))
        return out
    if prefix:
        rows = complete(prefix, viewer, limit)
        return [f"completions of “{prefix}” (objects you can see):"] + [f"  {t}  ({n})" for t, n in rows] if rows else [f"nothing starts with “{prefix}”"]
    rows = kinds(viewer, limit)
    return (["kinds of words — kind (distinct values, objects); vi_vocabulary(word_kind=…) shows the values, prefix=… completes:"]
            + [f"  {k}:  ({nv} values, {no} objects)" for k, nv, no in rows])
