"""G8 scoring exactly as prereg_G8.md: H1 L>Z solved pairs, H2 L<Z evaluations, H3 L>T solved pairs; Holm; secondary descriptives."""
import collections, glob, json, os
from math import comb

D = os.path.dirname(os.path.abspath(__file__))
BUDGET = 10000
R = {}
for f in glob.glob(f"{D}/runs/*.json"):
    r = json.load(open(f))
    R[(r["task"], r["arm"], r["seed"])] = r
tasks = sorted({k[0] for k in R}); seeds = sorted({k[2] for k in R})
pairs = [(t, s) for t in tasks for s in seeds]
missing = [(t, a, s) for t, s in pairs for a in "LZTS" if (t, a, s) not in R]
assert not missing, f"{len(missing)} runs missing, e.g. {missing[:3]}"


def sign(plus, minus):
    n = plus + minus
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(plus, minus) + 1)) / 2 ** n)


def solved(a, t, s):
    return R[(t, a, s)]["solved"]


def evals(a, t, s):
    r = R[(t, a, s)]
    return r["evals_to_solve"] if r["solved"] else BUDGET + 1


def solved_test(a, b):
    plus = sum(solved(a, t, s) and not solved(b, t, s) for t, s in pairs)
    minus = sum(solved(b, t, s) and not solved(a, t, s) for t, s in pairs)
    return {"only_" + a: plus, "only_" + b: minus, "p": round(sign(plus, minus), 5)}


def evals_test(a, b):
    plus = sum(evals(a, t, s) < evals(b, t, s) for t, s in pairs)
    minus = sum(evals(a, t, s) > evals(b, t, s) for t, s in pairs)
    return {a + "_faster": plus, b + "_faster": minus, "p": round(sign(plus, minus), 5)}


res = {"runs": len(R), "pairs": len(pairs),
       "solved_pairs": {a: sum(solved(a, t, s) for t, s in pairs) for a in "LZTS"},
       "per_task": {t: {a: sum(solved(a, t, s) for s in seeds) for a in "LZTS"} for t in tasks},
       "median_evals_when_solved": {a: sorted(evals(a, t, s) for t, s in pairs if solved(a, t, s))[
           len([1 for t, s in pairs if solved(a, t, s)]) // 2] if any(solved(a, t, s) for t, s in pairs) else None for a in "LZTS"},
       "H1_L_vs_Z_solved": solved_test("L", "Z"), "H2_L_vs_Z_evals": evals_test("L", "Z"), "H3_L_vs_T_solved": solved_test("L", "T"),
       "secondary": {"S_vs_Z_solved": solved_test("S", "Z"), "S_vs_L_solved": solved_test("S", "L")}}
ps = sorted([("H1", res["H1_L_vs_Z_solved"]["p"]), ("H2", res["H2_L_vs_Z_evals"]["p"]), ("H3", res["H3_L_vs_T_solved"]["p"])],
            key=lambda x: x[1])
holm, prev = {}, 0.0
for i, (h, p) in enumerate(ps):
    prev = max(prev, min(1.0, p * (len(ps) - i))); holm[h] = round(prev, 5)
res["holm"] = holm
sp = res["solved_pairs"]
res["verdict"] = {
    "H1": "supported" if sp["L"] > sp["Z"] and holm["H1"] < 0.05 else "refuted (L <= Z or not significant)",
    "H2": "supported" if res["H2_L_vs_Z_evals"]["L_faster"] > res["H2_L_vs_Z_evals"]["Z_faster"] and holm["H2"] < 0.05 else "not supported",
    "H3": "supported" if sp["L"] > sp["T"] and holm["H3"] < 0.05 else "not supported"}
res["L_solution_origins"] = dict(collections.Counter(R[(t, "L", s)]["solution"]["origin"] for t, s in pairs if solved("L", t, s)).most_common())
res["S_solution_origins"] = dict(collections.Counter(R[(t, "S", s)]["solution"]["origin"] for t, s in pairs if solved("S", t, s)).most_common())
json.dump(res, open(f"{D}/result_G8.json", "w"), indent=1)
print(json.dumps(res, indent=1))
