"""PREREG_binder hypotheses from binder_confirm's per-task file.
H-BR1: on the six trained families, enum_global needs fewer calls than enum — exact one-sided sign test over tasks (an unsolved
strategy counts as cap + 1 = 4001 calls; ties dropped), alpha 0.05.
H-BR2: grammar_global solves the unseen families (chain3, join): one-sided 95 % Clopper-Pearson lower bound of the solved share
> 0.80. Descriptive: per family solved / mean / median calls per strategy; share solved at the first call.
usage: binder_test.py PER_TASK.jsonl"""
import json
import sys
from math import comb


def cp_lower(k, n, alpha=0.05):
    if k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        tail = sum(comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(k, n + 1))
        if tail < alpha:
            lo = mid
        else:
            hi = mid
    return round(lo, 4)


def main():
    rows = [json.loads(l) for l in open(sys.argv[1])]
    cap = lambda x: 4001 if x is None else x  # noqa: E731
    tr = [r for r in rows if r["family"] not in ("chain3", "join")]
    b = sum(cap(r["enum_global"]) < cap(r["enum"]) for r in tr); c = sum(cap(r["enum_global"]) > cap(r["enum"]) for r in tr)
    p = sum(comb(b + c, i) for i in range(b, b + c + 1)) / 2 ** (b + c) if b + c else 1.0
    un = [r for r in rows if r["family"] in ("chain3", "join")]
    k = sum(r["grammar_global"] is not None for r in un)
    lo = cp_lower(k, len(un))
    fam = {}
    for r in rows:
        for s in ("enum", "enum_global", "grammar_global"):
            d = fam.setdefault(r["family"], {}).setdefault(s, [])
            d.append(r[s])
    desc = {f: {s: {"solved": sum(x is not None for x in v), "n": len(v),
                    "mean": round(sum(x for x in v if x is not None) / max(1, sum(x is not None for x in v)), 2),
                    "first_call": sum(x == 1 for x in v)} for s, v in d.items()} for f, d in sorted(fam.items())}
    print(json.dumps({"H_BR1": {"global_fewer": b, "enum_fewer": c, "p_one_sided": p, "holds": p < 0.05},
                      "H_BR2": {"unseen_solved": k, "n": len(un), "cp_lower_95": lo, "holds": lo > 0.80},
                      "by_family": desc}, indent=1))


if __name__ == "__main__":
    main()
