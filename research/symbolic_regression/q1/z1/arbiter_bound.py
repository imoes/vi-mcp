"""Z1 planning bound (25.11.2026, exploratory, uses GOLD — never a method): how much would a perfect ARBITER between the two readers
gain? For every single-valued relation group (token-sharing subject, same relation) of a question, the candidates are the R3r values
plus the base values. ORACLE keeps only the candidates matching the gold evidence object when one matches; every other group is merged
primary-first exactly as reader_merge.py pref does (R3r's values if R3r has any, else base's). Multi-valued relations stay as pref.
The score difference ORACLE − PREF is the ceiling of any arbitration (a verifier question, a vote, a third reader) on this set.
usage: arbiter_bound.py DEV.json R3R.jsonl BASE.jsonl OUT.jsonl [oracle|pref]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stated_recall import norm  # noqa: E402

SINGLE = {"father", "mother", "place of birth", "place of death", "place of burial", "date of birth", "date of death", "director",
          "country of citizenship", "publication date", "country of origin", "composer", "performer"}


def match(a, b):
    return set(norm(a)) <= set(norm(b)) or set(norm(b)) <= set(norm(a))


def main(dev_p, r_p, b_p, out, mode="oracle"):
    dev = {q["_id"]: q for q in json.load(open(dev_p))}
    R = {json.loads(l)["id"]: json.loads(l) for l in open(r_p)}
    B = {json.loads(l)["id"]: json.loads(l) for l in open(b_p)}
    changed = 0
    with open(out, "w") as f:
        for i, r in R.items():
            rt = [tuple(t) for rd in r["reads"] for t in rd["triples"]]
            bt = [tuple(t) for rd in B[i]["reads"] for t in rd["triples"]]
            gold = dev[i]["evidences"]

            def keep(s, p, o, primary):
                nonlocal changed
                g = [go for gs, gp, go in gold if gp == p and set(norm(gs)) & set(norm(s))]
                cands = [o2 for s2, p2, o2 in rt + bt if p2 == p and set(norm(s2)) & set(norm(s))]
                if mode == "oracle" and p in SINGLE and g and any(match(go, c) for go in g for c in cands):
                    ok = any(match(go, o) for go in g)          # oracle: keep only gold-matching candidates of this group
                    changed += not ok
                    return ok
                if primary:                                      # pref: primary always kept
                    return True
                return not any(p == p2 and set(norm(s)) & set(norm(s2)) for s2, p2, o2 in rt)

            reads = [dict(rd, triples=[t for t in rd["triples"] if keep(*t, True)]) for rd in r["reads"]] + \
                    [dict(rd, triples=[t for t in rd["triples"] if keep(*t, False)]) for rd in B[i]["reads"]]
            f.write(json.dumps(dict(r, reads=reads), ensure_ascii=False) + "\n")
    print(json.dumps({"mode": mode, "dropped_by_oracle": changed}))


if __name__ == "__main__":
    main(*sys.argv[1:])
