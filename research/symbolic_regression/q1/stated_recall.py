"""Reader measure (21.11.2026): recall of STATED gold facts per relation. A gold evidence triple (s, r, o) of a 2Wiki question counts
when the subject's context paragraph contains the object's normalised token sequence; it is recalled when the reads contain a triple
with relation r, a subject sharing a token with s, and an object whose token set contains or is contained in o's. Precision is not
measured (gold is incomplete: 2Wiki lists only the facts the question needs). Precision proxy (added 19:36 UTC): for every stated gold
triple, CONFLICT = the reads also contain the same relation for that subject with an object that matches no gold object of that
(subject, relation) — a wrong value competes with the right one in the solver (father, mother, places and countries are mostly
single-valued in 2Wiki questions).
usage: stated_recall.py DEV.json READS.jsonl [READS2.jsonl ...]"""
import collections
import json
import re
import sys


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s*\(.*?\)\s*$", "", s.lower())).split()


def stated(o, para):
    t = norm(o); p = " " + " ".join(norm(para)) + " "
    return bool(t) and (" " + " ".join(t) + " ") in p


def recall(dev, reads):
    rec = collections.defaultdict(lambda: [0, 0, 0])
    for i, r in reads.items():
        q = dev[i]; ctx = {t: " ".join(x) for t, x in q["context"]}
        trip = [(s, p, o) for rd in r["reads"] for s, p, o in rd["triples"]]
        for s, p, o in q["evidences"]:
            para = next((v for t, v in ctx.items() if norm(t) == norm(s)), None)
            if para is None or not stated(o, para):
                continue
            hit = any(p == p2 and (set(norm(o)) <= set(norm(o2)) or set(norm(o2)) <= set(norm(o))) and set(norm(s)) & set(norm(s2))
                      for s2, p2, o2 in trip)
            gold_objs = [o3 for s3, p3, o3 in q["evidences"] if p3 == p and set(norm(s3)) & set(norm(s))]
            conflict = any(p == p2 and set(norm(s)) & set(norm(s2)) and not any(set(norm(g)) <= set(norm(o2)) or set(norm(o2)) <= set(norm(g)) for g in gold_objs)
                           for s2, p2, o2 in trip)
            rec[p][0] += hit; rec[p][1] += 1; rec[p][2] += conflict
    return rec


def main():
    dev = {q["_id"]: q for q in json.load(open(sys.argv[1]))}
    out = {}
    for f in sys.argv[2:]:
        reads = {json.loads(l)["id"]: json.loads(l) for l in open(f)}
        rec = recall(dev, reads)
        tot = [sum(v[0] for v in rec.values()), sum(v[1] for v in rec.values()), sum(v[2] for v in rec.values())]
        out[f] = {"questions": len(reads), "stated_recall": [tot[0], tot[1], round(tot[0] / max(1, tot[1]), 4)],
                  "conflicts": [tot[2], tot[1], round(tot[2] / max(1, tot[1]), 4)],
                  "by_relation": {p: {"hit": h, "n": n, "conflict": c} for p, (h, n, c) in sorted(rec.items(), key=lambda x: -x[1][1])}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
