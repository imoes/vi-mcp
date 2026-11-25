"""PREREG_R3r analysis (vi-mcp-sr docs/PREREG_R3r.md). Inputs: the three fresh2 read files (R1-full 0-shot, base 2-shot from the
3070 host; R3r 0-shot from the pod) and the per-question files of official_score.py for the arms. Builds the unions in the Q1 order
(fine-tuned reader first, then base — as score_fresh.sh did for the fresh 400), and tests H-R3r1 by an exact one-sided McNemar.
usage: score_r3r.py union R1FULL BASE R3R IDS.json OUT_OLD OUT_NEW
       score_r3r.py test PER_OLD PER_NEW [PER_R1FULL PER_BASE PER_R3R]"""
import json
import sys
from math import comb


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def union(a, b, ids, out):
    with open(out, "w") as f:
        for i in ids:
            r = dict(a[i]); r["reads"] = a[i]["reads"] + b[i]["reads"]; f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    if sys.argv[1] == "union":
        r1, base, r3, ids_path, out_old, out_new = sys.argv[2:8]
        ids = [q["_id"] for q in json.load(open(ids_path))]
        A, B, C = load(r1), load(base), load(r3)
        assert set(ids) == set(A) == set(B) == set(C), (len(ids), len(A), len(B), len(C))
        union(A, B, ids, out_old); union(C, B, ids, out_new)
        print(json.dumps({"union": len(ids)}))
        return
    old, new = load(sys.argv[2]), load(sys.argv[3])
    ids = sorted(old); assert set(ids) == set(new)
    b = sum(new[i]["em_alias"] > old[i]["em_alias"] for i in ids); c = sum(new[i]["em_alias"] < old[i]["em_alias"] for i in ids)
    p = sum(comb(b + c, k) for k in range(b, b + c + 1)) / 2 ** (b + c) if b + c else 1.0
    out = {"H_R3r1": {"new_only": b, "old_only": c, "p_one_sided": round(p, 6), "holds": p < 0.05,
                      "em_old": sum(old[i]["em_alias"] for i in ids) / len(ids), "em_new": sum(new[i]["em_alias"] for i in ids) / len(ids)}}
    for name, path in zip(("r1full", "base", "r3r"), sys.argv[4:7]):
        d = load(path); out[f"em_single_{name}"] = sum(d[i]["em_alias"] for i in ids) / len(ids)
    types = sorted({old[i]["type"] for i in ids})
    out["by_type"] = {t: {"old": sum(old[i]["em_alias"] for i in ids if old[i]["type"] == t),
                          "new": sum(new[i]["em_alias"] for i in ids if new[i]["type"] == t)} for t in types}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
