"""fresh4 (22.11.2026): 100 questions per type from the 2WikiMultiHopQA dev set, disjoint by id from every set used so far
(development 400, fresh 400, fresh2, fresh3), drawn with random.Random("q1-fresh4-2026-11-22") from the sorted remaining ids.
usage: make_fresh4.py DEV.json OUT.json USED1.json [USED2.json ...]"""
import json
import random
import sys

dev = json.load(open(sys.argv[1]))
used = {q["_id"] for p in sys.argv[3:] for q in json.load(open(p))}
rng = random.Random("q1-fresh4-2026-11-22")
out = []
for t in ("bridge_comparison", "comparison", "compositional", "inference"):
    pool = sorted(q["_id"] for q in dev if q["type"] == t and q["_id"] not in used)
    pick = set(rng.sample(pool, 100))
    out += [q for q in dev if q["_id"] in pick]
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
print(json.dumps({"n": len(out), "used_excluded": len(used)}))
