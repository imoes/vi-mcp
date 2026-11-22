"""Z7b offline test: which shown hint does the agent use? (docs/PREREG_Z7B_WITHIN_ACTION.md)

Usage: python scripts/z7b_within_action.py DB.sqlite OUT.json
Reads a COPY of a VI database read-only; never imports vi_mcp. Reuses the loaders and replicas of z7_hint_utility.py.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

sys.path.insert(0, str(Path(__file__).resolve().parent))
import z7_hint_utility as z  # noqa: E402

SEED, N_BOOT = 22112026, 2000


def actions(exps):
    out = []
    for e in exps:
        u = e["d"].get("used")
        shown = [h for h in e["shown"] if not h.startswith(("answer:", "antwort:"))]
        if not isinstance(u, list) or len(shown) < 2:
            continue
        y = [1 if h in u else 0 for h in shown]
        if 0 < sum(y) < len(y):
            out.append({"e": e, "hints": shown, "y": y})
    return out


def hfeat(e, h, born):
    f = z.hint_features(h, e["ts"], born)
    kind = next(k for k in f if k.startswith("hint_kind:"))
    f[f"{kind}|{z.tool_of(e['triggers'])}"] = 1.0
    return f


def pairs_of(a):
    return [(i, j) for i, yi in enumerate(a["y"]) if yi for j, yj in enumerate(a["y"]) if not yj]


def pairwise_acc(acts, scorer):
    hit = tot = 0.0
    per = []
    for a in acts:
        s = scorer(a)
        h = t = 0.0
        for i, j in pairs_of(a):
            t += 1
            h += 1.0 if s[i] > s[j] else 0.5 if s[i] == s[j] else 0.0
        per.append((h, t))
        hit, tot = hit + h, tot + t
    return hit / tot, per


def top1(acts, scorer):
    hits, expect = [], []
    for a in acts:
        s = scorer(a)
        best = max(range(len(s)), key=lambda i: (s[i], -i))  # ties → live order
        hits.append(a["y"][best])
        expect.append(sum(a["y"]) / len(a["y"]))
    return float(np.mean(hits)), float(np.mean(expect))


def fit_beta(acts):
    c = defaultdict(lambda: [0, 0])
    for a in acts:
        for h, y in zip(a["hints"], a["y"]):
            c[h][0] += y
            c[h][1] += 1
    m = sum(v[0] for v in c.values()) / sum(v[1] for v in c.values())
    return c, m


def beta_scorer(c, m, s):
    return lambda a: [(m * s + c[h][0]) / (s + c[h][1]) if h in c else m for h in a["hints"]]


def fit_pairwise(acts, born, C):
    rows, ys = [], []
    for a in acts:
        F = [hfeat(a["e"], h, born) for h in a["hints"]]
        for i, j in pairs_of(a):
            d = defaultdict(float)
            for k, v in F[i].items():
                d[k] += v
            for k, v in F[j].items():
                d[k] -= v
            rows += [dict(d), {k: -v for k, v in d.items()}]
            ys += [1, 0]
    dv = DictVectorizer().fit(rows)
    mdl = LogisticRegression(C=C, fit_intercept=False, max_iter=5000).fit(dv.transform(rows), ys)
    w = dict(zip(dv.get_feature_names_out(), mdl.coef_[0]))
    return lambda a: [sum(w.get(k, 0.0) * v for k, v in hfeat(a["e"], h, born).items()) for h in a["hints"]]


def boot(acts, scorers, rng):
    res = defaultdict(list)
    per = {k: pairwise_acc(acts, f)[1] for k, f in scorers.items()}
    n = len(acts)
    for _ in range(N_BOOT):
        idx = [rng.randrange(n) for _ in range(n)]
        acc = {}
        for k in scorers:
            h = sum(per[k][i][0] for i in idx)
            t = sum(per[k][i][1] for i in idx)
            acc[k] = h / t
        for k in scorers:
            res[k].append(acc[k])
            res[f"{k}-A1"].append(acc[k] - acc["A1"])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in res.items()}


def main(db_path, out_path):
    exps, born = z.load(db_path)
    acts = sorted(actions(exps), key=lambda a: a["e"]["ts"])
    cut = int(0.7 * len(acts))
    tr, te = acts[:cut], acts[cut:]
    icut = int(0.75 * len(tr))
    itr, iva = tr[:icut], tr[icut:]
    rep = {"actions": len(acts), "cutoff": te[0]["e"]["ts"],
           "parts": {k: {"actions": len(v), "pos": sum(sum(a["y"]) for a in v), "neg": sum(len(a["y"]) - sum(a["y"]) for a in v),
                         "pairs": sum(len(pairs_of(a)) for a in v), "instances": Counter(a["e"]["inst"] for a in v)}
                     for k, v in (("train", tr), ("inner_train", itr), ("inner_val", iva), ("holdout", te))}}
    # B'
    c_i, m_i = fit_beta(itr)
    yv = [y for a in iva for y in a["y"]]
    ll = {s: log_loss(yv, [p for a in iva for p in beta_scorer(c_i, m_i, s)(a)], labels=[0, 1]) for s in (1, 2, 5, 10)}
    s_best = min(ll, key=ll.get)
    b_inner = pairwise_acc(iva, beta_scorer(c_i, m_i, s_best))[0]
    c_t, m_t = fit_beta(tr)
    rep["B"] = {"s_logloss_inner": ll, "s": s_best, "inner_val_pairwise": b_inner, "prior_mean": m_t}
    # C'
    accs = {C: pairwise_acc(iva, fit_pairwise(itr, born, C))[0] for C in (0.03, 0.1, 0.3, 1, 3)}
    C_best = max(accs, key=lambda C: (round(accs[C], 4), -C))
    rep["C"] = {"C_pairwise_inner": accs, "C": C_best, "inner_val_pairwise": accs[C_best]}
    chosen = "B" if round(b_inner, 4) >= round(accs[C_best], 4) else "C"
    rep["chosen"] = chosen
    # holdout
    bs = z.bandit_scores([e for e in exps if e["ts"] < rep["cutoff"]])
    scorers = {
        "R0": lambda a: [0.0] * len(a["hints"]),
        "A1": lambda a: [-i for i in range(len(a["hints"]))],
        "A2": lambda a: [bs.get(h, 0.5) for h in a["hints"]],
        "B": beta_scorer(c_t, m_t, s_best),
        "C": fit_pairwise(tr, born, C_best),
    }
    rep["holdout_pairwise"] = {k: pairwise_acc(te, f)[0] for k, f in scorers.items()}
    rep["holdout_ci95"] = boot(te, scorers, random.Random(SEED))
    rep["holdout_top1"] = {k: top1(te, f) for k, f in scorers.items()}
    seen = {h for a in tr for h in a["hints"]}
    tot = sum(len(pairs_of(a)) for a in te)
    cov = sum(1 for a in te for i, j in pairs_of(a) if a["hints"][i] in seen and a["hints"][j] in seen)
    rep["coverage_pairs_both_seen"] = cov / tot if tot else float("nan")
    rep["position_of_used"] = Counter(i for a in acts for i, y in enumerate(a["y"]) if y)
    rep["position_shown"] = Counter(i for a in acts for i in range(len(a["y"])))
    ch = rep["chosen"]
    rep["H1"] = {"chosen": ch, "acc": rep["holdout_pairwise"][ch], "ci95": rep["holdout_ci95"][ch], "holds": rep["holdout_ci95"][ch][0] > 0.5}
    rep["H2"] = {"diff_vs_A1": rep["holdout_pairwise"][ch] - rep["holdout_pairwise"]["A1"], "ci95": rep["holdout_ci95"][f"{ch}-A1"],
                 "holds": rep["holdout_ci95"][f"{ch}-A1"][0] > 0}
    rep["H4"] = {"acc": rep["holdout_pairwise"][ch], "at_least_0.65": rep["holdout_pairwise"][ch] >= 0.65}
    with open(out_path, "w") as f:
        json.dump(rep, f, indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
