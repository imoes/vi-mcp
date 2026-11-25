"""Step 0 of kit36 (docs/PREREG_kit35_S43.md): is run 35's "Speaking for" error a property of kit35 or of training seed 42?

Every eval item whose situation contains a sentence "[n] Speaking for|against claim sN: member X, source O." is checked: the model's
fact line [n] must be exactly line(sN, pos|neg, O, X). "self" = X is also the author of sN in the gold facts. Counts per run, and
paired against run 35 (seed 42). Deterministic string comparison; no judge.
usage: step0_score.py EVAL.jsonl NAME=ANSWERS.jsonl [NAME=ANSWERS.jsonl ...]"""
import json
import re
import sys
from collections import Counter

PAT = re.compile(r"^\[(\d+)\]\s*Speaking (for|against) claim (s\d+): member (\w+), source (\w+)\.$", re.M)


def fact_lines(text):
    block = text.split("Statements:")[0]
    return {int(m.group(1)): re.sub(r"\s", "", m.group(2)) for m in re.finditer(r"^\s*\[(\d+)\]\s*(.+)$", block, re.M)}


def main():
    ev = {x["id"]: x for x in map(json.loads, open(sys.argv[1]))}
    runs = {}
    for a in sys.argv[2:]:
        name, path = a.split("=", 1)
        runs[name] = {x["id"]: x for x in map(json.loads, open(path))}
    common = set.intersection(*(set(r) for r in runs.values()))
    items = []
    for i in sorted(common):
        e = ev[i]
        if "facts" not in e.get("meta", {}) or len(e["messages"]) < 2:
            continue
        gold = [re.sub(r"\s", "", f) for f in e["meta"]["facts"].splitlines() if f.strip()]
        authors = {m.group(1): m.group(2) for f in gold if (m := re.match(r"author\((\w+),(\w+)\)", f))}
        for m in PAT.finditer(e["messages"][1]["content"]):
            n, d, s, x, o = int(m.group(1)), m.group(2), m.group(3), m.group(4), m.group(5)
            want = f"line({s},{'pos' if d == 'for' else 'neg'},{o},{x})"
            got = {k: fact_lines(r[i]["tuned"]).get(n) for k, r in runs.items()}
            items.append({"id": i, "set": e["set"], "n": n, "dir": d, "self": authors.get(s) == x,
                          "ok": {k: g == want for k, g in got.items()},
                          "author_error": {k: (g or "").startswith("author(") for k, g in got.items()}})
    out = {"items": len(items), "runs": list(runs), "cells": {}}
    for d in ("for", "against"):
        for selfc in (True, False):
            sub = [t for t in items if t["dir"] == d and t["self"] == selfc]
            key = f"{d}/{'self' if selfc else 'other'}"
            out["cells"][key] = {"n": len(sub), **{f"{k}_ok": sum(t["ok"][k] for t in sub) for k in runs},
                                 **{f"{k}_author_errors": sum(t["author_error"][k] for t in sub) for k in runs}}
    if "run35" in runs:
        for k in runs:
            if k == "run35":
                continue
            sub = [t for t in items if t["dir"] == "for" and t["self"]]
            out[f"paired_for_self_run35_vs_{k}"] = dict(Counter(f"run35={t['ok']['run35']}/{k}={t['ok'][k]}" for t in sub))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
