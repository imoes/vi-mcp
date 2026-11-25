"""EXPLORATORY: sequential covering on top of the binder (FOIL-style) for disjunctive targets. Single clauses from the one-clause
shapes (chain2, inverse, filter, neg, chain3, join; base t(X,Y) <= A(X,Y)), bindings scored by the binder's marginal shares against
the positives NOT yet covered; a clause is accepted when, evaluated with clingo in both worlds, it derives at least one uncovered
positive and no non-positive (closed world). Clauses are added until every positive is covered (max 3 clauses), then the union is
checked exactly. Calls = clingo evaluations (clause checks + final check). Cap 4000.
usage: binder_cover.py REFS.jsonl"""
import itertools
import json
import re
import statistics as st
import sys

import binder_rank as BR
import solver_calls as SC

CLAUSES = [("base", "t(X, Y) <= {A}(X, Y)", "A", ""),
           ("chain2", "t(X, Y) <= {A}(X, Z) & {B}(Z, Y)", "AB", ""),
           ("inverse", "t(X, Y) <= {A}(Z, X) & {B}(Z, Y)", "AB", ""),
           ("filter", "t(X, Y) <= {A}(X, Z) & {B}(Z, Y) & {U}(Y)", "AB", "U"),
           ("neg", "t(X, Y) <= {A}(X, Z) & {B}(Z, Y) & ~{U}(Y)", "AB", "U"),
           ("join", "t(X, Y) <= {A}(X, Y) & {B}(Y, X)", "AB", "")]


def derive(prompt, tgt, clause_text, world):
    facts = re.search(rf"World {world} facts: (.*)", prompt).group(1).split("; ")
    asp = ""
    for r in clause_text.split("\n"):
        head, body = r.split("<=", 1)
        lits = [x.strip() for x in body.split("&")]
        asp += "target(X,Y):-" + ",".join(("not " + x[1:].replace(" ", "")) if x.startswith("~") else x.replace(" ", "") for x in lits) + ".\n"
    got = SC.K.solve("".join(f.replace(" ", "") + ".\n" for f in facts) + asp + "#show target/2.")
    return {tuple(re.match(r"target\((\w+),(\w+)\)", a).groups()) for a in got}


def cover(prompt, cap=4000):
    tgt = re.search(r"Target: (\w+)/2", prompt).group(1)
    b, u = SC.preds(prompt)
    ws = BR.worlds(prompt, tgt)
    pos = [set(w[1]) for w in ws]
    left = [set(p) for p in pos]
    calls = 0; chosen = []
    for _round in range(3):
        wsl = [(ws[i][0], sorted(left[i])) for i in range(2)]
        pool = []
        for si, (_n, tmpl, bs, us) in enumerate(CLAUSES):
            slots = list(bs) + list(us)
            cons = BR.lit_constraints(tmpl.format(**{s: s for s in slots}), "t")
            for n, combo in enumerate(itertools.product(*[(b if s in bs else u) for s in slots])):
                m = dict(zip(slots, combo)); sc = 1.0; k = 0
                for p, neg, cs in cons:
                    if p in m and cs:
                        sc *= BR.share(wsl, m[p], neg, cs); k += 1
                pool.append((-(sc ** (1 / max(1, k))), si, n, tmpl.format(**m)))
        pool.sort(key=lambda x: x[:3])
        found = False
        for _s, _si, _n, text in pool:
            calls += 1
            d = [derive(prompt, tgt, text, w) for w in (1, 2)]
            if all(d[i] <= pos[i] for i in range(2)) and any(d[i] & left[i] for i in range(2)):
                chosen.append(text); left = [left[i] - d[i] for i in range(2)]; found = True
                break
            if calls >= cap:
                return False, calls, chosen
        if not found:
            return False, calls, chosen
        if not any(left):
            calls += 1
            rules = "\n".join(c.replace("t(", tgt + "(") for c in chosen)
            return SC.K.way_a_exact(prompt, rules), calls, chosen
    return False, calls, chosen


def main():
    refs = [json.loads(l) for l in open(sys.argv[1])]
    res = []; byfam = {}
    for r in refs:
        ok, c, ch = cover(r["prompt"])
        res.append(c if ok else None); byfam.setdefault(r.get("family", "?"), []).append(c if ok else None)
    f = lambda xs: {"n": len(xs), "solved": sum(x is not None for x in xs), "mean_calls": round(st.mean([x for x in xs if x is not None]), 1) if any(x is not None for x in xs) else None}
    print(json.dumps({"all": f(res), "by_family": {k: f(v) for k, v in sorted(byfam.items())}}))


if __name__ == "__main__":
    main()
