"""Confirmatory analysis of R2-small (PREREG_R2_small.md part B; PREREG_R2_small_C.md part C), unit = seed, final eval step.
H-B1 / H-C1 / H-C2: one-sided exact Mann-Whitney U on the per-seed testD faithful accuracy, ARM_HI > ARM_LO, alpha 0.05.
H-B2: 95 % bootstrap CI (10,000 resamples of seeds per arm, seed 0) of mean(ARM_HI) - mean(ARM_LO) on testI; holds if lower > -0.05.
Note 1 (descriptive): on testD, the share of items whose FIRST THREE use lines are all valid (checked by truncating goal and output
to the first three literals / use lines and running the same clingo check).
usage: analyze_r2b.py DATA_DIR ARM_HI ARM_LO RESULT.json ... [--data-lo DATA_DIR_LO]
(--data-lo: the low arm's data dir when the arms come from different parts, e.g. memI (synth_idx) vs mem (synth_v1))"""
import itertools
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gen_traces_synth as G  # noqa: E402
import score_r2b as S  # noqa: E402


def items_of(data):
    out = {}
    for f in Path(data).glob("*_test*.jsonl"):
        for l in open(f):
            it = json.loads(l); out[it["id"]] = it
    return out


def first3(it, out, lib):
    """True when the first three use lines are valid instances in goal order (depth >= 3)"""
    goal = re.search(r"Goal: answer\(Y\) <= (.*)", it["prompt"]).group(1)
    lits = goal.split(" & ")[:3]
    uses = [l for l in out.splitlines() if l.startswith("use ")][:3]
    if len(uses) < 3:
        return False
    m = re.search(r"⇒ \w+\(\w+, (\w+)\)$", uses[-1])
    if not m:
        return False
    it2 = dict(it, prompt=it["prompt"].replace(goal, " & ".join(lits)))
    return G.check(it2, "\n".join(uses) + f"\nanswer: {m.group(1)}", lib)["faithful"]


def mwu_one_sided(hi, lo):
    """exact P(U >= u_obs) under H0 by enumerating all splits of the pooled values (ties: midrank-free count of pairs, 0.5)"""
    def u(a, b):
        return sum((x > y) + 0.5 * (x == y) for x in a for y in b)
    obs = u(hi, lo); pool = hi + lo; n = len(hi); ge = tot = 0
    for idx in itertools.combinations(range(len(pool)), n):
        s = set(idx); a = [pool[i] for i in idx]; b = [pool[i] for i in range(len(pool)) if i not in s]
        tot += 1; ge += u(a, b) >= obs - 1e-12
    return obs, ge / tot


def main():
    data, hi_arm, lo_arm = sys.argv[1], sys.argv[2], sys.argv[3]
    files = [a for a in sys.argv[4:] if a.endswith(".json")]
    data_lo = sys.argv[sys.argv.index("--data-lo") + 1] if "--data-lo" in sys.argv else data
    lib = G.library(random.Random(1000))
    items = {**items_of(data), **items_of(data_lo)}
    per = {}  # (arm, seed) -> metrics at the final step
    for p in files:
        res = json.load(open(p))
        arm, seed = (res.get("args") or {}).get("arm", res.get("arm")), (res.get("args") or {}).get("seed", res.get("seed"))
        if arm is None:
            m = re.search(r"_(\w+?)_s(\d+)$", Path(p).stem); arm, seed = m.group(1), int(m.group(2))
        if arm not in (hi_arm, lo_arm):
            continue
        step = max(res["evals"], key=int)
        met = {"step": int(step)}
        for sname, rows in res["evals"][step].items():
            f = c = f3 = n3 = 0; dep = {}
            for r in rows:
                it = items[r["id"]]; out = S.detok(r["gen"]); ch = G.check(it, out, lib)
                f += ch["faithful"]; c += ch["correct"]
                d = dep.setdefault(it["depth"], [0, 0]); d[0] += 1; d[1] += ch["faithful"]
                if sname.lower().endswith("d"):
                    n3 += 1; f3 += first3(it, out, lib)
            met[sname] = {"faithful": f / len(rows), "answer": c / len(rows),
                          "by_depth": {k: round(v[1] / v[0], 4) for k, v in sorted(dep.items())}}
            if n3:
                met[sname]["first3_valid"] = f3 / n3
        per[(arm, seed)] = met
    def vals(arm, key, field="faithful"):
        return [m[k][field] for (a, _s), m in sorted(per.items()) if a == arm for k in m if k != "step" and k.lower().endswith(key)]
    hiD, loD = vals(hi_arm, "testd"), vals(lo_arm, "testd")
    hiI, loI = vals(hi_arm, "testi"), vals(lo_arm, "testi")
    u, p = mwu_one_sided(hiD, loD) if hiD and loD else (None, None)
    rnd = random.Random(0); diffs = []
    for _ in range(10000):
        a = [rnd.choice(hiI) for _ in hiI]; b = [rnd.choice(loI) for _ in loI]
        diffs.append(sum(a) / len(a) - sum(b) / len(b))
    diffs.sort()
    out = {"arms": [hi_arm, lo_arm], "seeds": {hi_arm: len(hiD), lo_arm: len(loD)},
           "testD_faithful_mean": {hi_arm: sum(hiD) / max(1, len(hiD)), lo_arm: sum(loD) / max(1, len(loD))},
           "testD_mwu_one_sided": {"U": u, "p": p},
           "testI_faithful_mean": {hi_arm: sum(hiI) / max(1, len(hiI)), lo_arm: sum(loI) / max(1, len(loI))},
           "testI_diff_ci95": [diffs[249], diffs[9749]] if hiI and loI else None,
           "testD_first3_valid_mean": {arm: (lambda v: sum(v) / max(1, len(v)))(vals(arm, "testd", "first3_valid")) for arm in (hi_arm, lo_arm)},
           "per_seed": {f"{a}_s{s}": m for (a, s), m in sorted(per.items())}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
