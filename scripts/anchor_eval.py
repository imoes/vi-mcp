"""0.72.0: measure the search anchor (goal Z6) on a private working copy — development data and the offline gate.

Every question is searched once with vi_recall as an agent calls it (hybrid, reranker if configured, reinforce=false, in a session of
INSTANCE so visibility is the agent's); anchor.CAPTURE records the list before the anchor and the anchor plan. Placements are
computed afterwards from that record with the production function anchor.place — the same code the switch runs.
A row whose meaning search failed (the search fell back to full text) is marked invalid and searched again by the next run (resumable).

  python3 scripts/anchor_eval.py recall RECALL.json dev|gate OUT.jsonl      # eval/recall.json → questions, split by source page
  python3 scripts/anchor_eval.py agents DB OUT.jsonl                          # logged agent hybrid searches → questions (no gold)
  python3 scripts/anchor_eval.py search DB QUESTIONS.jsonl OUT.jsonl [--instance NAME] [--limit N] [--semantic]
  python3 scripts/anchor_eval.py score OUT.jsonl [--hops 0,1,2,5] [--at 0,1] [--pages]
  python3 scripts/anchor_eval.py switchcheck DB QUESTIONS.jsonl [--limit 20] [--semantic]
  python3 scripts/anchor_eval.py gate RECALL.jsonl Z6.jsonl AGENTS.jsonl --questions RQ.jsonl ZQ.jsonl AQ.jsonl   # PREREG_Z6_GATE

QUESTIONS.jsonl: {"id", "question", "gold": [page ids], "instance"?} — all gold ids in the top k counts (both@k for two-page
questions). --pages scores at page level like vi_mcp/evaluation.py: an object counts as its source page (evaluation.group_of), each
page once; recall rows carry the page as gold. The recall split is by a hash of the source page, so both query styles of a target and
all parts of a page fall in the same half.
Environment: VI_EMBED_URL, VI_RERANK_URL (internal service addresses — never in the repository). The database is opened read-write
(sessions are written): pass a private copy, never the original."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


def split_half(group: str) -> str:
    """dev or gate, by a seeded hash of the source page. Pure."""
    import hashlib
    return "dev" if int(hashlib.sha256(f"z6gate:{group}".encode()).hexdigest()[:8], 16) % 2 == 0 else "gate"


def recall(a) -> None:
    rows = json.loads(Path(a.recall).read_text(encoding="utf-8"))
    n = 0
    with open(a.out, "w") as f:
        for q in rows:
            if q.get("error") or not q.get("group") or split_half(q["group"]) != a.half:
                continue
            for style in ("frage", "stichworte"):
                text = str(q.get(style) or "").strip()
                if text:
                    f.write(json.dumps({"id": f"{q['target']}|{style}", "question": text, "gold": [q["group"]], "style": style,
                                        "stratum": q.get("stratum", "-")}, ensure_ascii=False) + "\n")
                    n += 1
    print(f"{a.half}: {n} queries", flush=True)


def agents(a) -> None:
    import sqlite3
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    seen, n = set(), 0
    with open(a.out, "w") as f:
        for ts, inst, query in con.execute("SELECT ts, instance, query FROM search_log WHERE search_kind LIKE 'hybrid%' ORDER BY ts"):
            key = (inst, query.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            n += 1
            f.write(json.dumps({"id": f"log{n:04d}", "question": query, "gold": [], "instance": inst, "ts": ts}, ensure_ascii=False) + "\n")
    print(f"{n} distinct agent hybrid searches", flush=True)


def search(a) -> None:
    from vi_mcp import anchor, evaluation, memory as g, session, tools, vector
    vector.config = {"url": os.environ["VI_EMBED_URL"]}
    if os.environ.get("VI_RERANK_URL"):
        vector.rerank_config = {"url": os.environ["VI_RERANK_URL"]}
    g.open_db(a.db)
    out = Path(a.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            if r.get("valid"):
                done.add(r["id"])
    rows = [json.loads(line) for line in open(a.questions)][: a.limit or None]
    todo = [q for q in rows if q["id"] not in done]
    print(f"{len(rows)} questions, {len(done)} done, {len(todo)} to search", flush=True)
    sessions = {}
    t0 = time.time()
    args = {"limit": 10, "reinforce": False, **({"semantic": True} if a.semantic else {})}
    with out.open("a") as f:
        for n, q in enumerate(todo, 1):
            inst = q.get("instance") or a.instance
            if inst not in sessions:
                sessions[inst] = session.begin(inst, "anchor_eval")
            anchor.CAPTURE = []
            t = time.time()
            with session.on_behalf(sessions[inst]):
                text = str(tools.call_tool("vi_recall", {"filter": q["question"], **args}, inst, True))
            head = text.splitlines()[0] if text else ""
            cap = anchor.CAPTURE[-1] if anchor.CAPTURE else None
            # a fallback (no meaning search, or no reranker while one is configured) changes the base list: searched again later
            valid = cap is not None and "meaning search unavailable" not in head and "reranker unavailable" not in head
            ids = list(dict.fromkeys((cap["ranked"] if cap else []) + [i for p in (cap["plan"] if cap else [])
                                                                          for i in [p["anchor"], *p["hops"]]]))
            groups = {i: evaluation.group_of(o) for i, o in g.load_many(ids).items()}
            f.write(json.dumps({"id": q["id"], "gold": q["gold"], "valid": valid, "s": round(time.time() - t, 2), "instance": inst,
                                "ranked": cap["ranked"] if cap else [], "plan": cap["plan"] if cap else [], "groups": groups,
                                "note": head[:400]},
                               ensure_ascii=False) + "\n")
            f.flush()
            if n % 50 == 0:
                print(f"{n}/{len(todo)} in {time.time() - t0:.0f} s", flush=True)
    anchor.CAPTURE = None


def switchcheck(a) -> None:
    """Validity of the computed arms: the first N queries through the real switch (off, then on) — the shown top-10 ids must equal
    OFF[:10] (the captured list before the anchor) and anchor.place(OFF, plan)[:10]. Prints mismatches; exit code 1 on any."""
    import re
    from vi_mcp import anchor, memory as g, session, tools, vector
    vector.config = {"url": os.environ["VI_EMBED_URL"]}
    if os.environ.get("VI_RERANK_URL"):
        vector.rerank_config = {"url": os.environ["VI_RERANK_URL"]}
    g.open_db(a.db)
    rows = [json.loads(line) for line in open(a.questions)][: a.limit]
    args = {"limit": 10, "reinforce": False, **({"semantic": True} if a.semantic else {})}
    s = session.begin(a.instance, "anchor_switchcheck")
    shown = lambda t: re.findall(r"^\s*\[([a-z_]+:[0-9a-z\-]+)\]", t, re.M)  # noqa: E731
    bad = n = 0
    with session.on_behalf(s):
        for q in rows:
            out = {}
            for mode in ("off", "on"):
                anchor.MODE, anchor.CAPTURE = mode, []
                text = str(tools.call_tool("vi_recall", {"filter": q["question"], **args}, a.instance, True))
                out[mode] = (shown(text), anchor.CAPTURE[-1] if anchor.CAPTURE else None, text.splitlines()[0][:200])
            anchor.MODE, anchor.CAPTURE = "off", None
            (ids_off, cap_off, h_off), (ids_on, cap_on, h_on) = out["off"], out["on"]
            if "unavailable" in h_off or "unavailable" in h_on or not cap_off or not cap_on:
                print(f"{q['id']}: invalid (service unavailable)", flush=True)
                continue
            n += 1
            want_on = anchor.place(cap_on["ranked"], cap_on["plan"])[:10]
            ok = ids_off == cap_off["ranked"][:10] and ids_on == want_on
            if not ok:
                bad += 1
                print(f"{q['id']}: MISMATCH off={ids_off == cap_off['ranked'][:10]} on={ids_on == want_on}", flush=True)
    print(json.dumps({"checked": n, "mismatch": bad, "hops": anchor.HOPS}), flush=True)
    sys.exit(1 if bad else 0)


def score(a) -> None:
    from vi_mcp import anchor
    rows = {}
    for line in open(a.out):
        r = json.loads(line)
        if r.get("valid"):
            rows[r["id"]] = r  # the last valid search of a question counts
    hops = [int(x) for x in a.hops.split(",")]

    def view(r, ids):  # object ids → what is counted: the objects, or (--pages) their source pages, each once
        return list(dict.fromkeys(r["groups"].get(i, i) for i in ids)) if a.pages else ids

    def hit(r, ids, k):
        return bool(r["gold"]) and set(r["gold"]) <= set(view(r, ids)[:k])
    ats = [int(x) for x in a.at.split(",")]
    res = {"n": len(rows), "with_anchor": sum(1 for r in rows.values() if r["plan"])}
    for k in (1, 4, 10):
        res[f"base@{k}"] = round(sum(hit(r, r["ranked"], k) for r in rows.values()) / max(1, len(rows)), 4)
    for h in hops:
        for at in ats:
            arm = f"hops{h}at{at}"
            placed = {i: anchor.place(r["ranked"], r["plan"], hops=h, at=at) for i, r in rows.items()}
            for k in (1, 4, 10):
                res[f"{arm}@{k}"] = round(sum(hit(r, placed[i], k) for i, r in rows.items()) / max(1, len(rows)), 4)
            res[arm] = {f"{w}@{k}": len([i for i, r in rows.items() if hit(r, placed[i], k) != hit(r, r["ranked"], k)
                                         and hit(r, placed[i], k) == (w == "won")]) for k in (1, 4) for w in ("won", "lost")}
            # top 4 changed at all (descriptive, also without gold): the anchor moved something into the shown four
            res[arm]["top4_changed"] = sum(1 for i, r in rows.items() if view(r, placed[i])[:4] != view(r, r["ranked"])[:4])
            res[arm]["lost@4_ids"] = [i for i, r in rows.items() if hit(r, r["ranked"], 4) and not hit(r, placed[i], 4)]
    print(json.dumps(res, indent=1))


def _mcnemar_two_sided(b: int, c: int) -> float:
    """Exact two-sided McNemar (binomial on the discordant pairs, p = 1/2). Pure."""
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def _valid_rows(path: str) -> dict:
    rows = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("valid"):
            rows[r["id"]] = r
    return rows


def gate(a) -> None:
    """PREREG_Z6_GATE: G1 (recall Hit@4 non-inferior), G1b (recall Hit@1 does not drop), G2 (Z6 both@4 retained), G3 (agent searches,
    descriptive), validity (≤ 5 % invalid per set). ON = anchor.place(OFF, plan) with the frozen anchor.HOPS and anchor.AT."""
    from vi_mcp import anchor
    sets = {"recall": (a.recall, a.questions[0], True), "z6": (a.z6, a.questions[1], False), "agents": (a.agents, a.questions[2], False)}
    out: dict = {"hops": anchor.HOPS, "at": anchor.AT, "valid": {}}
    rows = {}
    for name, (path, qpath, pages) in sets.items():
        asked = sum(1 for _ in open(qpath))
        rows[name] = _valid_rows(path)
        out["valid"][name] = {"asked": asked, "valid": len(rows[name]), "invalid_share": round(1 - len(rows[name]) / max(1, asked), 4)}
    valid_run = all(v["invalid_share"] <= 0.05 for v in out["valid"].values())

    def view(r, ids, pages):
        return list(dict.fromkeys(r["groups"].get(i, i) for i in ids)) if pages else ids

    def hit(r, ids, k, pages):
        return bool(r["gold"]) and set(r["gold"]) <= set(view(r, ids, pages)[:k])

    def compare(name, k):
        pages = sets[name][2]
        won = lost = on_hits = off_hits = 0
        for r in rows[name].values():
            off, on = hit(r, r["ranked"], k, pages), hit(r, anchor.place(r["ranked"], r["plan"]), k, pages)
            on_hits += on
            off_hits += off
            won += on and not off
            lost += off and not on
        n = len(rows[name])
        return {"n": n, "off": round(off_hits / max(1, n), 4), "on": round(on_hits / max(1, n), 4), "won": won, "lost": lost,
                "mcnemar_p_two_sided": round(_mcnemar_two_sided(won, lost), 4)}
    g1, g1b, g2 = compare("recall", 4), compare("recall", 1), compare("z6", 4)
    g1["pass"] = g1["lost"] - g1["won"] <= 3
    g1b["pass"] = g1b["on"] >= g1b["off"]
    g2["pass"] = g2["on"] >= 0.80 and g2["on"] - g2["off"] >= 0.50
    g1["lost_classes"] = [
        {"style": i.split("|")[-1], "anchor_is_target_page": any(r["groups"].get(p["anchor"]) in r["gold"] for p in r["plan"])}
        for i, r in rows["recall"].items() if hit(r, r["ranked"], 4, True) and not hit(r, anchor.place(r["ranked"], r["plan"]), 4, True)]
    ag = rows["agents"].values()
    with_anchor = [r for r in ag if r["plan"]]
    changed = [r for r in with_anchor if anchor.place(r["ranked"], r["plan"])[:4] != r["ranked"][:4]]
    g3 = {"n": len(rows["agents"]), "with_anchor": len(with_anchor), "top4_changed": len(changed),
          "anchor_already_in_off_top4": sum(1 for r in with_anchor if all(p["anchor"] in r["ranked"][:4] for p in r["plan"])),
          "pages_placed": dict(sorted(Counter(min(4, len(anchor.place([], r["plan"]))) for r in with_anchor).items()))}
    out.update(G1=g1, G1b=g1b, G2=g2, G3=g3, run_valid=valid_run)
    out["state"] = "invalid" if not valid_run else "passed" if g1["pass"] and g1b["pass"] and g2["pass"] else "failed"
    print(json.dumps(out, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recall")
    r.add_argument("recall"), r.add_argument("half", choices=("dev", "gate")), r.add_argument("out")
    ag = sub.add_parser("agents")
    ag.add_argument("db"), ag.add_argument("out")
    s = sub.add_parser("search")
    s.add_argument("db"), s.add_argument("questions"), s.add_argument("out")
    s.add_argument("--instance", default="claude-code"), s.add_argument("--limit", type=int, default=0)
    s.add_argument("--semantic", action="store_true", help="semantic=true, as vi_mcp/evaluation.py's hybrid variant calls it")
    w = sub.add_parser("switchcheck")
    w.add_argument("db"), w.add_argument("questions"), w.add_argument("--limit", type=int, default=20)
    w.add_argument("--instance", default="claude-code"), w.add_argument("--semantic", action="store_true")
    gt = sub.add_parser("gate")
    gt.add_argument("recall"), gt.add_argument("z6"), gt.add_argument("agents")
    gt.add_argument("--questions", nargs=3, required=True, help="the three question files, same order (for the invalid share)")
    c = sub.add_parser("score")
    c.add_argument("out"), c.add_argument("--hops", default="0,1,2,5"), c.add_argument("--at", default="0")
    c.add_argument("--pages", action="store_true")
    a = ap.parse_args(argv)
    {"recall": recall, "agents": agents, "search": search, "switchcheck": switchcheck, "gate": gate, "score": score}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
