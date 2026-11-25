"""Bit-identical replay check: compare gp2_log.py runs with the stored G8b-1 runs (runs1)."""
import json, sys, glob
I = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..") + "/"
ok = bad = 0
for f in sorted(glob.glob(I + "g8d/replay/*.json")):
    if f.endswith(".worlds.json"): continue
    n = json.load(open(f)); stem = f.rsplit("/", 1)[1]
    s = json.load(open(I + "g8b/runs1/" + stem))
    keys = ["solved", "evals", "first_in_start", "search_cost", "generations", "cex_added"]
    diff = {k: (s.get(k), n.get(k)) for k in keys if s.get(k) != n.get(k)}
    if (s.get("first_solution") or {}).get("program") != (n.get("first_solution") or {}).get("program"): diff["first_program"] = "differs"
    if [x["program"] for x in s.get("solutions", [])] != [x["program"] for x in n.get("solutions", [])]: diff["solutions"] = "differ"
    print(stem, "IDENTICAL" if not diff else diff); ok += not diff; bad += bool(diff)
print("identical", ok, "different", bad)
