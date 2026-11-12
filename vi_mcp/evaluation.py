"""Evaluation (0.55.0) — a fixed measuring instrument for the search, so every change to it is measured before it stays.

Taken over from it-aikb (eval/retrieval_ab.py): a question set with a known target, judged at PAGE level — several objects can come
from one source page (a Confluence page imported in parts); a hit on any of them counts. Metrics per query (scikit-learn user guide,
model_evaluation): reciprocal rank (MRR), Hit@1/5/10 and nDCG@10 with one relevant page (gain 1 / log2(rank + 1)).

A question file is a JSON list of {"frage", "stichworte", "target", "group", "stratum"}: the natural question and the keywords are two
query styles for the same target. The file holds internal content and never belongs into the repository; `vi-mcp eval generate`
writes it next to the database.

A search variant is a function (query, limit) -> list of object ids, in rank order. The variants here only read: no hit is
reinforced (a measurement must not change what it measures, 0.31.0).
"""
from __future__ import annotations

import json
import math
import re
import statistics
import time
from pathlib import Path
from typing import Callable

from . import memory as g

LIMIT = 10
STYLES = ("frage", "stichworte")
_ID = re.compile(r"\[([a-z]+:[0-9a-z][0-9a-z_-]*)\]")


def group_of(o: g.MemoryObject) -> str:
    """The source page of an object: its source URL without the version suffix (" · Version 3 …"), else the object itself."""
    q = str(o.data.get("quelle") or "").strip()
    return q.split(" · ")[0] if q.startswith("http") else o.id


def page_ranking(ids: list[str]) -> list[str]:
    """Object ids in rank order → source pages in rank order, each page once (its best part counts)."""
    objects = g.load_many(ids)
    out: list[str] = []
    for oid in ids:
        o = objects.get(oid)
        grp = group_of(o) if o else oid
        if grp not in out:
            out.append(grp)
    return out


def query_metrics(pages: list[str], target: str) -> dict:
    """Metrics of one query with one relevant page. Pure."""
    rank = pages.index(target) + 1 if target in pages[:LIMIT] else None
    return {"rang": rank, "rr": 1.0 / rank if rank else 0.0, "hit1": rank == 1, "hit5": bool(rank and rank <= 5),
            "hit10": bool(rank), "ndcg10": 1.0 / math.log2(rank + 1) if rank else 0.0}


def fulltext(query: str, limit: int = LIMIT) -> list[str]:
    """vi_recall as it is called without semantic=true: full text (AND, filled up by OR) + recency + importance."""
    return [o.id for _s, o, _g in g.recall(query, limit=limit, or_fallback=True, viewer=None)]


def hybrid(query: str, limit: int = LIMIT) -> list[str]:
    """vi_recall(semantic=true) exactly as the tool runs it (meaning and full text by rank fusion)."""
    from . import tools
    text = tools.call_tool("vi_recall", {"filter": query, "semantic": True, "reinforce": False, "limit": limit}, g.SERVER_INSTANCE, False)
    return _ID.findall(text)[:limit]


VARIANTS: dict[str, Callable[[str, int], list[str]]] = {"fulltext": fulltext, "hybrid": hybrid}


def run(questions: list[dict], variant: Callable[[str, int], list[str]], styles: tuple[str, ...] = STYLES) -> dict:
    """All questions through one variant. Returns the summary (overall, per style, per stratum) and the rows per query."""
    rows = []
    for q in questions:
        if q.get("error") or not q.get("group"):
            continue
        for style in styles:
            query = str(q.get(style) or "").strip()
            if not query:
                continue
            t0 = time.monotonic()
            try:
                ids, err = variant(query, LIMIT), None
            except Exception as ex:  # noqa: BLE001 — a failing query is a measured failure, named in the row
                ids, err = [], f"{type(ex).__name__}: {ex}"[:200]
            ms = int((time.monotonic() - t0) * 1000)
            m = query_metrics(page_ranking(ids), q["group"])
            rows.append({"target": q.get("target"), "stratum": q.get("stratum", "-"), "style": style, "query": query, "ms": ms,
                         "index": _index_of_target(q.get("target")), **m, **({"fehler": err} if err else {})})
    return {"gesamt": summarize(rows), "je_stil": {s: summarize([r for r in rows if r["style"] == s]) for s in styles},
            "je_schicht": {s: summarize([r for r in rows if r["stratum"] == s]) for s in sorted({r["stratum"] for r in rows})},
            "je_index": _per_index(rows), "zeilen": rows}


#: 0.61.0: a per-index figure needs this many queries, below it the index is named as too small
INDEX_MIN_QUERIES = 20


def _index_of_target(oid: str | None) -> str:
    o = g.load(oid) if oid else None
    return o.idx if o is not None else "global"


def _per_index(rows: list[dict]) -> dict:
    out = {}
    for ix in sorted({r.get("index", "global") for r in rows}):
        part = [r for r in rows if r.get("index", "global") == ix]
        out[ix] = summarize(part) if len(part) >= INDEX_MIN_QUERIES else {"zustand": "zu_wenig", "n": len(part),
                                                                         "urteil": f"{len(part)} queries — at least {INDEX_MIN_QUERIES} for a figure"}
    return out


def summarize(rows: list[dict]) -> dict:
    """Mean of each metric over the queries, with the number of queries and the latency median. Pure."""
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "mrr": round(statistics.mean(r["rr"] for r in rows), 3),
            "hit1": round(statistics.mean(r["hit1"] for r in rows), 3), "hit5": round(statistics.mean(r["hit5"] for r in rows), 3),
            "hit10": round(statistics.mean(r["hit10"] for r in rows), 3), "ndcg10": round(statistics.mean(r["ndcg10"] for r in rows), 3),
            "ms_median": int(statistics.median(r["ms"] for r in rows)), "fehler": sum(1 for r in rows if r.get("fehler"))}


def load_questions(path: Path | str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def table(results: dict[str, dict]) -> str:
    """Markdown table of several variants' summaries (overall and per style)."""
    lines = ["| variant | part | n | MRR | Hit@1 | Hit@5 | Hit@10 | nDCG@10 | ms median | errors |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, res in results.items():
        for part, s in [("all", res["gesamt"])] + [(k, v) for k, v in res["je_stil"].items()] + [(k, v) for k, v in res["je_schicht"].items()]:
            if s.get("n"):
                lines.append(f"| {name} | {part} | {s['n']} | {s['mrr']} | {s['hit1']} | {s['hit5']} | {s['hit10']} | {s['ndcg10']} | {s['ms_median']} | {s['fehler']} |")
    return "\n".join(lines)


# ── 0.55.0: the daily measurement in sleep ──────────────────────────────────────────────────────────────────────────────────────────
#: number of target objects in a question set (two queries each), at least EVAL_MIN before the first measurement
EVAL_N = 150
EVAL_MIN = 100
#: seconds of language-model time per sleep for writing questions — the rest follows in the next sleep (as vector.catch_up)
GEN_BUDGET_S = 300
#: one measurement a day: a sleep within this many hours of the last measurement skips the step (named)
EVERY_H = 20
#: replaceable for tests; default: next to the database (SQLite) or /var/lib/vi-mcp (PostgreSQL)
EVAL_DIR: Path | None = None
GEN_PROMPT = ("You build a test set for the search of an IT knowledge base. Below is one knowledge object. Write two search queries "
              "with which an IT administrator or an AI would look for exactly this knowledge without knowing it yet:\n"
              '1. "frage": one natural question, in the language of the object; in your own words, copy no sentence from it; product, '
              "host and error names are allowed when one would know them while searching.\n"
              '2. "stichworte": 2 to 4 keywords as typed into a search field.\nAnswer only with JSON: {"frage": "...", "stichworte": "..."}')
GEN_SCHEMA = {"type": "object", "properties": {"frage": {"type": "string"}, "stichworte": {"type": "string"}}, "required": ["frage", "stichworte"]}


def eval_dir() -> Path:
    if EVAL_DIR is not None:
        return Path(EVAL_DIR)
    fp = g.fpath_active
    return (Path(fp).parent if fp and not str(fp).startswith("postgres") else Path("/var/lib/vi-mcp")) / "eval"


def stratum(o: g.MemoryObject) -> str:
    """Where an object comes from: the host of its source URL (an import), else the instance that wrote it. Pure."""
    import urllib.parse
    q = str(o.data.get("quelle") or "")
    if q.startswith("http"):
        return "web:" + (urllib.parse.urlsplit(q.split(" · ")[0]).hostname or "?")
    return "own:" + (o.instance or "?")


def sample_targets(n: int, exclude: set[str], seed: int) -> list[g.MemoryObject]:
    """A stratified sample of shared knowledge (insights, rules, skills): each stratum in proportion to its size, at least 3 each."""
    import random
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill') AND modus = 'aktiv' "
                                            "AND length(text) >= 40")]
    objs = [o for o in g.load_many([i for i in ids if i not in exclude]).values()]
    by: dict[str, list] = {}
    for o in objs:
        by.setdefault(stratum(o), []).append(o)
    rnd = random.Random(seed)
    total = sum(len(v) for v in by.values()) or 1
    out = []
    for s, v in sorted(by.items()):
        out += rnd.sample(v, min(len(v), max(3, round(n * len(v) / total))))
    rnd.shuffle(out)
    return out[:n]


def generate(budget_s: float = GEN_BUDGET_S) -> dict:
    """Write questions for the sample until EVAL_N targets exist or the time budget is used; appends to the question file."""
    from . import reflection
    if not (reflection.config or {}).get("url") and reflection.ask_fn is None:
        return {"zustand": "uebersprungen", "grund": "no language model configured (config: llm)"}
    path = eval_dir() / "recall.json"
    have = load_questions(path) if path.exists() else []
    if len(have) >= EVAL_N:
        return {"zustand": "vollstaendig", "n": len(have)}
    t0, made, failed = time.monotonic(), 0, 0
    for o in sample_targets(EVAL_N - len(have), {q["target"] for q in have}, seed=len(have) + 1):
        if time.monotonic() - t0 > budget_s:
            break
        content = str(o.data.get("inhalt") or "")[:3000]
        try:
            m = reflection._json_from(reflection.question(GEN_PROMPT, f"{o.text}\n\n{content}",
                                                          response_format={"type": "json_schema", "json_schema": {"name": "frage", "schema": GEN_SCHEMA}}))
            s = lambda v: (" ".join(map(str, v)) if isinstance(v, list) else str(v or "")).strip()  # noqa: E731
            if not s(m.get("frage")) or not s(m.get("stichworte")):
                raise ValueError("empty question")
            have.append({"target": o.id, "group": group_of(o), "stratum": stratum(o), "frage": s(m["frage"]), "stichworte": s(m["stichworte"])})
            made += 1
        except Exception:  # noqa: BLE001 — counted, the object is tried again in a later sleep
            failed += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(have, ensure_ascii=False, indent=1), encoding="utf-8")
    path.chmod(0o600)  # internal content
    return {"zustand": "erzeugt", "neu": made, "fehlgeschlagen": failed, "n": len(have)}


def history(limit: int = 7) -> list[dict]:
    """The last daily measurements (newest last)."""
    p = eval_dir() / "verlauf.jsonl"
    if not p.exists():
        return []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[-limit:]]


def nightly(now: str | None = None) -> dict:
    """Sleep step 9_pruefung: once a day the question set (written in portions) through every available variant, plus the router's
    holdout numbers; one line per day in eval/verlauf.jsonl. Exhaustive states: heute_schon · fragen_fehlen · gemessen."""
    from datetime import datetime, timedelta
    from . import learning, metrics, vector
    now = now or g.now()
    last = history(1)
    if last and datetime.fromisoformat(now) - datetime.fromisoformat(last[-1]["zeit"]) < timedelta(hours=EVERY_H):
        return {"zustand": "heute_schon", "grund": f"measured {last[-1]['zeit'][:16]}, again after {EVERY_H} h"}
    gen = generate()
    path = eval_dir() / "recall.json"
    questions = load_questions(path) if path.exists() else []
    if len(questions) < EVAL_MIN:
        return {"zustand": "fragen_fehlen", "fragen": len(questions), "noetig": EVAL_MIN, "erzeugung": gen}
    entry = {"zeit": now, "fragen": len(questions), "erzeugung": gen, "suche": {}}
    for name, fn in VARIANTS.items():
        if name == "hybrid" and not vector.available():
            entry["suche"][name] = {"zustand": "uebersprungen", "grund": "no embedding service configured"}
            continue
        entry["suche"][name] = {k: v for k, v in run(questions, fn).items() if k != "zeilen"}
    m = learning.model()
    if m:
        d = m.data
        entry["router"] = {"zustand": d.get("zustand"), "auc": d.get("auc_holdout"), "log_loss": d.get("log_loss_holdout"),
                           "champion": (d.get("champion") or {}).get("zustand")}
    try:
        entry["exploration"] = {k: v for k, v in metrics.exploration_effect(168).items() if k != "urteil"}  # 0.57.0
    except Exception as ex:  # noqa: BLE001
        entry["exploration"] = {"fehler": f"{type(ex).__name__}: {ex}"}
    try:  # 0.61.0
        entry["zurueckhalten"] = {k: v for k, v in metrics.holdback_effect(24 * 30).items() if k != "urteil"}
    except Exception as ex:  # noqa: BLE001
        entry["zurueckhalten"] = {"fehler": f"{type(ex).__name__}: {ex}"}
    try:
        entry["hinweis_lift"] = metrics.hint_lift_matched(168)
    except Exception as ex:  # noqa: BLE001 — named, the measurement of the search stands
        entry["hinweis_lift"] = {"fehler": f"{type(ex).__name__}: {ex}"}
    p = eval_dir() / "verlauf.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    p.chmod(0o600)
    return {"zustand": "gemessen", **{k: (v.get("gesamt") if isinstance(v, dict) and "gesamt" in v else v) for k, v in entry["suche"].items()}}


# ── 0.57.0: the search log — what a search returned at which rank, and what was opened afterwards ─────────────────────────────────────
#: an opening within this many seconds after the search counts as a click on it (the agent read the hit)
CLICK_WINDOW_S = 600


def _log_table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS suche_log (zeit TEXT NOT NULL, instanz TEXT NOT NULL, gespraech TEXT, anfrage TEXT NOT NULL, "
                       "suchart TEXT, treffer TEXT NOT NULL, geoeffnet TEXT)")
        g.db().execute("CREATE INDEX IF NOT EXISTS suche_log_zeit ON suche_log (zeit)")
        g.db().commit()


def log_search(instance: str, conversation: str | None, query: str, kind: str | None, ids: list[str]) -> None:
    """One vi_recall: the query (masked text as the client sent it; internal like the rest of the memory) and the ids in rank order.
    Kept USAGE retention days (usage_stats.RETENTION_DAYS) — the data for learning a ranker from what agents open (Joachims 2017)."""
    _log_table()
    with g.lock:
        g.db().execute("INSERT INTO suche_log (zeit, instanz, gespraech, anfrage, suchart, treffer) VALUES (?, ?, ?, ?, ?, ?)",
                       (g.now(), instance, conversation, query[:500], kind, json.dumps(ids[:50])))
        g.db().commit()


def log_open(instance: str, oid: str) -> None:
    """vi_object after a search: marks the hit as opened in the newest search of this instance within CLICK_WINDOW_S that returned it."""
    from datetime import datetime, timedelta, timezone
    _log_table()
    since = (datetime.now(timezone.utc) - timedelta(seconds=CLICK_WINDOW_S)).isoformat(timespec="milliseconds")
    with g.lock:
        rows = g.db().execute("SELECT rowid, treffer, geoeffnet FROM suche_log WHERE instanz = ? AND zeit >= ? ORDER BY zeit DESC LIMIT 5",
                              (instance, since)).fetchall()
        for rowid, hits, opened in rows:
            if oid in json.loads(hits):
                o = json.loads(opened) if opened else []
                if oid not in o:
                    g.db().execute("UPDATE suche_log SET geoeffnet = ? WHERE rowid = ?", (json.dumps(o + [oid]), rowid))
                    g.db().commit()
                return


def click_stats(days: float = 7) -> dict:
    """Searches, share with at least one opened hit, opened hits by rank (position bias — the first places are looked at more)."""
    from datetime import datetime, timedelta, timezone
    _log_table()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with g.lock:
        rows = g.db().execute("SELECT treffer, geoeffnet FROM suche_log WHERE zeit >= ?", (since,)).fetchall()
    by_rank: dict[int, int] = {}
    with_click = 0
    for hits, opened in rows:
        h, o = json.loads(hits), json.loads(opened) if opened else []
        with_click += bool(o)
        for x in o:
            if x in h:
                r = h.index(x) + 1
                by_rank[r] = by_rank.get(r, 0) + 1
    return {"suchen": len(rows), "mit_klick": with_click, "je_rang": dict(sorted(by_rank.items()))}


def cleanup_log() -> int:
    from datetime import datetime, timedelta, timezone
    from .usage_stats import RETENTION_DAYS
    _log_table()
    bound = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with g.lock:
        n = g.db().execute("DELETE FROM suche_log WHERE zeit < ?", (bound,)).rowcount
        g.db().commit()
    return n
