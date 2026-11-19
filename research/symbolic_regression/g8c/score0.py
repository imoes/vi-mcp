"""G8c-0 scoring, exactly as prereg_G8c0.md fixes it (written after the runs, before looking at any arm comparison):
- O2 per (dream, seed, arm); censored = 15,001; a (dream, seed) with a start-phase solution is undefined in every arm (identical starts).
- Ceiling ratio: per dream median O2(U) / median O2(O) over its defined seeds; the median over dreams (dreams with all arms censored excluded).
- O vs P and O vs M: the G8b-1 statistic — dream = unit; within each dream the retained values of both arms get midranks; d = rank(other) −
  rank(O) per pair; S = sum over dreams of the mean d; 10,000 sign flips of the pairs (RNG seed 20261119); two-sided p; each must be < 0.05
  (conjunction, no Holm). PASS iff ratio >= 1.5 and both p < 0.05 with O cheaper.
Runs missing in ALL arms of a (dream, seed) (timeouts) are excluded and counted.
usage: score0.py -> result_G8c0.json"""
import glob, json, os, random, statistics
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
CENS = 15001
R = {}
for f in glob.glob(f"{D}/runs0/*.json"):
    r = json.load(open(f))
    R[(r["idx"], r["seed"], r["arm"])] = r
keys = sorted({(i, s) for i, s, _a in R})
missing = sorted({(i, s) for i in range(30) for s in range(3)} - set(keys))
lookup = sorted((i, s) for i, s in keys if any(R.get((i, s, a), {}).get("first_in_start") for a in "UOPM"))
inconsistent = [(i, s) for i, s in keys if len({R[(i, s, a)]["first_in_start"] for a in "UOPM" if (i, s, a) in R}) > 1]


def o2(i, s, a):
    r = R.get((i, s, a))
    if r is None or r["first_in_start"]:
        return None
    return CENS if r["O2"] is None or r["O2"] > 15000 else r["O2"]


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda k: vals[k])
    rk = [0.0] * len(vals); k = 0
    while k < len(order):
        j = k
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[k]]:
            j += 1
        for t in range(k, j + 1):
            rk[order[t]] = (k + j) / 2 + 1
        k = j + 1
    return rk


def test(other):
    per = []
    for i in range(30):
        pairs = [(o2(i, s, "O"), o2(i, s, other)) for s in range(3)]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        if not pairs:
            continue
        rk = ranks([a for a, _ in pairs] + [b for _, b in pairs])
        n = len(pairs)
        per.append([rk[n + k] - rk[k] for k in range(n)])
    S = sum(sum(d) / len(d) for d in per)
    rnd = random.Random(20261119)
    hits = 0
    for _ in range(10000):
        Ss = sum(sum(x * rnd.choice((1, -1)) for x in d) / len(d) for d in per)
        hits += abs(Ss) >= abs(S)
    return {"S": round(S, 4), "p": round((1 + hits) / 10001, 5), "dreams": len(per), "pairs": sum(map(len, per)),
            "direction": "O cheaper" if S > 0 else "O dearer" if S < 0 else "tie"}


ratios, excl = [], 0
per_k = defaultdict(list)
dreams = {d["idx"]: d for d in json.load(open(f"{D}/dreams.json"))["dreams"]}
for i in range(30):
    u = [o2(i, s, "U") for s in range(3)]; o = [o2(i, s, "O") for s in range(3)]
    u = [x for x in u if x is not None]; o = [x for x in o if x is not None]
    if not u or not o:
        continue
    if all(x == CENS for x in u + o):
        excl += 1; continue
    r = statistics.median(u) / statistics.median(o)
    ratios.append(r); per_k[dreams[i]["k"]].append(r)
res = {"runs": len(R), "missing_all_arms": missing, "start_phase_solved_pairs": len(lookup), "inconsistent_start": inconsistent,
       "dreams_with_ratio": len(ratios), "dreams_all_censored_excluded": excl,
       "median_ratio_U_over_O": round(statistics.median(ratios), 3) if ratios else None,
       "ratio_by_k": {k: round(statistics.median(v), 3) for k, v in sorted(per_k.items())},
       "O_vs_P": test("P"), "O_vs_M": test("M"), "U_vs_O_descriptive": test("U"),
       "solved_rate": {a: round(sum(1 for (i, s, aa), r in R.items() if aa == a and r["solved"]) / max(1, sum(1 for k in R if k[2] == a)), 3)
                       for a in "UOPM"}}
mr = res["median_ratio_U_over_O"] or 0
res["PASS"] = bool(mr >= 1.5 and all(res[t]["p"] < 0.05 and res[t]["direction"] == "O cheaper" for t in ("O_vs_P", "O_vs_M")))
json.dump(res, open(f"{D}/result_G8c0.json", "w"), indent=1)
print(json.dumps(res, indent=1))
