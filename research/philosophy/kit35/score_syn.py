"""Score SYN-HO (kit35, PREREG_kit35): an answer is CORRECT when its prose contains the held-out synonym as words (underscores and
case normalised) and — where the replaced seed word occurs nowhere else in the renamed block — does NOT contain the seed word.
Paired test: run B (new) vs run A (old) on the same items, exact one-sided McNemar (b = right only in B).
usage: score_syn.py ITEMS.jsonl ANSWERS_A.jsonl ANSWERS_B.jsonl [--key tuned]"""
import json
import re
import sys
from math import comb


def norm(t):
    return " " + " ".join(re.sub(r"[^a-z0-9 ]", " ", t.replace("_", " ").lower()).split()) + " "


def correct(item, answer):
    t = norm(answer)
    ok = norm(item["meta"]["must_contain"]) in t
    bad = item["meta"]["must_not_contain"]
    if bad is not None and norm(bad) in t:
        ok = False
    return ok


def main():
    items = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[1])}
    key = sys.argv[sys.argv.index("--key") + 1] if "--key" in sys.argv else "tuned"
    runs = []
    for p in sys.argv[2:4]:
        ans = {json.loads(l)["id"]: json.loads(l) for l in open(p)}
        assert set(ans) == set(items), (p, len(ans), len(items))
        runs.append({i: correct(items[i], ans[i][key]) for i in items})
    a, b = runs
    only_b = sum(b[i] and not a[i] for i in items)
    only_a = sum(a[i] and not b[i] for i in items)
    n = only_a + only_b
    p = sum(comb(n, k) for k in range(only_b, n + 1)) / 2 ** n if n else 1.0
    by_block = {}
    for i, it in items.items():
        blk = it["meta"]["block"]
        x = by_block.setdefault(blk, [0, 0, 0])
        x[0] += a[i]; x[1] += b[i]; x[2] += 1
    print(json.dumps({"n": len(items), "A_correct": sum(a.values()), "B_correct": sum(b.values()), "only_B": only_b, "only_A": only_a,
                      "p_one_sided": round(p, 6), "holds": p < 0.05, "by_block_A_B_n": by_block}, indent=1))


if __name__ == "__main__":
    main()
