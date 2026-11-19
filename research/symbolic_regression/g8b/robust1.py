"""G8b-1 amendment 1: re-check every first verified solution on 1,000 NEW big worlds per task (same worlds for every arm and seed).
Writes robust1.json {"task|arm|seed": true/false}; score1.py's sensitivity analysis counts non-robust solutions as unsolved.
usage: robust1.py [--workers N]"""
import argparse, glob, json, os, random, sys
from concurrent.futures import ProcessPoolExecutor

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
sys.path.insert(0, os.path.join(D, "..", "..", "blind_tasks"))
sys.path.insert(0, os.path.join(D, "..", "g8"))
import blind_tasks as BT  # noqa: E402
import g8_eval as E  # noqa: E402

E.TIMEOUT = 10.0
N = 1000
_cache = {}


def worlds(name):
    if name not in _cache:
        rnd = random.Random(f"{name}:robust:1")
        ws = [BT.world_text(name, rnd, big=True) for _ in range(N)]
        t = BT.TASKS[name]
        _cache[name] = (ws, [E.answers(t["REFERENCE"], w, t["answers"]) for w in ws])
    return _cache[name]


def check(job):
    key, name, prog = job
    ws, gold = worlds(name)
    t = BT.TASKS[name]
    for w, g in zip(ws, gold):
        if E.answers(prog, w, t["answers"]) != g:
            return key, False
    return key, True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); o = ap.parse_args()
    jobs = []
    for f in glob.glob(f"{D}/runs1/*.json"):
        if f.endswith((".first.json", ".start.json")):
            continue
        r = json.load(open(f))
        fs = r.get("first_solution")
        if fs:
            jobs.append((f"{r['task']}|{r['arm']}|{r['seed']}", r["task"], fs["program"]))
    jobs.sort(key=lambda j: j[1])  # group by task: each worker builds a task's worlds once
    out = {}
    with ProcessPoolExecutor(o.workers) as ex:
        for k, ok in ex.map(check, jobs, chunksize=8):
            out[k] = ok
    json.dump(out, open(f"{D}/robust1.json", "w"), indent=1)
    print(len(out), "solutions checked;", sum(out.values()), "robust")
