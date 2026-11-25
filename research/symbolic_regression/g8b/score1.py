"""G8b-1 scoring exactly as prereg_G8b1.md (version 2, frozen 7099f073…): O1 lookup, O2 search cost, OT total; H1 L vs XR on O2 over
pairs without lookup, H2 on O1, H3 on OT; within-task midranks, 10,000 Monte Carlo sign flips (seed 20261119), Holm; trivial stratum
from Z; effect = median over tasks of log(XR median / L median) with a task bootstrap 95 % interval. Only complete seed blocks.
usage: score1.py [--arms L XR] -> result_G8b1.json"""
import argparse, glob, json, math, os, random, statistics
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
CENS = 15001


def load():
    R = {}
    for f in glob.glob(f"{D}/runs1/*.json"):
        if f.endswith((".first.json", ".start.json")):
            continue
        r = json.load(open(f))
        R[(r["task"], r["arm"], r["seed"])] = r
    return R


def o1(r):
    return 1 if r["first_in_start"] else 0


def o2(r):
    if r["first_in_start"]:
        return None
    c = r["search_cost"]
    return CENS if c is None or c > 15000 else c


def ot(r):
    fs = r.get("first_solution")
    s = r["start"]["start_evals"]
    if not fs:
        return s + CENS
    return fs["evals"] if fs["evals"] - s <= 15000 or r["first_in_start"] else s + CENS


def midranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def test(R, tasks, seeds, a, b, f, need_defined=False):
    per_task, kept = {}, {}
    for t in tasks:
        pairs = []
        for s in seeds:
            ra, rb = R.get((t, a, s)), R.get((t, b, s))
            if not ra or not rb:
                continue
            va, vb = f(ra), f(rb)
            if need_defined and (va is None or vb is None):
                continue
            pairs.append((va, vb))
        kept[t] = pairs
        if pairs:
            ranks = midranks([x for p in pairs for x in p])
            per_task[t] = [ranks[2 * i + 1] - ranks[2 * i] for i in range(len(pairs))]  # d = rank(b) - rank(a)
    S = sum(sum(d) / len(d) for d in per_task.values())
    rnd = random.Random(20261119)
    hits = 0
    for _ in range(10000):
        s_star = sum(sum(x if rnd.random() < 0.5 else -x for x in d) / len(d) for d in per_task.values())
        hits += abs(s_star) >= abs(S) - 1e-12
    return {"S": round(S, 4), "p": round((1 + hits) / 10001, 5), "tasks": len(per_task),
            "pairs": sum(len(v) for v in kept.values())}, kept


def effect(R, tasks, seeds, a, b, f):
    logs = []
    excluded = 0
    for t in tasks:
        va = [f(R[(t, a, s)]) for s in seeds if (t, a, s) in R and f(R[(t, a, s)]) is not None]
        vb = [f(R[(t, b, s)]) for s in seeds if (t, b, s) in R and f(R[(t, b, s)]) is not None]
        if not va or not vb:
            excluded += 1; continue
        ma, mb = statistics.median(va), statistics.median(vb)
        if ma >= CENS and mb >= CENS:
            excluded += 1; continue
        logs.append(math.log(mb / ma))
    if not logs:
        return {"median_log_ratio": None, "excluded_tasks": excluded}
    rnd = random.Random(7)
    boots = sorted(statistics.median([rnd.choice(logs) for _ in logs]) for _ in range(5000))
    return {"median_log_ratio": round(statistics.median(logs), 4), "ratio": round(math.exp(statistics.median(logs)), 3),
            "ci95_ratio": [round(math.exp(boots[124]), 3), round(math.exp(boots[4874]), 3)], "tasks": len(logs), "excluded_tasks": excluded}


if __name__ == "__main__":
    R = load()
    tasks = sorted({k[0] for k in R})
    complete = [s for s in range(10) if all((t, a, s) in R for t in tasks for a in ("L", "XR", "XL", "Z"))]
    trivial = [t for t in tasks if sum(o1(R[(t, "Z", s)]) for s in complete if (t, "Z", s) in R) >= 0.8 * max(1, len(complete))]
    core = [t for t in tasks if t not in trivial]
    out = {"runs": len(R), "complete_seed_blocks": complete, "trivial_tasks": trivial, "core_tasks": len(core)}
    h1, kept = test(R, core, complete, "L", "XR", o2, need_defined=True)
    testable = sum(1 for t in core if sum(1 for va, vb in kept.get(t, []) if va < CENS and vb < CENS) >= 3)
    h1["testable_tasks"] = testable
    h1["not_testable"] = testable < 10
    h2, _ = test(R, core, complete, "L", "XR", o1)
    h3, _ = test(R, core, complete, "L", "XR", ot)
    ps = sorted([("H1", h1["p"]), ("H2", h2["p"]), ("H3", h3["p"])], key=lambda x: x[1])
    holm, prev = {}, 0.0
    for i, (h, p) in enumerate(ps):
        prev = max(prev, min(1.0, p * (len(ps) - i))); holm[h] = round(prev, 5)
    out.update({"H1_search_cost": h1, "H2_lookup": h2, "H3_total": h3, "holm": holm,
                "effect_H1": effect(R, core, complete, "L", "XR", o2), "effect_H3": effect(R, core, complete, "L", "XR", ot),
                "lookup_rate": {a: round(sum(o1(R[(t, a, s)]) for t in core for s in complete) / max(1, len(core) * len(complete)), 3)
                                for a in ("L", "XR", "XL", "Z")},
                "solved_rate": {a: round(sum(1 for t in core for s in complete if R[(t, a, s)].get("first_solution")) /
                                         max(1, len(core) * len(complete)), 3) for a in ("L", "XR", "XL", "Z")},
                "secondary_L_vs_XL_total": test(R, core, complete, "L", "XL", ot)[0],
                "secondary_L_vs_Z_total": test(R, core, complete, "L", "Z", ot)[0],
                "setup_failures": sum(1 for r in R.values() if r.get("timeouts", 0) > 0)})
    json.dump(out, open(f"{D}/result_G8b1.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
