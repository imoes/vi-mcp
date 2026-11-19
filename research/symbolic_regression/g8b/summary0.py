"""G8b-0 summary (note_G8b0.md): solved seeds per task, evaluations to the first solve, the shortest solution per task."""
import glob, json, os, statistics

D = os.path.dirname(os.path.abspath(__file__))
R = [json.load(open(f)) for f in sorted(glob.glob(f"{D}/runs0/*.json"))]
tasks = sorted({r["task"] for r in R})
out = {"runs": len(R), "per_task": {}}
for t in tasks:
    rs = [r for r in R if r["task"] == t]
    solved = [r for r in rs if r["solved"]]
    first = sorted(min(s["evals"] for s in r["solutions"]) for r in solved)
    shortest = min((r["best"] for r in solved), key=lambda b: b["size"], default=None)
    out["per_task"][t] = {"solved": f"{len(solved)}/{len(rs)}",
                          "median_evals_first_solve": statistics.median(first) if first else None,
                          "cex_added_median": statistics.median([r["cex_added"] for r in rs]),
                          "shortest": shortest and {"size": shortest["size"], "program": shortest["program"]}}
out["solved_total"] = sum(r["solved"] for r in R)
json.dump(out, open(f"{D}/result_G8b0.json", "w"), indent=1)
print(json.dumps(out, indent=1))
