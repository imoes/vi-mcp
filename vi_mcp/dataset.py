"""Training data from the memory (0.62.0) — the goal: a VI that comes out of the incubator fine-tunes an AI.

The user (13.11.2026): "Wenn eine VI aus dem Inkubator kommt, soll man damit dann eine KI fine-tunen." The language model of vi-mcp is
never trained here; this module writes a dataset someone can fine-tune a model with (SFT, KTO, DPO), documented and checked.

  qa.jsonl    SFT — question → answer from shared and internal knowledge: the questions are the ones the classification generated
              (doc2query, classify.py) or the object's own text; the answer is the knowledge with its source. Chat format
              {"messages": [user, assistant], "meta": {...}}.
  kto.jsonl   KTO (binary feedback, Ethayarajh et al. 2024 — fits the memory's helped/not-helped signal): situation → hint, desirable or
              not, from the measured counters on the hint (beta mean ≥ 0.6 or ≤ 0.4 with at least MIN_RATINGS ratings).
  dpo.jsonl   DPO — the same situation (a trigger hashtag both hints share), one hint helped clearly more than the other.
  manifest.json and DATASHEET.md — what is in it, what was left out and why, versions, known gaps (Gebru et al., Datasheets for Datasets).

What never goes in: private objects, experiences and conversations (they belong to their instance — the hint data are the aggregated
counters on knowledge, not anyone's actions), quarantine, refuted or archived objects, code pieces (copies of repositories), and the
targets of the fixed question set (evaluation.recall.json) — they stay held out, so a model fine-tuned on the data can still be measured
on them (contamination guard; questions too close to an evaluation question are dropped as well). Credentials: every text goes through
anonymize.without_secrets once more; what that changes is counted (an audit of the scrubbing at save time).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from . import __version__
from . import memory as g

FORMAT_VERSION = 1
KINDS = ("erkenntnis", "regel", "skill")
ANSWER_CHARS = 8000
MIN_RATINGS = 5
GOOD, BAD = 0.6, 0.4
DPO_MARGIN = 0.3


def _norm(q: str) -> str:
    return re.sub(r"\W+", " ", (q or "").lower()).strip()


def _eval_hold_out() -> tuple[set[str], set[str]]:
    """(target ids, normalised questions) of the fixed question set — held out of every training file."""
    from . import evaluation
    p = evaluation.eval_dir() / "recall.json"
    if not p.exists():
        return set(), set()
    try:
        qs = evaluation.load_questions(p)
    except Exception:  # noqa: BLE001
        return set(), set()
    return {q["target"] for q in qs}, {_norm(q["frage"]) for q in qs if q.get("frage")}


def _objects(index: str | None) -> list[g.MemoryObject]:
    sql = (f"SELECT id FROM objekt WHERE art IN ({','.join('?' * len(KINDS))}) AND modus IN ('aktiv', 'test') AND sicht IN ('geteilt', 'intern')"
           + (" AND idx = ?" if index else ""))
    with g.lock:
        ids = [r[0] for r in g.db().execute(sql, (*KINDS, *([index] if index else [])))]
    return list(g.load_many(ids).values())


def _clean(text: str, audit: Counter, field: str) -> str:
    from . import anonymize
    out = anonymize.without_secrets(text)
    if out != text:
        audit[field] += 1
    return out


def _answer(o: g.MemoryObject, audit: Counter) -> str:
    body = str(o.data.get("inhalt") or "").strip()
    src = str(o.data.get("quelle") or "").strip()
    text = o.text.strip() + (f"\n\n{body[:ANSWER_CHARS]}" if body else "") + (f"\n\nSource: {src}" if src else "")
    return _clean(text, audit, "answer")


def build(index: str | None = None) -> dict:
    """All examples and the bookkeeping, in memory (export writes them)."""
    from . import vil
    targets, eval_qs = _eval_hold_out()
    skipped, audit = Counter(), Counter()
    qa, rated, qa_objects = [], [], []
    for o in _objects(index):
        if "art_wissen:code" in o.hashtags:
            skipped["code piece (a copy of a repository)"] += 1
            continue
        if o.id in targets:
            skipped["target of the fixed question set (held out for evaluation)"] += 1
            continue
        k = o.data.get("klasse") or {}
        questions = [q for q in (k.get("fragen") or []) if isinstance(q, str) and q.strip()] or [o.text.strip()]
        meta = {"id": o.id, "kind": o.kind, "index": o.idx, "answers": k.get("answers"), "memory": vil.memory_of(o),
                "evidence": vil.evidence_of(o), "weight": vil.weight_of(o)[0], "ratings": vil.weight_of(o)[1],
                "question_source": "doc2query" if k.get("fragen") else "title"}
        answer = _answer(o, audit)
        qa_objects.append((o, questions))
        for q in questions:
            if _norm(q) in eval_qs:
                skipped["question equal to an evaluation question"] += 1
                continue
            qa.append({"messages": [{"role": "user", "content": _clean(q, audit, "question")}, {"role": "assistant", "content": answer}],
                       "meta": meta})
        w, n = vil.weight_of(o)
        if n >= MIN_RATINGS:
            rated.append((o, w, n))
    kto, dpo = [], []
    for o, w, n in rated:
        if w >= GOOD or w <= BAD:
            kto.append({"prompt": _situation(o), "completion": _clean(o.text, audit, "hint"), "label": w >= GOOD,
                        "meta": {"id": o.id, "weight": w, "ratings": n}})
    by_trigger: dict[str, list] = {}
    for o, w, n in rated:
        for t in o.hashtags:
            if t.startswith(("tool:", "host:", "thema:", "fehler:")):
                by_trigger.setdefault(t, []).append((o, w, n))
    seen = set()
    for t, group in sorted(by_trigger.items()):
        group.sort(key=lambda x: -x[1])
        best, worst = group[0], group[-1]
        if best[1] - worst[1] >= DPO_MARGIN and (best[0].id, worst[0].id) not in seen:
            seen.add((best[0].id, worst[0].id))
            dpo.append({"prompt": f"Situation: {t}. Which piece of knowledge helps?", "chosen": _clean(best[0].text, audit, "hint"),
                        "rejected": _clean(worst[0].text, audit, "hint"),
                        "meta": {"trigger": t, "chosen": best[0].id, "rejected": worst[0].id, "weights": [best[1], worst[1]]}})
    agentic, agentic_skipped = agentic_examples(qa_objects, eval_qs, audit)
    skipped.update(agentic_skipped)
    return {"qa": qa, "kto": kto, "dpo": dpo, "agentic": agentic, "skipped": dict(skipped), "scrubbed": dict(audit), "held_out": len(targets)}


AGENTIC_MAX = 2000
_STOP = frozenset("what which where when does with this that from have will they them their there about into your über eine einer einem "
                  "einen wird werden wurde nicht oder auch nach wenn dann sich sind kann muss soll wie was wer warum welche welcher".split())


def _query_words(question: str, n: int = 3) -> list[str]:
    import re as _re
    words = [w.lower() for w in _re.findall(r"[\wäöüß-]{4,}", question or "")]
    return [w for w in dict.fromkeys(words) if w not in _STOP][:n]


def _tool_schema() -> dict:
    from . import tools
    d = next(t for t in tools.TOOLS if t["name"] == "vi_recall")
    return {"type": "function", "function": {"name": "vi_recall", "description": d["description"][:600], "parameters": d["inputSchema"]}}


def _search_lines(query: str) -> tuple[list[g.MemoryObject], str]:
    """Run the real search (tools.search, full text and tags — no embedding calls while exporting) and render the VIL answer, without
    anything private, in quarantine or not knowledge."""
    from . import tools, vil
    try:
        hits, _f, _k = tools.search({"filter": query, "limit": 10, "semantic": False}, None, None)
    except tools.Rejected:
        return [], ""
    objs = [o for _s, o, _w in hits if o.visibility != "privat" and o.mode not in ("quarantaene",) and o.kind in KINDS]
    return objs, "\n".join(vil.tell_line(o) for o in objs) or "nothing in memory"


def agentic_examples(items: list[tuple], eval_qs: set[str], audit: Counter) -> tuple[list[dict], Counter]:
    """0.62.0 — the user: "Außerdem soll die VI so trainiert werden, dass man agentisch die Daten durchsuchen kann." Trajectories in the
    tool-calling chat format: the user asks; the assistant calls vi_recall with a VIL question built from the question's words and the
    object's label and hashtags; the tool answers with the real tell lines of this server's search; if the target is not among them,
    the assistant relaxes (drops the words, keeps @host/#thema) and asks again; it answers from the target, citing it. Kept only if the
    target was found — a trajectory that teaches a wrong answer is no example (counted)."""
    import random as _random
    from . import vil
    skipped = Counter()
    rnd = _random.Random(11)
    pool = items if len(items) <= AGENTIC_MAX else rnd.sample(items, AGENTIC_MAX)
    tool = _tool_schema()
    out = []
    for o, questions in pool:
        q = questions[0]
        if _norm(q) in eval_qs:
            continue
        qtype = (o.data.get("klasse") or {}).get("answers")
        qtype = qtype if qtype in vil.QTYPES else "what"
        host = next((t[5:] for t in o.hashtags if t.startswith("host:")), None)
        topic = next((t[6:] for t in o.hashtags if t.startswith("thema:")), None)
        tags = " ".join(([f"@{host}"] if host else []) + ([f"#{topic}"] if topic else []))
        words = " ".join(_query_words(q))
        steps = [f"ask.{qtype} {words} {tags}".strip()] + ([f"ask.{qtype} {tags}"] if tags and words else [])
        messages = [{"role": "user", "content": _clean(q, audit, "question")}]
        found = False
        for query in steps:
            objs, lines = _search_lines(query)
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "function": {"name": "vi_recall", "arguments": {"filter": query, "format": "vil"}}}]})
            messages.append({"role": "tool", "name": "vi_recall", "content": _clean(lines, audit, "tool")})
            if any(x.id == o.id for x in objs):
                found = True
                break
        if not found:
            skipped["agentic: the search did not find the target (no example teaches a wrong answer)"] += 1
            continue
        messages.append({"role": "assistant", "content": _answer(o, audit) + f"\n\n(from {o.id})"})
        out.append({"messages": messages, "tools": [tool], "meta": {"id": o.id, "steps": (len(messages) - 2) // 2, "answers": qtype}})
    return out, skipped


def _situation(o: g.MemoryObject) -> str:
    triggers = [t for t in o.hashtags if t.startswith(("tool:", "host:", "thema:", "fehler:"))][:8]
    return "Situation: " + (", ".join(triggers) or "general") + ". Which piece of knowledge helps?"


def _versions() -> dict:
    from . import classify, learning
    m = learning.model()
    st = g.load(classify.STUDENT)
    return {"vi_mcp": __version__, "format": FORMAT_VERSION, "router": (m.data.get("trainiert") if m else None),
            "classify_prompt": classify.prompt_hash(), "classify_schema": classify.SCHEMA_VERSION,
            "student": (st.data.get("trainiert") if st else None), "time": g.now()}


def datasheet(manifest: dict) -> str:
    c, sk, sc = manifest["counts"], manifest["skipped"], manifest["scrubbed"]
    return f"""# Datasheet — vi-mcp training data

Written by `vi-mcp dataset export` on {manifest['versions']['time']} (vi-mcp {manifest['versions']['vi_mcp']}, format {FORMAT_VERSION}).
Index: {manifest['index'] or 'all indexes'}. Internal: company knowledge unanonymised — hand it only to people of the same organisation.

## Motivation
A VI out of the incubator fine-tunes an AI: question → answer from its knowledge (SFT), and which hints helped (KTO, DPO).

## Composition
| file | examples | what |
|---|---|---|
| qa.jsonl | {c['qa']} | question → knowledge with source; questions from the classification (doc2query) or the object's text |
| kto.jsonl | {c['kto']} | situation → hint, desirable if its measured success ≥ {GOOD} (≤ {BAD}: undesirable), ≥ {MIN_RATINGS} ratings |
| dpo.jsonl | {c['dpo']} | the same trigger, one hint helped ≥ {DPO_MARGIN} more than the other |
| agentic.jsonl | {c['agentic']} | tool use: the model asks the VI with vi_recall in VIL (relaxing once if needed) and answers from the target |

## Left out, with the reason
""" + ("\n".join(f"- {k}: {v}" for k, v in sk.items()) or "- nothing") + f"""
- private objects, experiences and conversations: never selected (they belong to their instance)
- quarantine, refuted and archived objects: never selected

## Evaluation hold-out (contamination guard)
{manifest['held_out']} targets of the fixed question set are not in any file, nor questions equal to an evaluation question.

## Scrubbing audit
Credentials are removed at save time; this export ran the scrubber again — changed texts: """ + (", ".join(f"{k} {v}" for k, v in sc.items()) or "none") + f""".

## Labels and their quality
- answers/memory labels: a language model with two prompt variants; measured on a production sample (13.11.2026, 45 objects):
  agreement 82 % (Cohen's κ 0.75) for the question type, 87 % (κ 0.80) for the memory kind. No human gold set yet.
- weights: beta mean of helped/not helped of the hint bandit — the counters of this server only.

## Versions
""" + "\n".join(f"- {k}: {v}" for k, v in manifest["versions"].items()) + """

## Known gaps
- No user prompts: they are masked and never stored, so there are no full task trajectories.
- The hint data are aggregated counters, not single actions; a hint shown more often weighs more.
- doc2query questions exist only for objects the classification has labelled; the rest use the object's own text as the question.
"""


def export(directory: str | Path, index: str | None = None) -> dict:
    """Write the files (0600) into `directory` (created 0700). Returns the manifest."""
    from . import indexes
    idx = indexes.normalize(index) if index else None
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    data = build(idx)
    manifest = {"index": idx, "counts": {k: len(data[k]) for k in ("qa", "kto", "dpo", "agentic")}, "skipped": data["skipped"],
                "scrubbed": data["scrubbed"], "held_out": data["held_out"], "versions": _versions()}
    for name in ("qa", "kto", "dpo", "agentic"):
        _write(d / f"{name}.jsonl", "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data[name]))
    _write(d / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    _write(d / "DATASHEET.md", datasheet(manifest))
    return manifest


def _write(p: Path, text: str) -> None:
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str]) -> int:
    """vi-mcp dataset export DIR [--index X]"""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp dataset", description="training data from the memory, for fine-tuning a model")
    u = a.add_subparsers(dest="cmd", required=True)
    ex = u.add_parser("export", help="write qa/kto/dpo .jsonl, manifest.json and DATASHEET.md into a directory")
    ex.add_argument("directory")
    ex.add_argument("--index")
    o = a.parse_args(argv)
    g.open_db(config.load().db)
    try:
        print(json.dumps(export(o.directory, o.index), indent=2, ensure_ascii=False))
    finally:
        g.close_db()
    return 0
