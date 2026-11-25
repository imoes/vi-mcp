"""EXPLORATORY (not pre-registered; on the already-used kit R2 evaluation sets): a data-driven BINDER for way A. A shape's predicate
slots are bound in the order of a marginal score computed from the prompt's facts and positives only — no candidate rule is
evaluated. For every body literal of the shape and every head variable (X or Y) it contains at argument position i, the slot's
predicate p gets the share of positive pairs whose X (or Y) value occurs at position i of some p fact (negated literal: does NOT
occur), averaged over both worlds; a binding's score = product over its literals' shares. Bindings are tried best-first (ties in the
fixed order of solver_calls). Calls = clingo checks (score_kit_r2.way_a_exact) until the first exact rule.
Strategies: enum (solver_calls order), enum+rank, model (greedy + K samples, solver_calls order), model+rank, combined (model+rank,
then enum+rank), enum_global / combined_global (every shape's bindings pooled and ranked by the geometric mean of
literal shares — does the model add anything to the data score?). usage: binder_rank.py REFS GREEDY SAMPLES"""
import itertools
import json
import re
import statistics as st
import sys

import solver_calls as SC
K = SC.K


def worlds(prompt, tgt):
    out = []
    for i in (1, 2):
        facts = [re.match(r"(\w+)\((.*)\)", f.replace(" ", "")).groups() for f in re.search(rf"World {i} facts: (.*)", prompt).group(1).split("; ")]
        pos = [tuple(re.match(rf"{tgt}\((\w+),(\w+)\)", p.replace(" ", "")).groups()) for p in re.search(rf"World {i} {tgt} holds for: (.*)", prompt).group(1).split("; ")]
        at = {}
        for p, args in facts:
            for k, a in enumerate(args.split(",")):
                at.setdefault((p, k), set()).add(a)
        out.append((at, pos))
    return out


def lit_constraints(rule_text, tgt):
    """(slot_or_pred, negated, [(argpos, 'X'|'Y')]) per body literal"""
    out = []
    for r in rule_text.split("\n"):
        hv = re.findall(r"[A-Z]\w*", r.split("<=")[0])
        hx, hy = hv[0], hv[1]
        for lit in r.split("<=")[1].split("&"):
            lit = lit.strip(); neg = lit.startswith("~"); lit = lit.lstrip("~")
            m = re.match(r"(\w+)\((.*)\)", lit.replace(" ", ""))
            p, args = m.group(1), m.group(2).split(",")
            if p == tgt:
                continue
            cs = [(k, "X" if a == hx else "Y") for k, a in enumerate(args) if a in (hx, hy)]
            out.append((p, neg, cs))
    return out


def share(ws, pred, neg, cs):
    vals = []
    for at, pos in ws:
        for k, v in cs:
            s = at.get((pred, k), set())
            hit = [(x if v == "X" else y) in s for x, y in pos]
            vals.append(sum((not h) if neg else h for h in hit) / max(1, len(hit)))
    return sum(vals) / len(vals) if vals else 1.0


def ranked_bindings(ws, template, slots, choices):
    """template: rule text with {slot} placeholders; slots: slot names; choices: slot -> candidate predicates"""
    cons = lit_constraints(template.format(**{s: s for s in slots}), "t")
    scored = []
    for n, combo in enumerate(itertools.product(*[choices[s] for s in slots])):
        m = dict(zip(slots, combo)); sc = 1.0
        for p, neg, cs in cons:
            if p in m:
                sc *= share(ws, m[p], neg, cs)
        scored.append((-sc, n, m))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [m for _, _, m in scored]


def global_rank(prompt, shapes, cap=4000):
    """all (shape, binding) pairs pooled, best-first by the geometric mean of the literal shares (comparable across shapes with
    different numbers of literals); ties: shape order, then binding order"""
    tgt = re.search(r"Target: (\w+)/2", prompt).group(1)
    ws = worlds(prompt, tgt); pool = []
    for si, (template, slots, choices) in enumerate(shapes):
        cons = lit_constraints(template.format(**{s: s for s in slots}), "t")
        for n, combo in enumerate(itertools.product(*[choices[s] for s in slots])):
            m = dict(zip(slots, combo)); sc = 1.0; k = 0
            for p, neg, cs in cons:
                if p in m and cs:
                    sc *= share(ws, m[p], neg, cs); k += 1
            pool.append((-(sc ** (1 / max(1, k))), si, n, template, m))
    pool.sort(key=lambda x: x[:3])
    calls = 0
    for _s, _si, _n, template, m in pool:
        calls += 1
        if K.way_a_exact(prompt, template.format(**m).replace("t(", tgt + "(")):
            return True, calls
        if calls >= cap:
            return False, calls
    return False, calls


def try_shapes(prompt, shapes, rank, cap=4000):
    tgt = re.search(r"Target: (\w+)/2", prompt).group(1)
    b, u = SC.preds(prompt); ws = worlds(prompt, tgt) if rank else None
    calls = 0
    for template, slots, choices in shapes:
        order = ranked_bindings(ws, template, slots, choices) if rank else [dict(zip(slots, c)) for c in itertools.product(*[choices[s] for s in slots])]
        for m in order:
            text = template.format(**m).replace("t(", tgt + "(")
            calls += 1
            if K.way_a_exact(prompt, text):
                return True, calls
            if calls >= cap:
                return False, calls
    return False, calls


def enum_shapes(prompt):
    b, u = SC.preds(prompt); out = []
    for _n, rules, bs, us in SC.SHAPES:
        slots = list(bs) + list(us)
        out.append(("\n".join(rules), slots, {s: (b if s in bs else u) for s in slots}))
    return out


def model_shapes(prompt, answers):
    tgt = re.search(r"Target: (\w+)/2", prompt).group(1)
    b, u = SC.preds(prompt); ar = {p: 2 for p in b} | {p: 1 for p in u}
    out, seen = [], set()
    for ans in answers:
        rules = "\n".join(l.strip() for l in ans.splitlines() if "<=" in l)
        if not rules:
            continue
        used = list(dict.fromkeys(p for p in re.findall(r"~?(\w+)\(", rules) if p != tgt))
        if not used or any(p not in ar for p in used):
            continue
        slots = [f"S{k}" for k in range(len(used))]
        tmpl = re.sub(r"\b(\w+)\(", lambda mm: ("{S%d}(" % used.index(mm.group(1))) if mm.group(1) in used else mm.group(0), rules)
        tmpl = tmpl.replace(tgt + "(", "t(")
        if tmpl in seen:
            continue
        seen.add(tmpl)
        out.append((tmpl, slots, {s: (b if ar[p] == 2 else u) for s, p in zip(slots, used)}))
    return out


def main():
    refs = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[1])}
    greedy = {json.loads(l)["id"]: json.loads(l)["answer"] for l in open(sys.argv[2])}
    samples = {}
    for l in open(sys.argv[3]):
        r = json.loads(l); samples[r["id"]] = [s["answer"] for s in r["samples"] if s["finish"] == "stop"]
    res = {k: [] for k in ("enum", "enum_rank", "model", "model_rank", "combined_rank", "enum_global", "combined_global")}
    for i, r in refs.items():
        if i not in greedy:
            continue
        p = r["prompt"]; ms = model_shapes(p, [greedy[i]] + samples.get(i, [])); es = enum_shapes(p)
        for k, shapes, rk in (("enum", es, False), ("enum_rank", es, True), ("model", ms, False), ("model_rank", ms, True),
                              ("combined_rank", ms + es, True)):
            ok, c = try_shapes(p, shapes, rk)
            res[k].append(c if ok else None)
        for k, shapes in (("enum_global", es), ("combined_global", ms + es)):
            ok, c = global_rank(p, shapes); res[k].append(c if ok else None)
    f = lambda xs: {"solved": sum(x is not None for x in xs), "mean_calls": round(st.mean([x for x in xs if x is not None]), 1) if any(x is not None for x in xs) else None,
                    "median_calls": st.median([x for x in xs if x is not None]) if any(x is not None for x in xs) else None}
    print(json.dumps({"tasks": len(res["enum"]), **{k: f(v) for k, v in res.items()}}))


if __name__ == "__main__":
    main()
