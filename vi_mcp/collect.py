"""Collect mode of vi_recall (0.67.0): a question that wants many values about one entity ("what hardware does host X have") gets the
relevant chunks of every object about it, chosen under a token budget — not four hits.

The user decided (16.11.2026) that the memory recognises such questions itself. Measured on a production copy: 20 % of all objects are
parts of longer pages ("(part 2/3)", 3,387 pages, up to 159 parts), and the facts about one host are spread over several pages; top-k
returns about a quarter of a many-answer set even at k = 20 (QUEST 2305.11694, QAMPARI 2205.12665).

Steps (research VI erkenntnis:8200b28e…):
1. detect: the question names an entity that exists as a hashtag value (host:…) and either asks to collect ("hardware", "all",
   "which", "overview", …) or consists of little more than the entity — every decision is returned with its reason, so router accuracy
   can be measured;
2. candidates: the search hits ∪ every visible object carrying the entity hashtag (an exhaustive filter, not a ranking: single-vector
   retrieval cannot return complete sets, LIMIT 2508.21038; dense retrieval is weak on rare names, EntityQuestions 2109.08535);
3. group by page (data.source without its version suffix), parts in their order, chunked by `chunking`;
4. choose with `context_budget` (reranker per chunk, neighbours in the same section, a cap per page, chunks naming the entity first, cut
   at the largest score drop between a minimum and a maximum token budget), output in page order with […] for gaps;
5. name what was left out: per page the parts kept of all, and the counts with their reason.
The hashtag is noisy (pages that only mention a host carry it too), so nothing is taken unscored."""
from __future__ import annotations

import re
from typing import Any

from . import chunking, context_budget as cb, lexicon, memory as g, vector
#: words that ask for many values about the entity. English only: VIL is English, the standard language of the memory (user requirement,
#: 15.11.2026) — an agent asks the memory in English, whatever language its user speaks
INTENT = re.compile(r"\b(all|everything|which|what\s+do\s+you\s+know|overview|list|inventory|equipment|hardware|configuration|setup|"
                    r"details?|profile|summary)\b", re.I)
#: tokens that look like entity names: letters and digits mixed, optionally with a domain (host7, host7.example.org)
TOKEN = re.compile(r"\b([a-z][a-z0-9_-]*\d[a-z0-9_-]*(?:\.[a-z0-9-]+)*)\b", re.I)
STOP = {"the", "a", "an", "of", "on", "in", "at", "for", "is", "are", "has", "have", "does", "do", "what", "how", "about", "to", "and",
        "with", "from", "by", "run", "runs", "running"}
PART = re.compile(r"\((?:Teil|part|Text-Teil|Anhang-Teil)\s+(\d+)\s*/\s*(\d+)\)", re.I)

MIN_TOKENS, MAX_TOKENS, PAGE_CORE, MAX_PIECES = 1500, 8000, 3, 240
BROAD, BROAD_TOP = 300, 100  # an entity with more objects than BROAD contributes only its BROAD_TOP objects matching the question
RELATED_KINDS = ("host", "app", "service", "location")


def entity_tags(text: str) -> list[str]:
    """Hashtags (kind:value) of the entities the text names that a collect question can be about — from the VIL domain lexicon (host,
    location, service, app, project), e.g. host7 → host:host7.example.org, SITE-1 → location:SITE-1."""
    return [e["tag"] for e in lexicon.link(text, lexicon.COLLECT_KINDS)]


def detect(filter_text: str) -> dict[str, Any] | None:
    """The router: None for a single-fact search, else {entities, reason}."""
    if not filter_text:
        return None
    ents = entity_tags(filter_text)
    if not ents:
        return None
    intent = INTENT.search(filter_text)
    named = {w for t in ents for w in lexicon.normalize(t.split(":", 1)[1]).split()} | {t.split(":", 1)[1].split(".")[0].lower() for t in ents}
    rest = [w for w in lexicon.normalize(filter_text).split() if w not in STOP and w not in named and not TOKEN.fullmatch(w)]
    if intent:
        return {"entities": ents, "reason": f"entity {', '.join(ents)} with collect intent “{intent.group(0)}”"}
    if len(rest) <= 1:
        return {"entities": ents, "reason": f"the question is the entity {', '.join(ents)} itself"}
    return None


def _page_key(o) -> str:
    src = str(o.data.get("source") or "").split(" · ")[0].strip()
    return src or o.id


def _part(o) -> tuple[int, int]:
    m = PART.search(o.text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _title(o) -> str:
    t = PART.sub("", (o.text or "").split(" – ")[0]).strip(" :")
    return t[:120]


def collect(query_words: str, hits: list, decision: dict[str, Any], *, min_tokens: int = MIN_TOKENS, max_tokens: int = MAX_TOKENS,
            per_page: int = PAGE_CORE, only_indexes: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    """The collected context for the question and its counts. `hits`: the search's (score, object, weights). only_indexes (0.70.1): the
    index:<name> conditions of the question — the entity's objects come only from there, as the search's hits do."""
    counts: dict[str, Any] = {"entities": decision["entities"], "reason": decision["reason"]}
    within = " ".join(f"index:{i}" for i in only_indexes or [])
    entity_ids: list[str] = []
    for tag in decision["entities"]:
        entity_ids += [i for i in g.ids_for_filter(f"{within} {tag}".strip()) if i not in entity_ids]
    counts["objects_with_entity_tag"] = len(entity_ids)
    counts["related"] = related(entity_ids, decision["entities"])
    if len(entity_ids) > BROAD:
        # a broad entity (a site carries ~1,400 objects, mostly monitoring findings): only its objects that also match the question —
        # full text inside the entity hashtag ranks them; the rest is counted and named, never scored blindly (probe, 16.11.2026)
        words = " ".join(w for w in re.findall(r"[\wäöüß-]+", query_words) if w.lower() not in STOP)
        inside: list[str] = []
        for tag in decision["entities"]:
            inside += [o.id for _s, o, _w in g.recall(f"{within} {tag} {words}".strip(), limit=BROAD_TOP, or_fallback=True) if o.id not in inside]
        by_question = len(inside)
        if len(inside) < BROAD_TOP:  # no or few words of the question inside the entity: its most recent and important objects fill up
            for tag in decision["entities"]:
                inside += [o.id for _s, o, _w in g.recall(f"{within} {tag}".strip(), limit=BROAD_TOP) if o.id not in inside][:BROAD_TOP - len(inside)]
        counts["broad_entity"] = {"objects": len(entity_ids), "kept_by_question": by_question, "filled_by_recency": len(inside) - by_question}
        entity_ids = inside
    order = [o.id for _s, o, _w in hits] + [i for i in entity_ids if i not in {o.id for _s, o, _w in hits}]
    objs = g.load_many(order)
    pages: dict[str, list] = {}
    for oid in order:  # pages in the order of their best object: search rank first, then the entity's other objects
        if oid in objs:
            pages.setdefault(_page_key(objs[oid]), []).append(objs[oid])
    counts["pages"] = len(pages)
    pieces: list[cb.Piece] = []
    texts: dict[int, list[str]] = {}
    meta: dict[int, dict[str, Any]] = {}
    for entry, (key, parts) in enumerate(pages.items()):
        parts.sort(key=lambda o: _part(o)[0])
        title = _title(parts[0])
        own: list[str] = []
        for o in parts:
            content = str(o.data.get("content") or "").strip() or o.text
            for c in chunking.chunk_markdown(title, content):
                own.append(c.text)
        texts[entry] = own
        n_parts = max((_part(o)[1] for o in parts), default=0)
        meta[entry] = {"title": title, "source": key, "ids": [o.id for o in parts], "parts_here": len(parts), "parts_total": n_parts}
        for pos, t in enumerate(own):
            pieces.append(cb.Piece(entry, pos, t, cb.section_of(t)))
    counts["chunks"] = len(pieces)
    if len(pieces) > MAX_PIECES:  # pages are in rank order, so the tail is the least relevant; counted, never silent
        counts["chunks_not_scored"] = len(pieces) - MAX_PIECES
        pieces = pieces[:MAX_PIECES]
    if not pieces:
        return "", counts
    try:
        scores = vector.rerank_scores(query_words, [p.text for p in pieces]) if vector.rerank_available() else None
        counts["scored_by"] = "reranker" if scores is not None else "word overlap"
    except Exception as ex:  # noqa: BLE001 — the collect mode must never cost the answer: word overlap, named
        scores, counts["scored_by"] = None, f"word overlap (reranker failed: {type(ex).__name__})"
    if scores is None:
        q = set(re.findall(r"\w+", query_words.lower())) - STOP
        scores = [len(q & set(re.findall(r"\w+", p.text.lower()))) for p in pieces]
    # a chunk naming the entity goes first: a host by its first label, other entities by their normalised value
    names = {lexicon.normalize(t.split(":", 1)[1].split(".")[0] if t.startswith("host:") else t.split(":", 1)[1])
             for t in decision["entities"]}
    forced = {i for i, p in enumerate(pieces) if any(f" {n} " in f" {lexicon.normalize(p.text)} " for n in names if n)}
    header_tokens = {e: cb.estimate_tokens(f"{m['title']} {m['source']}") + 8 for e, m in meta.items()}
    sel = cb.select(pieces, scores, header_tokens, min_tokens=min_tokens, max_tokens=max_tokens, per_entry_core=per_page, forced=forced)
    counts.update(tokens=sel.tokens, dropped=sel.dropped, pages_kept=len(sel.keep))
    # for the agent's follow-up question: the pages not shown, by title and first object id
    best: dict[int, float] = {}
    for p, s in zip(pieces, scores):
        best[p.entry] = max(best.get(p.entry, float("-inf")), s)
    counts["pages_left_out"] = [(meta[e]["title"], meta[e]["ids"][0])
                                for e in sorted((e for e in meta if e not in sel.keep), key=lambda e: -best.get(e, float("-inf")))]
    out: list[str] = []
    for n, entry in enumerate(sorted(sel.keep), 1):
        m = meta[entry]
        kept = sel.keep[entry]
        parts = f"parts {m['parts_here']} of {m['parts_total']} found" if m["parts_total"] else "one object"
        out.append(f"[{n}] {m['title']} · {m['source']} · {', '.join(m['ids'][:4])}{' …' if len(m['ids']) > 4 else ''} · "
                   f"{len(kept)} of {len(texts[entry])} chunks · {parts}\n{cb.render(texts[entry], kept)}")
    return "\n\n".join(out), counts


def related(ids: list[str], entities: list[str], top: int = 15) -> dict[str, list[tuple[str, int]]]:
    """The structured answer to a list question ("which hosts are at site X"): the other entities that occur together with it, per kind,
    with the number of the entity's (visible) objects they occur in — straight from the hashtags, no text read."""
    out: dict[str, list[tuple[str, int]]] = {}
    cnt: dict[str, int] = {}
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        marks = ",".join("?" * len(part))
        with g.lock:
            for tag, n in g.db().execute(f"SELECT tag, COUNT(*) FROM tag WHERE object_id IN ({marks}) GROUP BY tag", part):
                cnt[tag] = cnt.get(tag, 0) + n
    for kind in RELATED_KINDS:
        rows = sorted(((t, n) for t, n in cnt.items() if t.startswith(kind + ":") and t not in entities), key=lambda x: -x[1])
        if rows:
            out[kind] = rows[:top] + ([("…", len(rows) - top)] if len(rows) > top else [])
    return out


def note(counts: dict[str, Any]) -> str:
    """One line on what the collect mode did and left out (nothing disappears silently)."""
    d = counts.get("dropped") or {}
    left = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in d.items() if v)
    extra = f", {counts['chunks_not_scored']} chunks of the last pages not scored" if counts.get("chunks_not_scored") else ""
    b = counts.get("broad_entity")
    broad = (f"; a broad entity ({b['objects']} objects): its {b['kept_by_question']} objects matching the question were gathered"
             + (f", {b['filled_by_recency']} more by recency" if b.get("filled_by_recency") else "") if b else "")
    rel = "".join(f"\nwith it — {k}: " + ", ".join(f"{t.split(':', 1)[1] if t != '…' else '…'} ({n})" for t, n in rows)
                  for k, rows in (counts.get("related") or {}).items())
    return (f"collect mode ({counts['reason']}): {counts.get('pages_kept', 0)} of {counts['pages']} pages, "
            f"{counts.get('tokens', 0)} tokens, {counts['objects_with_entity_tag']} objects carry the entity hashtag, chunks scored by "
            f"{counts.get('scored_by', '–')}" + (f"; left out: {left}" if left else "") + extra + broad + rel + follow_up(counts))


def follow_up(counts: dict[str, Any]) -> str:
    """0.67.0: the agent searches on with follow-up questions (as IT-AIKB's deepsearch does) — so the answer names its next steps instead
    of leaving them to a guess: the pages not shown, the full content of a page, and the entity filter for every object about it."""
    steps = []
    gone = counts.get("pages_left_out") or []
    if gone:
        steps.append("pages not shown: " + "; ".join(f"{t} ({i})" for t, i in gone[:5]) + (f" (+{len(gone) - 5})" if len(gone) > 5 else ""))
    steps.append("vi_object <id> reads a page's object in full")
    if counts.get("entities"):
        steps.append(f"vi_recall(\"{' '.join(counts['entities'][:2])}\", collect=false, limit=50) lists all "
                     f"{counts.get('objects_with_entity_tag', 0)} objects of the entity")
    steps.append("a narrower follow-up question (one aspect: e.g. disks, network, services) gets its chunks first")
    return "\nfollow-up: " + " · ".join(steps)
