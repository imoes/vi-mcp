"""PREREG_binder (vi-mcp-sr docs/PREREG_binder.md): a data-ranked binder for way A, confirmatory on FRESH tasks, no model.
Tasks: gen_rules.py --seed 61 --n 600 (8 families x 75, round-robin). Strategies (calls = clingo checks via score_kit_r2.way_a_exact
until the first exact rule, cap 4000):
  enum         the six trained shapes (solver_calls.SHAPES) in fixed order, bindings in fixed order;
  enum_global  the same six shapes, all (shape, binding) pairs ranked by binder_rank.global_rank (geometric mean of the marginal
               shares of the literals that touch X or Y; computed from facts and positives only, no rule evaluated);
  grammar_global  the six shapes + chain3 + join, ranked the same way.
Output: per task and strategy (solved, calls), and the summary. usage: binder_confirm.py TASKS.jsonl OUT_PER_TASK.jsonl"""
import json
import statistics as st
import sys

import binder_rank as BR
import solver_calls as SC

EXTRA = [("chain3", ["t(X, Y) <= {A}(X, Z) & {B}(Z, W) & {C}(W, Y)"], "ABC", ""),
         ("join", ["t(X, Y) <= {A}(X, Y) & {B}(Y, X)"], "AB", "")]


def shapes(prompt, extra):
    b, u = SC.preds(prompt); out = []
    for _n, rules, bs, us in SC.SHAPES + (EXTRA if extra else []):
        slots = list(bs) + list(us)
        out.append(("\n".join(rules), slots, {s: (b if s in bs else u) for s in slots}))
    return out


def main():
    tasks = [json.loads(l) for l in open(sys.argv[1])]
    rows = []
    with open(sys.argv[2], "w") as f:
        for t in tasks:
            p = t["prompt"]; r = {"id": t["id"], "family": t["family"]}
            ok, c = BR.try_shapes(p, shapes(p, False), False); r["enum"] = c if ok else None
            ok, c = BR.global_rank(p, shapes(p, False)); r["enum_global"] = c if ok else None
            ok, c = BR.global_rank(p, shapes(p, True)); r["grammar_global"] = c if ok else None
            f.write(json.dumps(r) + "\n"); f.flush(); rows.append(r)
    summ = {}
    for k in ("enum", "enum_global", "grammar_global"):
        for grp, sel in (("trained6", lambda r: r["family"] not in ("chain3", "join")), ("unseen2", lambda r: r["family"] in ("chain3", "join"))):
            xs = [r[k] for r in rows if sel(r)]
            ok = [x for x in xs if x is not None]
            summ[f"{k}:{grp}"] = {"n": len(xs), "solved": len(ok), "mean_calls": round(st.mean(ok), 2) if ok else None,
                                  "median_calls": st.median(ok) if ok else None}
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
