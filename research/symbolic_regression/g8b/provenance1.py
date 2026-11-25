"""G8b-1 provenance (prereg_G8b1.md section "Provenance (S8)") — IMPLEMENTED AFTER THE DATA WERE SEEN (19.11.2026, after score1.py);
the analysis follows the protocol's wording, nothing else is tested. Descriptive, no claim.
Protocol: "the share of L solutions with a rule matching (near.matches, bodies >= 2 literals) a rule of its origin block; base rates: the
same share for XR/XL solutions against their UNSCRAMBLED origin block, and for L solutions against a random other block."
Added for reading (also descriptive): the same shares split by whether the first solution was a start candidate (lookup) or found by
search — the H1 question is about the searched ones. Base rate 'random other block': one other block per solution (seeded) and the mean
over all other blocks.
usage: provenance1.py -> provenance1.json"""
import glob, json, os, random, sys
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
import arms2  # noqa: E402
import grade  # noqa: E402
import near  # noqa: E402

LIB = {b: [r for r in rules if len([l for l in r[1] if l[0] != "!="]) >= 2] for b, rules in arms2.library()}
BLOCKS = sorted(LIB)


def nontrivial(prog):
    rules = [r for r in (grade.parse(x) for x in prog.splitlines() if x.strip()) if r]
    return [r for r in rules if len([l for l in r[1] if l[0] != "!="]) >= 2]


def hit(sol_rules, block):
    return any(near.matches(s, lr) for s in sol_rules for lr in LIB.get(block, []))


def share(xs):
    return {"n": len(xs), "share": round(sum(xs) / len(xs), 4) if xs else None}


if __name__ == "__main__":
    rnd = random.Random(20261119)
    acc = defaultdict(list)
    skipped = defaultdict(int)
    for f in sorted(glob.glob(f"{D}/runs1/*.json")):
        if f.endswith((".first.json", ".start.json")):
            continue
        r = json.load(open(f))
        fs = r.get("first_solution")
        if not fs:
            continue
        origin = fs.get("origin", "?").split("~")[0]  # XR/XL blocks are "<block>~rewired|~relinked": compare with the UNSCRAMBLED block
        if origin not in LIB:
            skipped[f"{r['arm']}:{origin.split(':')[0] if ':' in origin else origin}"] += 1
            continue
        sol = nontrivial(fs["program"])
        how = "start" if r.get("first_in_start") else "search"
        own = hit(sol, origin)
        acc[(r["arm"], "origin", "all")].append(own)
        acc[(r["arm"], "origin", how)].append(own)
        if r["arm"] == "L":
            other = rnd.choice([b for b in BLOCKS if b != origin])
            o1 = hit(sol, other)
            acc[("L", "random_other", "all")].append(o1); acc[("L", "random_other", how)].append(o1)
            mean_other = sum(hit(sol, b) for b in BLOCKS if b != origin) / (len(BLOCKS) - 1)
            acc[("L", "mean_other", "all")].append(mean_other); acc[("L", "mean_other", how)].append(mean_other)
    out = {"note": "implemented after the data were seen; descriptive only (prereg S8)",
           "shares": {f"{a}|{k}|{h}": share(v) for (a, k, h), v in sorted(acc.items())},
           "skipped_no_library_origin": dict(skipped), "library_blocks": len(BLOCKS)}
    json.dump(out, open(f"{D}/provenance1.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
