"""Z6 analysis (PREREG_Z6): per question both-pages@4 for BASE and M1; exact one-sided McNemar (M1 > BASE); the difference in
percentage points with a 95 % bootstrap CI that resamples VMs (6 questions per VM share their pages), random.Random("z6-boot"),
10,000 draws; descriptive per relation and language.
usage: z6_score.py BASE.jsonl M1.jsonl"""
import json
import random
import sys
from collections import defaultdict
from math import comb


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


base, m1 = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(base)
assert set(ids) == set(m1), (len(base), len(m1))
b = sum(m1[i]["both4"] and not base[i]["both4"] for i in ids)
c = sum(base[i]["both4"] and not m1[i]["both4"] for i in ids)
p = sum(comb(b + c, k) for k in range(b, b + c + 1)) / 2 ** (b + c) if b + c else 1.0
vm_of = {i: i.split(":")[1] for i in ids}
groups = defaultdict(list)
for i in ids:
    groups[vm_of[i]].append(i)
keys = sorted(groups)
rnd = random.Random("z6-boot")
diffs = []
for _ in range(10000):
    sample = [i for k in (rnd.choice(keys) for _ in keys) for i in groups[k]]
    diffs.append(sum(m1[i]["both4"] - base[i]["both4"] for i in sample) / len(sample))
diffs.sort()
rate = lambda d: round(sum(d[i]["both4"] for i in ids) / len(ids), 4)
by = defaultdict(lambda: [0, 0, 0])
for i in ids:
    k = "/".join(i.split(":")[2:4]); by[k][0] += base[i]["both4"]; by[k][1] += m1[i]["both4"]; by[k][2] += 1
print(json.dumps({"n": len(ids), "vms": len(keys), "both4_base": rate(base), "both4_m1": rate(m1),
                  "diff_points": round(100 * (rate(m1) - rate(base)), 2),
                  "ci95_points_vm_bootstrap": [round(100 * diffs[249], 2), round(100 * diffs[9749], 2)],
                  "m1_only": b, "base_only": c, "p_one_sided": p, "H_Z6a_holds": p < 0.05,
                  "H_Z6b_goal_10_points": (rate(m1) - rate(base)) >= 0.10,
                  "by_relation_lang_base_m1_n": dict(by)}, indent=1))
