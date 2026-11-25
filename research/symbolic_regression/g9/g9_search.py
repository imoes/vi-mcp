"""G9 search: symbolic regression of failure rules over the VI's experiences with gp2 (the G8b-1 search, unchanged), then the Popper
gate on the FUTURE (test >= 2026-11-13): a rule counts only if its precision on the test period exceeds the test base rate with the
lower Wilson 95 % bound. Model selection on the validation day only; the test is read once per run.
Fitness = mean F1 of predicted failed(E) atoms per world (lexicase over the 20 train worlds); the archive keeps the best fit per size;
the chosen program = the archive entry with the best validation F1 (ties: smaller).
usage: g9_search.py SEED OUTDIR [--budget N]"""
import argparse, json, math, os, random, sys, time

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(D, "..", "g8b"))
import gp2 as gp  # noqa: E402

DATA = os.path.join(D, os.environ.get("G9_DATA", "data"))


class ExpTask:
    """the interface gp2.Search and gp2.Gen read, built from data files instead of a hidden reference"""
    def __init__(self, seed):
        meta = json.load(open(f"{DATA}/meta.json"))
        tr = json.load(open(f"{DATA}/train.json"))
        self.name, self.ref = "experiences", None
        self.inputs = {"tool": 2, "topic": 2, "host": 2, "inst": 2, "prev_fail_tool": 1, "prev_fail_conv": 1, "action": 1}
        self.answers = {"failed": 1}
        self.train = [w["facts"] for w in tr]
        self.gold = [frozenset(w["gold"]) for w in tr]
        # an exact program on all train worlds would be checked on the validation worlds (never a "solution" by itself)
        va = json.load(open(f"{DATA}/valid.json"))
        self.verify, self.verify_gold = [w["facts"] for w in va], [frozenset(w["gold"]) for w in va]
        self.stress, self.stress_gold = [], []
        ent = ("entity",)
        self.type_of = {(p, 0): ent for p in self.inputs}
        self.type_of[("failed", 0)] = ent
        for p in ("tool", "topic", "host", "inst"):
            self.type_of[(p, 1)] = ("value", p)
        c = meta["constants"]
        self.consts = {("tool", 1): c["tool"], ("topic", 1): c["topic"], ("host", 1): c["host"], ("inst", 1): c["inst"]}


def metrics(prog_text, worlds):
    tp = fp = fn = n = 0
    for w in worlds:
        got = gp.E.answers(prog_text, w["facts"], {"failed": 1})
        if got is None:  # a world the program cannot be solved on is an error, never "predicts nothing" (it hid a dead search once)
            raise RuntimeError(f"program fails on a world ({len(w['facts'].splitlines())} facts): {prog_text[:120]}")
        g = frozenset(w["gold"])
        tp += len(got & g); fp += len(got - g); fn += len(g - got); n += w["n"]
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "n": n, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int); ap.add_argument("out"); ap.add_argument("--budget", type=int, default=6000)
    o = ap.parse_args()
    task = ExpTask(o.seed)
    for split in ("train", "valid", "test"):  # guard: every world must translate with a trivial rule, or the fitness is dead
        for w in json.load(open(f"{DATA}/{split}.json")):
            if gp.E.answers("failed(V0) <= action(V0)", w["facts"], {"failed": 1}) is None:
                raise SystemExit(f"{split}: a world does not translate ({len(w['facts'].splitlines())} facts) — rebuild the data")
    t0 = time.time()
    s = gp.Search(task, o.seed, o.budget, after_solve=0)
    res = s.run()
    va = json.load(open(f"{DATA}/valid.json")); te = json.load(open(f"{DATA}/test.json"))
    best = None
    for size_, entry in sorted(s.archive.items()):
        prog = gp.render(entry[1])
        m = metrics(prog, va)
        if best is None or m["f1"] > best[1]["f1"]:
            best = (prog, m, size_)
    prog, mv, size_ = best
    mt = metrics(prog, te)
    base = sum(w["failed"] for w in te) / sum(w["n"] for w in te)
    low = wilson_low(mt["tp"], mt["tp"] + mt["fp"])
    out = {"seed": o.seed, "program": prog, "size": size_, "valid": mv, "test": mt, "test_base_rate": round(base, 4),
           "test_precision_wilson_low": round(low, 4), "popper_gate_passed": low > base,
           "lift": round(mt["precision"] / base, 2) if base else None, "evals": s.evals, "seconds": round(time.time() - t0, 1)}
    json.dump(out, open(f"{o.out}/g9_{o.seed}.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
