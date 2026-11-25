"""G8d-0 — information gate (offline): does a representation of the parent predict whether one edit (operator, rule index) improves it?

Input: <dir>/<task>_<arm>_<seed>.edits.jsonl + .worlds.json from gp2_log.py. Only clean records: no crossover, exactly one mutate() call,
not an immigrant, child != parent after canon. Labels offline on the run's final training worlds (train + counterexamples): parent and
child scored like gp2 Search.cases; label 1 = child's score sum > parent's, or equal with smaller size.
Representations (all name-free; predicates only as 'same as literal j' identities, never names — DESIGN_RULES R1):
  N   operator one-hot + parent size (rules, body literals)
  W   N + wiring-blind signature of the program and of the target rule
  S   W + exact 1-hop context features of the target rule (bag of hashed context tokens) and of the program
  F0  W + behaviour of the parent that the search already has for free (per-world TP/FP/FN aggregates)
  SF  S + F0
Model: HistGradientBoostingClassifier, leave-one-task-out. Report pooled out-of-fold AUC per representation and the task-bootstrap 95 %
CI of the margin best-of(S, F0, SF) - max(N, W).
usage: g8d0.py DIR [--max-runs N] [--out result.json]"""
import argparse, glob, json, random, re, sys, zlib
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "g8b"))
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "..", "blind_tasks"))
import gp2 as gp  # noqa: E402
gp.T = __import__("blind_tasks")
E = gp.E

CAP = 300  # amendment 2 (20.11.2026): records per run
OPS = ["add_rule", "add_lit", "add_neg", "add_neq", "del_lit", "del_rule", "flip", "const", "var", "pred", "invent", "recurse"]
_LIT = re.compile(r"^(~?)([a-z]\w*)(?:\((.*)\))?$")


def parse(text):
    prog = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        head, _, body = line.partition(" <= ")
        h = _atom(head.strip())
        lits = []
        for part in [p.strip() for p in body.split(" & ")] if body else []:
            if part.startswith("(") and " != " in part:
                a, b = part[1:-1].split(" != ")
                lits.append(("!=", a.strip(), b.strip()))
            else:
                neg = part.startswith("~")
                lits.append(("-" if neg else "+", _atom(part[1:] if neg else part)))
        prog.append((h, tuple(lits)))
    return tuple(prog)


def _atom(s):
    m = _LIT.match(s)
    p, args = m.group(2), m.group(3)
    return (p, tuple(a.strip() for a in args.split(",")) if args else ())


def size(prog):
    return sum(1 + len(b) for _, b in prog)


def score(prog_text, worlds, golds, answers, cache):
    if prog_text in cache:
        return cache[prog_text]
    s, tp_, fp_, fn_, perfect, zero = 0.0, 0, 0, 0, 0, 0
    for w, g in zip(worlds, golds):
        got = E.answers(prog_text, w, answers)
        if got is None:
            cache[prog_text] = None
            return None
        tp = len(got & g); fp = len(got - g); fn = len(g - got)
        v = 1.0 if got == g else (0.0 if tp == 0 else 2 * tp / (len(got) + len(g))) * 0.99
        s += v; tp_ += tp; fp_ += fp; fn_ += fn; perfect += v == 1.0; zero += v == 0.0
    cache[prog_text] = (s, tp_, fp_, fn_, perfect, zero, len(worlds))
    return cache[prog_text]


def wiring_blind(prog):
    helpers = {h[0] for h, _ in prog if h[0].startswith("inv")}
    pos = sum(1 for _, b in prog for l in b if l[0] == "+"); neg = sum(1 for _, b in prog for l in b if l[0] == "-")
    neq = sum(1 for _, b in prog for l in b if l[0] == "!=")
    rec = sum(1 for h, b in prog for l in b if l[0] != "!=" and l[1][0] == h[0])
    return {"w_rules": len(prog), "w_pos": pos, "w_neg": neg, "w_neq": neq, "w_rec": rec, "w_helpers": len(helpers),
            "w_body_max": max((len(b) for _, b in prog), default=0), "w_head_arity": len(prog[0][0][1]) if prog else 0}


def rule_sig(rule, pre):
    h, b = rule
    return {f"{pre}body": len(b), f"{pre}pos": sum(l[0] == "+" for l in b), f"{pre}neg": sum(l[0] == "-" for l in b),
            f"{pre}neq": sum(l[0] == "!=" for l in b), f"{pre}helper_head": float(h[0].startswith("inv")),
            f"{pre}arity": len(h[1])}


def contexts(rule):
    """name-free 1-hop context tokens of a rule: for each literal its sign, arity, and for each argument slot whether it is a constant,
    shared with the head (which head slot), shared with another literal (sign/arity of that literal), or local; predicate identity only
    as 'same predicate as the head' or 'repeated in the body'."""
    h, b = rule
    toks = []
    preds = Counter(l[1][0] for l in b if l[0] != "!=")
    for l in b:
        if l[0] == "!=":
            for v in (l[1], l[2]):
                toks.append("neq:" + ("head%d" % h[1].index(v) if v in h[1] else "body"))
            continue
        sign, (p, args) = l[0], l[1]
        tag = f"{sign}{len(args)}" + ("H" if p == h[0] else "") + ("R" if preds[p] > 1 else "") + ("I" if p.startswith("inv") else "")
        toks.append("lit:" + tag)
        for k, a in enumerate(args):
            if not gp.is_var(a):
                toks.append(f"{tag}.{k}:const"); continue
            where = [f"head{h[1].index(a)}"] if a in h[1] else []
            for m in b:
                if m is l: continue
                if m[0] == "!=":
                    if a in (m[1], m[2]): where.append("neq")
                elif a in m[1][1]:
                    where.append(f"{m[0]}{len(m[1][1])}")
            toks.append(f"{tag}.{k}:" + ("|".join(sorted(where)) if where else "local"))
    return toks


def hashed(tokens, pre, dim=256):
    out = defaultdict(float)
    for t in tokens:
        out[f"{pre}{zlib.crc32(t.encode()) % dim}"] += 1.0
    return out


def features(rec, parent, cache_p):
    op, i = rec["ops"][0]
    n = {f"op={op}": 1.0, "p_rules": len(parent), "p_size": size(parent)}
    w = dict(n); w.update(wiring_blind(parent))
    rule = parent[i] if parent and i < len(parent) else None
    if rule:
        w.update(rule_sig(rule, "r_"))
    s = dict(w)
    if rule:
        s.update(hashed(contexts(rule), "sr_"))
    s.update(hashed([t for r in parent for t in contexts(r)], "sp_"))
    f = dict(w)
    if cache_p:
        sc, tp, fp, fn, perfect, zero, nw = cache_p
        f.update({"f_score": sc / nw, "f_fp": fp, "f_fn": fn, "f_fp_share": fp / (fp + fn) if fp + fn else 0.0,
                  "f_perfect": perfect / nw, "f_zero": zero / nw, "f_tp": tp})
    sf = dict(s); sf.update({k: v for k, v in f.items() if k.startswith("f_")})
    return {"N": n, "W": w, "S": s, "F0": f, "SF": sf}


def load(d, max_runs, seed=0):
    rows = []
    files = sorted(glob.glob(f"{d}/*.edits.jsonl"))
    random.Random(seed).shuffle(files)
    for ef in files[:max_runs] if max_runs else files:
        stem = ef[:-len(".edits.jsonl")]
        name = stem.rsplit("/", 1)[1]
        task_name, arm, s = name.rsplit("_", 2)
        try:
            wj = json.load(open(stem + ".worlds.json"))
        except FileNotFoundError:
            continue
        task = gp.Task(task_name, int(s))
        worlds = wj["train"]
        golds = [E.answers(task.ref, w, task.answers) for w in worlds]
        cache = {}
        clean = []
        for line in open(ef):
            r = json.loads(line)
            if r["x"] is not None or len(r["ops"]) != 1 or r["imm"] or not r["c"] or r["c"] == r["p"]:
                continue
            clean.append(r)
        if CAP and len(clean) > CAP:  # amendment 2: at most CAP records per run, seeded by the run (median run has 73)
            clean = random.Random(f"cap:{name}").sample(clean, CAP)
        for r in clean:
            sp = score(r["p"], worlds, golds, task.answers, cache)
            sc = score(r["c"], worlds, golds, task.answers, cache)
            if sp is None or sc is None:
                continue
            parent, child = parse(r["p"]), parse(r["c"])
            y = int(sc[0] > sp[0] + 1e-9 or (abs(sc[0] - sp[0]) <= 1e-9 and size(child) < size(parent)))
            rows.append({"task": task_name, "arm": arm, "seed": int(s), "op": r["ops"][0][0], "y": y, "parent": f"{name}|{r['p']}",
                         "rec_ops": r["ops"], "p_text": r["p"], "sp": sp})  # amendment 1: features computed per representation (memory)
    return rows


def oof(rows, rep):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.feature_extraction import DictVectorizer
    tasks = sorted({r["task"] for r in rows})
    pred = np.zeros(len(rows))
    vec = DictVectorizer(sparse=False)
    X = vec.fit_transform(features({"ops": r["rec_ops"]}, parse(r["p_text"]), r["sp"])[rep] for r in rows)
    y = np.array([r["y"] for r in rows])
    tk = np.array([r["task"] for r in rows])
    for t in tasks:
        tr, te = tk != t, tk == t
        if len(set(y[tr])) < 2:
            continue
        clf = HistGradientBoostingClassifier(max_iter=200, random_state=0).fit(X[tr], y[tr])
        pred[te] = clf.predict_proba(X[te])[:, 1]
    return pred


def grouped_auc(y, p, groups):
    """AUC within parent: over all (positive, negative) pairs of edits of the SAME parent — what a proposer choosing among the edits of
    one parent can use. Parent-level headroom (a bad parent is easy to improve) cancels out. Returns (auc, pairs, parents)."""
    by = defaultdict(list)
    for yi, pi, gi in zip(y, p, groups):
        by[gi].append((yi, pi))
    win = pairs = 0.0; parents = 0
    for g in by.values():
        npos = sum(1 for yi, _ in g if yi == 1); nneg = len(g) - npos
        if not npos or not nneg:
            continue
        parents += 1
        # amendment 2: Mann-Whitney U by midranks — the same value as counting every (pos, neg) pair, in O(n log n)
        order = sorted(range(len(g)), key=lambda k: g[k][1])
        ranks = [0.0] * len(g); i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and g[order[j + 1]][1] == g[order[i]][1]:
                j += 1
            for k in range(i, j + 1):
                ranks[order[k]] = (i + j) / 2 + 1
            i = j + 1
        rpos = sum(ranks[k] for k in range(len(g)) if g[k][0] == 1)
        win += rpos - npos * (npos + 1) / 2
        pairs += npos * nneg
    return (win / pairs if pairs else None), int(pairs), parents


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if len(set(y)) == 2 else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--max-runs", type=int, default=0); ap.add_argument("--out")
    o = ap.parse_args()
    rows = load(o.dir, o.max_runs)
    y = np.array([r["y"] for r in rows]); tk = np.array([r["task"] for r in rows])
    res = {"records": len(rows), "positives": int(y.sum()), "tasks": len(set(tk)),
           "positives_by_op": {op: [int(sum(r["y"] for r in rows if r["op"] == op)), sum(1 for r in rows if r["op"] == op)] for op in OPS}}
    preds = {rep: oof(rows, rep) for rep in ["N", "W", "S", "F0", "SF"]}
    res["auc_loto"] = {rep: round(auc(y, p), 4) for rep, p in preds.items()}
    gr = np.array([r["parent"] for r in rows])
    res["auc_within_parent"] = {rep: grouped_auc(y, p, gr) for rep, p in preds.items()}
    tasks = sorted(set(tk)); rnd = np.random.default_rng(0); margins = []; gmargins = []
    for _ in range(1000):
        pick = rnd.choice(tasks, len(tasks), replace=True)
        parts = [np.where(tk == t)[0] for t in pick]
        idx = np.concatenate(parts)
        gid = [f"{j}#{gr[k]}" for j, part in enumerate(parts) for k in part]  # a task drawn twice is two independent copies
        if len(set(y[idx])) < 2: continue
        a = {rep: auc(y[idx], p[idx]) for rep, p in preds.items()}
        margins.append(max(a["S"], a["F0"], a["SF"]) - max(a["N"], a["W"]))
        ga = {rep: grouped_auc(y[idx], p[idx], gid)[0] for rep, p in preds.items()}
        if None not in ga.values():
            gmargins.append(max(ga["S"], ga["F0"], ga["SF"]) - max(ga["N"], ga["W"]))
    res["margin_best_vs_baseline"] = {"point": round(max(res["auc_loto"][k] for k in ("S", "F0", "SF")) - max(res["auc_loto"]["N"], res["auc_loto"]["W"]), 4),
                                      "ci95": [round(float(np.percentile(margins, 2.5)), 4), round(float(np.percentile(margins, 97.5)), 4)]}
    wp = res["auc_within_parent"]
    gpoint = max(wp[k][0] for k in ("S", "F0", "SF")) - max(wp["N"][0], wp["W"][0])
    res["margin_within_parent"] = {"point": round(gpoint, 4), "ci95": [round(float(np.percentile(gmargins, 2.5)), 4), round(float(np.percentile(gmargins, 97.5)), 4)] if gmargins else None}
    # self-review 2: the gate is the WITHIN-PARENT margin (the decision a proposer makes); the pooled AUC mixes in parent headroom
    m = res["margin_within_parent"]
    res["gate"] = "PASS" if m["ci95"] and m["point"] >= 0.05 and m["ci95"][0] > 0 else "FAIL"
    print(json.dumps(res, indent=1))
    if o.out:
        json.dump(res, open(o.out, "w"), indent=1)
