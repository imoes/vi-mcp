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
    qa, rated = [], []
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
    return {"qa": qa, "kto": kto, "dpo": dpo, "skipped": dict(skipped), "scrubbed": dict(audit), "held_out": len(targets)}


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
    manifest = {"index": idx, "counts": {k: len(data[k]) for k in ("qa", "kto", "dpo")}, "skipped": data["skipped"],
                "scrubbed": data["scrubbed"], "held_out": data["held_out"], "versions": _versions()}
    for name in ("qa", "kto", "dpo"):
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
