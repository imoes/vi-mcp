"""G9b: the G9 question with the selection fixed (prereg_G9b.md). The SAME rule chooses for every method:
  MDL on the pooled validation windows = size + false negatives + false positives (MaxSynth's cost, AAAI 2024),
  candidates always include 'no rule' (size 0, predicts nothing). Ties: the smaller program.
Methods: (1) GP = gp2 unchanged on the train worlds, candidates = its archive (best fit per size); (2) single literal rules (size 2);
(3) decision trees depth 1-6 (class_weight balanced), size = sum over positive leaves of (1 + path length). Each method's chosen
candidate is read ONCE on the test period. Abstaining ('no rule' chosen) is reported as such: no law claimed, gate not passed.
usage: g9b.py gp SEED OUT [--budget N] | g9b.py baselines OUT        (G9_DATA=data_b_cc)"""
import json, os, re, sys, time
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import g9_search as GS  # noqa: E402  (ExpTask, metrics, wilson_low; reads G9_DATA)

DATA = GS.DATA
VALID_FILES = sorted(f for f in os.listdir(DATA) if f.startswith("valid_"))


def load(name):
    return json.load(open(f"{DATA}/{name}"))


def mdl(m, size_):
    return size_ + m["fn"] + m["fp"]


def gate(mt, base):
    low = GS.wilson_low(mt["tp"], mt["tp"] + mt["fp"])
    return {"test_precision_wilson_low": round(low, 4), "popper_gate_passed": low > base,
            "lift": round(mt["precision"] / base, 2) if base and mt["tp"] + mt["fp"] else None}


def nothing_metrics(worlds):
    fn = sum(w["failed"] for w in worlds)
    return {"tp": 0, "fp": 0, "fn": fn, "n": sum(w["n"] for w in worlds), "precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_base(te):
    return sum(w["failed"] for w in te) / sum(w["n"] for w in te)


def run_gp(seed, out, budget):
    gp = GS.gp
    task = GS.ExpTask(seed)
    t0 = time.time()
    s = gp.Search(task, seed, budget, after_solve=0)
    s.run()
    va = load("valid.json"); te = load("test.json")
    per_window = {f: load(f) for f in VALID_FILES}
    cands = [("no rule", 0, nothing_metrics(va))]
    for size_, entry in sorted(s.archive.items()):
        prog = gp.render(entry[1])
        cands.append((prog, size_, GS.metrics(prog, va)))
    ranked = sorted(cands, key=lambda c: (mdl(c[2], c[1]), c[1]))
    prog, size_, mv = ranked[0]
    base = test_base(te)
    res = {"method": "gp", "seed": seed, "chosen": prog, "size": size_, "valid_mdl": mdl(mv, size_), "valid": mv,
           "no_rule_mdl": mdl(nothing_metrics(va), 0), "abstained": prog == "no rule",
           "windows": {f: (nothing_metrics(per_window[f]) if prog == "no rule" else GS.metrics(prog, per_window[f])) for f in VALID_FILES},
           "candidates": [{"size": c[1], "valid_mdl": mdl(c[2], c[1]), "valid_f1": c[2]["f1"]} for c in cands],
           "test_base_rate": round(base, 4), "evals": s.evals, "seconds": round(time.time() - t0, 1)}
    mt = nothing_metrics(te) if res["abstained"] else GS.metrics(prog, te)
    res["test"] = mt
    res.update(gate(mt, base) if not res["abstained"] else {"popper_gate_passed": False, "lift": None})
    json.dump(res, open(f"{out}/g9b_gp_{seed}.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("seed", "chosen", "size", "valid_mdl", "no_rule_mdl", "abstained", "popper_gate_passed")}))


def rows(name):
    out = []
    for w in load(name):
        feats, gold = defaultdict(set), set(w["gold"])
        for line in w["facts"].splitlines():
            m = re.match(r"(\w+)\((\w+)(?:, (\w+))?\)", line)
            p, e, v = m.group(1), m.group(2), m.group(3)
            feats[e].add(f"{p}={v}" if v else p)
            if p in ("host", "topic"):
                feats[e].add(f"{p}=*")
        for e, fs in feats.items():
            out.append((fs, f"failed({e})" in gold))
    return out


def counts(pred, ys):
    tp = sum(p and y for p, y in zip(pred, ys)); fp = sum(p and not y for p, y in zip(pred, ys))
    fn = sum((not p) and y for p, y in zip(pred, ys))
    prec = tp / (tp + fp) if tp + fp else 0.0; rec = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "n": len(ys), "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}


def tree_size(m):
    t = m.tree_
    total = 0

    def walk(node, depth):
        nonlocal total
        if t.children_left[node] == -1:
            if t.value[node][0].argmax() == 1:
                total += 1 + depth
            return
        walk(t.children_left[node], depth + 1); walk(t.children_right[node], depth + 1)
    walk(0, 0)
    return total


def run_baselines(out):
    from sklearn.tree import DecisionTreeClassifier
    tr, va, te = rows("train.json"), rows("valid.json"), rows("test.json")
    yv, yt = [y for _f, y in va], [y for _f, y in te]
    base = sum(yt) / len(yt)
    nothing_v = counts([False] * len(yv), yv)
    res = {"test_base_rate": round(base, 4), "no_rule_mdl": mdl(nothing_v, 0)}
    vocab = sorted({f for fs, _y in tr for f in fs})
    # single literal rules: chosen ONLY by validation MDL (the train period is not used beyond the vocabulary)
    cands = [("no rule", 0, nothing_v, None)] + [(f, 2, counts([f in fs for fs, _y in va], yv), f) for f in vocab]
    chosen = min(cands, key=lambda c: (mdl(c[2], c[1]), c[1]))
    mt = counts([False] * len(yt), yt) if chosen[3] is None else counts([chosen[3] in fs for fs, _y in te], yt)
    res["single_rule"] = {"chosen": chosen[0], "size": chosen[1], "valid_mdl": mdl(chosen[2], chosen[1]), "valid": chosen[2],
                          "abstained": chosen[3] is None, "test": mt,
                          **(gate(mt, base) if chosen[3] is not None else {"popper_gate_passed": False, "lift": None})}

    def X(rs):
        return [[1 if f in fs else 0 for f in vocab] for fs, _y in rs]
    tcands = [("no rule", 0, nothing_v, None)]
    for depth in range(1, 7):
        m = DecisionTreeClassifier(max_depth=depth, class_weight="balanced", random_state=0).fit(X(tr), [y for _f, y in tr])
        tcands.append((f"tree depth {depth}", tree_size(m), counts(list(m.predict(X(va))), yv), m))
    chosen = min(tcands, key=lambda c: (mdl(c[2], c[1]), c[1]))
    mt = counts([False] * len(yt), yt) if chosen[3] is None else counts(list(chosen[3].predict(X(te))), yt)
    res["tree"] = {"chosen": chosen[0], "size": chosen[1], "valid_mdl": mdl(chosen[2], chosen[1]), "valid": chosen[2],
                   "abstained": chosen[3] is None, "test": mt,
                   "candidates": [{"name": c[0], "size": c[1], "valid_mdl": mdl(c[2], c[1])} for c in tcands],
                   **(gate(mt, base) if chosen[3] is not None else {"popper_gate_passed": False, "lift": None})}
    json.dump(res, open(f"{out}/g9b_baselines.json", "w"), indent=1, default=int)
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: v[kk] for kk in ("chosen", "size", "valid_mdl", "abstained",
                      "popper_gate_passed")}) for k, v in res.items()}, indent=1, default=int))


if __name__ == "__main__":
    if sys.argv[1] == "gp":
        import argparse
        ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("seed", type=int); ap.add_argument("out")
        ap.add_argument("--budget", type=int, default=4000); o = ap.parse_args()
        os.makedirs(o.out, exist_ok=True)
        run_gp(o.seed, o.out, o.budget)
    else:
        os.makedirs(sys.argv[2], exist_ok=True)
        run_baselines(sys.argv[2])
