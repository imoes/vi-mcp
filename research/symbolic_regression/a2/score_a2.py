"""A2 scoring exactly as PROTOCOL_A2.md fixes it (written after the runs, before looking at any summary; 20.11.2026).
Per task: (1) solved = complete and consistent on ALL listed examples (P = R = 1) within 600 s — share of runs, tasks with >= 1 /
majority of runs solved; (2) size of the returned program in literals incl. head (gp2 'size'; Popper 'Size:'), median over solved
runs; (3) balanced accuracy of the best program on all listed examples (Popper: from its last TP/FN/TN/FP line; with 0 negatives it is
the recall and the task is flagged); (4) time to the first solution (median over solved runs).
GP runs killed at their memory cap (run_a2_gp.exits, exit 137, no JSON) count as 'not solved, resource limit' (amendment 1).
Tasks with < 5 negatives are flagged and summarised separately (protocol 'Limits').
usage: score_a2.py A2_DIR OUT.json"""
import glob
import json
import os
import re
import statistics as st
import sys
from collections import defaultdict

A = sys.argv[1]
tasks = [l.split()[1] for l in open(os.path.join(A, "list.txt")) if l.startswith("OK")]
SOL = re.compile(r"Precision:([\d.]+) Recall:([\d.]+) TP:(\d+) FN:(\d+) TN:(\d+) FP:(\d+) Size:(\d+)")
BEST = re.compile(r"^([\d.]+)s tp:(\d+) fn:(\d+) tn:(\d+) fp:(\d+) size:(\d+)", re.M)


def ba(tp, fn, tn, fp):
    r = tp / (tp + fn) if tp + fn else 0.0
    return r if tn + fp == 0 else (r + tn / (tn + fp)) / 2


def med(v):
    return round(st.median(v), 3) if v else None


exits = defaultdict(list)
for l in open(os.path.join(A, "run_a2_gp.exits")):
    m = re.search(r"(\S+) s(\d) exit (\d+)", l)
    if m:
        exits[(m.group(1), int(m.group(2)))].append(int(m.group(3)))
out = {}
for t in tasks:
    gp = {"runs": 0, "solved": 0, "resource_limit": 0, "size": [], "ba": [], "t_first": [], "pos": None, "neg": None}
    for s in range(5):
        f = os.path.join(A, "gp_runs", f"{t}__s{s}.json")
        gp["runs"] += 1
        if not os.path.exists(f):
            gp["resource_limit"] += 137 in exits.get((t, s), [])
            continue
        d = json.load(open(f))
        gp["pos"], gp["neg"] = d["pos"], d["neg"]
        gp["ba"].append(d["best_training"]["balanced_accuracy"])
        if d["solved"]:
            gp["solved"] += 1
            gp["size"].append(d["smallest_solution"]["size"]); gp["t_first"].append(d["first_solution"]["seconds"])
    pp = {"runs": 0, "solved": 0, "size": [], "ba": [], "t_first": [], "timeout": 0}
    for r in range(3):
        f = os.path.join(A, "popper_runs", f"{t}__r{r}.log")
        if not os.path.exists(f):
            continue
        txt = open(f, errors="replace").read()
        pp["runs"] += 1
        sols = SOL.findall(txt)
        ex = re.search(r"popper_exit=(\d+) popper_seconds=([\d.]+)", txt)
        if ex and ex.group(1) == "124":
            pp["timeout"] += 1
        if sols:
            p, rc, tp, fn, tn, fp, size = sols[-1]
            tp, fn, tn, fp, size = map(int, (tp, fn, tn, fp, size))
            pp["ba"].append(ba(tp, fn, tn, fp))
            if float(p) == 1.0 and float(rc) == 1.0:
                pp["solved"] += 1; pp["size"].append(size)
                # first hypothesis that is already complete and consistent (Popper prints the SOLUTION block only when it stops)
                first = next((float(b[0]) for b in BEST.findall(txt) if b[2] == "0" and b[4] == "0"), None)
                tsol = re.search(r"^([\d.]+)s \*+ SOLUTION", txt, re.M)
                pp["t_first"].append(first if first is not None else float(tsol.group(1)) if tsol else None)
        else:
            bs = BEST.findall(txt)
            if bs:
                _t, tp, fn, tn, fp, _sz = bs[-1]
                pp["ba"].append(ba(*map(int, (tp, fn, tn, fp))))
    out[t] = {"flag_few_negatives": gp["neg"] is not None and gp["neg"] < 5, "pos": gp["pos"], "neg": gp["neg"],
              "gp": {"solved": f"{gp['solved']}/{gp['runs']}", "resource_limit": gp["resource_limit"], "size_median": med(gp["size"]),
                     "ba_median": med(gp["ba"]), "t_first_median_s": med(gp["t_first"])},
              "popper": {"solved": f"{pp['solved']}/{pp['runs']}", "timeouts": pp["timeout"], "size_median": med(pp["size"]),
                         "ba_median": med(pp["ba"]), "t_first_median_s": med([x for x in pp["t_first"] if x is not None])}}


def summary(keys):
    def cnt(arm, cond):
        return sum(1 for k in keys if cond(*map(int, out[k][arm]["solved"].split("/"))))
    return {"tasks": len(keys),
            "gp_any": cnt("gp", lambda a, n: a >= 1), "gp_majority": cnt("gp", lambda a, n: a * 2 > n),
            "popper_any": cnt("popper", lambda a, n: a >= 1), "popper_majority": cnt("popper", lambda a, n: a * 2 > n),
            "both_solved_size_gp_le_popper": sum(1 for k in keys if out[k]["gp"]["size_median"] and out[k]["popper"]["size_median"]
                                                 and out[k]["gp"]["size_median"] <= out[k]["popper"]["size_median"]),
            "both_solved": sum(1 for k in keys if out[k]["gp"]["size_median"] and out[k]["popper"]["size_median"])}


clean = [k for k in out if not out[k]["flag_few_negatives"]]
flagged = [k for k in out if out[k]["flag_few_negatives"]]
res = {"per_task": out, "summary_all": summary(list(out)), "summary_neg_ge_5": summary(clean), "summary_flagged_neg_lt_5": summary(flagged),
       "flagged": flagged}
json.dump(res, open(sys.argv[2], "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "per_task"}, indent=1))
for k, v in out.items():
    print(f"{k:42s} {'F' if v['flag_few_negatives'] else ' '} GP {v['gp']['solved']:>4} rl{v['gp']['resource_limit']} size {v['gp']['size_median']} "
          f"ba {v['gp']['ba_median']} t {v['gp']['t_first_median_s']} | Popper {v['popper']['solved']:>4} size {v['popper']['size_median']} "
          f"ba {v['popper']['ba_median']} t {v['popper']['t_first_median_s']}")
