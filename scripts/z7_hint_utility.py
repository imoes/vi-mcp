"""Z7 offline test: hint utility from hint-level labels (docs/PREREG_Z7_HINT_UTILITY.md).

Usage: python scripts/z7_hint_utility.py DB.sqlite OUT.json

Reads a COPY of a VI database read-only (file:…?mode=ro) and never imports vi_mcp (opening a database through vi_mcp may migrate it).
The feature definitions mirror vi_mcp.learning.action_features / hint_features (without content groups) and bandit.py; deviations are
listed in the pre-registration.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

TRIGGER_KINDS = ("tool:", "skill:", "host:", "topic:", "error:")  # learning.TRIGGER_KINDS
NEW_DAYS = 7  # metrics.NEW_DAYS
IPS_CLIP = 10.0  # learning.IPS_CLIP
BASE_MIN = 10  # bandit.BASE_MIN
SEED = 22112026
N_BOOT = 2000
KIND_EN = {"erkenntnis": "insight", "regel": "rule", "suche": "search", "bild": "image", "seite": "page"}


def tool_of(triggers):
    return next((t for t in triggers if t.startswith("tool:")), "tool:?")


def action_features(triggers, ts):
    m = {t: 1.0 for t in triggers if t.startswith(TRIGGER_KINDS)}
    m[f"hour:{ts[11:13]}"] = 1.0
    return m


def hint_features(h, ts, born):
    prefix = h.split(":")[0]
    m = {f"hint:{h}": 1.0, f"hint_kind:{KIND_EN.get(prefix, prefix)}": 1.0}
    b = born.get(h)
    if b and (datetime.fromisoformat(ts) - datetime.fromisoformat(b)).total_seconds() <= NEW_DAYS * 86400:
        m["age:new"] = 1.0
    return m


def pair_features(e, h, born):
    f = action_features(e["triggers"], e["ts"])
    f[f"hint_n:{min(4, len(e['shown']))}"] = 1.0
    f.update(hint_features(h, e["ts"], born))
    return f


def ips(p):
    return min(IPS_CLIP, 1.0 / p) if isinstance(p, (int, float)) and 0.0 < p < 1.0 else 1.0


def hint_label(d, h):
    """Precedence: the agent's own feedback, then used, then the judge (pre-registration)."""
    fb = d.get("feedback")
    if isinstance(fb, dict) and isinstance(fb.get(h), (int, float)) and fb[h] != 0:
        return (1 if fb[h] > 0 else 0), "feedback"
    if isinstance(d.get("used"), list) and h in d["used"]:
        return 1, "used"
    j = (d.get("judge") or {}).get("hints") if isinstance(d.get("judge"), dict) else None
    if isinstance(j, dict) and isinstance(j.get(h), str):
        return (1 if j[h] == "used" else 0), "judge"
    return None, None


def load(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    okyes = {r[0] for r in db.execute("SELECT object_id FROM tag WHERE tag = 'ok:yes'")}
    okno = {r[0] for r in db.execute("SELECT object_id FROM tag WHERE tag = 'ok:no'")}
    exps = []
    for oid, ts, data, inst in db.execute("SELECT id, ts, data, instance FROM object WHERE kind = 'experience' AND mode = 'active' ORDER BY ts"):
        d = json.loads(data)
        b = d.get("before") or {}
        if not b or b.get("from_memory"):
            continue
        exps.append({"id": oid, "ts": ts, "inst": inst, "d": d, "triggers": b.get("triggers") or [], "shown": b.get("shown") or [],
                     "offer": b.get("offer") or {}, "cand": b.get("candidates") or [],
                     "ok": True if oid in okyes else False if oid in okno else None})
    ids = {h for e in exps for h in e["shown"] + e["cand"]}
    born = {}
    idl = list(ids)
    for i in range(0, len(idl), 500):
        chunk = idl[i:i + 500]
        for oid, ts in db.execute(f"SELECT id, ts FROM object WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            born[oid] = ts
    return exps, born


def labelled_pairs(exps):
    out = []
    for e in exps:
        for pos, h in enumerate(e["shown"]):
            y, src = hint_label(e["d"], h)
            if y is not None:
                out.append({"e": e, "h": h, "pos": pos, "y": y, "src": src, "p": e["offer"].get(h)})
    return out


def bandit_scores(train_exps):
    """bandit.py v2 replica: advantage over the instance × tool (else tool, else all) success rate without hints."""
    base_it, base_t, base_all = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), [0, 0]
    for e in train_exps:
        if e["ok"] is None or e["shown"]:
            continue
        t = tool_of(e["triggers"])
        for c in (base_it[(e["inst"], t)], base_t[t], base_all):
            c[0] += 1
            c[1] += e["ok"]

    def rate(inst, t):
        for c in (base_it.get((inst, t)), base_t.get(t)):
            if c and c[0] >= BASE_MIN:
                return c[1] / c[0]
        return base_all[1] / max(1, base_all[0])

    ab = defaultdict(lambda: [0.0, 0.0])
    for e in train_exps:
        if e["ok"] is None or not e["shown"]:
            continue
        p = rate(e["inst"], tool_of(e["triggers"]))
        for h in e["shown"]:
            if e["ok"]:
                ab[h][0] += 1 - p
            else:
                ab[h][1] += p
    return {h: (1 + a) / (2 + a + b) for h, (a, b) in ab.items()}


def beta_fit(pairs):
    c = defaultdict(lambda: [0, 0])
    for q in pairs:
        c[q["h"]][0] += q["y"]
        c[q["h"]][1] += 1
    return c, sum(q["y"] for q in pairs) / len(pairs)


def beta_score(counts, m, s, h):
    k, n = counts.get(h, (0, 0))
    return (m * s + k) / (s + n)


def fit_lr(X, y, w, C):
    return LogisticRegression(C=C, max_iter=2000).fit(X, y, sample_weight=w)


def safe_auc(y, s):
    return roc_auc_score(y, s) if len(set(y)) == 2 else float("nan")


def main(db_path, out_path):
    exps, born = load(db_path)
    pairs = labelled_pairs(exps)
    pairs.sort(key=lambda q: q["e"]["ts"])
    cutoff = pairs[int(0.7 * len(pairs))]["e"]["ts"]
    tr = [q for q in pairs if q["e"]["ts"] < cutoff]
    te = [q for q in pairs if q["e"]["ts"] >= cutoff]
    icut = tr[int(0.75 * len(tr))]["e"]["ts"]
    itr = [q for q in tr if q["e"]["ts"] < icut]
    iva = [q for q in tr if q["e"]["ts"] >= icut]
    rep = {"n_pairs": len(pairs), "cutoff": cutoff, "inner_cutoff": icut,
           "parts": {k: {"n": len(v), "pos": sum(q["y"] for q in v), "experiences": len({q["e"]["id"] for q in v}),
                         "hints": len({q["h"] for q in v}), "sources": Counter(q["src"] for q in v),
                         "with_p_lt_1": sum(1 for q in v if isinstance(q["p"], (int, float)) and 0 < q["p"] < 1)}
                     for k, v in (("train", tr), ("inner_train", itr), ("inner_val", iva), ("holdout", te))}}

    # --- B: Beta posterior, s on inner validation by log loss
    cnt_i, m_i = beta_fit(itr)
    ll = {s: log_loss([q["y"] for q in iva], [beta_score(cnt_i, m_i, s, q["h"]) for q in iva], labels=[0, 1]) for s in (1, 2, 5, 10)}
    s_best = min(ll, key=ll.get)
    b_inner_auc = safe_auc([q["y"] for q in iva], [beta_score(cnt_i, m_i, s_best, q["h"]) for q in iva])
    cnt, m = beta_fit(tr)
    score = defaultdict(dict)
    for q in te:
        score["B"][id(q)] = beta_score(cnt, m, s_best, q["h"])
    rep["B"] = {"s_logloss_inner": ll, "s": s_best, "prior_mean": m, "inner_val_auc": b_inner_auc}

    # --- C0 / C1: hint-label logistic regression
    def feats(qs):
        return [pair_features(q["e"], q["h"], born) for q in qs]

    for name, weighted in (("C0", False), ("C1", True)):
        def w(qs):
            return np.array([ips(q["p"]) if weighted else 1.0 for q in qs])
        dv = DictVectorizer().fit(feats(itr))
        Xi, Xv = dv.transform(feats(itr)), dv.transform(feats(iva))
        yi, yv = np.array([q["y"] for q in itr]), np.array([q["y"] for q in iva])
        lls, aucs = {}, {}
        for C in (0.03, 0.1, 0.3, 1, 3):
            mdl = fit_lr(Xi, yi, w(itr), C)
            pv = mdl.predict_proba(Xv)[:, 1]
            lls[C], aucs[C] = log_loss(yv, pv, labels=[0, 1]), safe_auc(yv, pv)
        C_best = min(lls, key=lls.get)
        dv = DictVectorizer().fit(feats(tr))
        mdl = fit_lr(dv.transform(feats(tr)), np.array([q["y"] for q in tr]), w(tr), C_best)
        pt = mdl.predict_proba(dv.transform(feats(te)))[:, 1]
        for q, p in zip(te, pt):
            score[name][id(q)] = p
        rep[name] = {"C_logloss_inner": lls, "C_auc_inner": aucs, "C": C_best, "inner_val_auc": aucs[C_best]}
        rep[name]["_model"] = (dv, mdl)

    # --- A1 live order
    for q in te:
        score["A1"][id(q)] = -q["pos"]
    # --- A2 bandit replica (training-period experiences only)
    train_exps = [e for e in exps if e["ts"] < cutoff]
    bs = bandit_scores(train_exps)
    for q in te:
        score["A2"][id(q)] = bs.get(q["h"], 0.5)
    rep["A2"] = {"hints_with_counters": len(bs), "holdout_pairs_covered": sum(1 for q in te if q["h"] in bs)}
    # --- A3 outcome-router replica
    otr = [(e, h) for e in train_exps if e["ok"] is not None for h in e["shown"]]
    dv3 = DictVectorizer().fit([pair_features(e, h, born) for e, h in otr])
    m3 = LogisticRegression(class_weight="balanced", C=0.3, max_iter=2000).fit(
        dv3.transform([pair_features(e, h, born) for e, h in otr]), np.array([int(e["ok"]) for e, _ in otr]),
        sample_weight=np.array([ips(e["offer"].get(h)) for e, h in otr]))
    p3 = m3.predict_proba(dv3.transform([pair_features(q["e"], q["h"], born) for q in te]))[:, 1]
    for q, p in zip(te, p3):
        score["A3"][id(q)] = p
    rep["A3"] = {"outcome_pairs": len(otr), "ok_rate": float(np.mean([e["ok"] for e, _ in otr]))}

    # --- model choice (inner validation AUC; ties → simpler)
    order = ["B", "C0", "C1"]
    inner = {k: rep[k]["inner_val_auc"] for k in order}
    chosen = max(order, key=lambda k: (round(inner[k], 4), -order.index(k)))
    rep["chosen"] = chosen

    # --- holdout metrics
    y = np.array([q["y"] for q in te])
    models = ["A1", "A2", "A3", "B", "C0", "C1"]
    S = {k: np.array([score[k][id(q)] for q in te]) for k in models}
    rep["holdout_auc"] = {k: safe_auc(y, S[k]) for k in models}
    # cluster bootstrap over experiences
    groups = defaultdict(list)
    for i, q in enumerate(te):
        groups[q["e"]["id"]].append(i)
    keys = list(groups)
    rng = random.Random(SEED)
    boot = defaultdict(list)
    for _ in range(N_BOOT):
        idx = [i for k in (rng.choice(keys) for _ in keys) for i in groups[k]]
        yb = y[idx]
        if len(set(yb)) < 2:
            continue
        a = {k: roc_auc_score(yb, S[k][idx]) for k in models}
        for k in models:
            boot[k].append(a[k])
            boot[f"{k}-A1"].append(a[k] - a["A1"])
    rep["holdout_ci95"] = {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in boot.items()}
    rep["n_boot_valid"] = len(boot["A1"])
    # within-experience pairwise accuracy
    pw = {}
    for k in models:
        hit = tot = 0.0
        for ids in groups.values():
            P = [i for i in ids if y[i] == 1]
            N = [i for i in ids if y[i] == 0]
            for i in P:
                for j in N:
                    tot += 1
                    hit += 1.0 if S[k][i] > S[k][j] else 0.5 if S[k][i] == S[k][j] else 0.0
        pw[k] = {"pairs": tot, "accuracy": hit / tot if tot else float("nan")}
    rep["within_experience"] = pw
    rep["mixed_label_experiences"] = sum(1 for ids in groups.values() if len({y[i] for i in ids}) == 2)
    # Recall@4 of positives among logged candidates (lower-bound proxy), B and C
    rec = {}
    by_exp = {q["e"]["id"]: q["e"] for q in te}
    for k in ("B", "C0", "C1"):
        vals = []
        for eid, ids in groups.items():
            positives = {te[i]["h"] for i in ids if y[i] == 1}
            if not positives:
                continue
            e = by_exp[eid]
            cand = list(dict.fromkeys(e["cand"] + e["shown"]))
            if k == "B":
                sc = [beta_score(cnt, m, s_best, h) for h in cand]
            else:
                dv, mdl = rep[k]["_model"]
                sc = list(mdl.predict_proba(dv.transform([pair_features(e, h, born) for h in cand]))[:, 1])
            top = {h for _, h in sorted(zip(sc, cand), key=lambda t: -t[0])[:4]}
            vals.append(len(positives & top) / len(positives))
        rec[k] = {"experiences": len(vals), "recall_at_4": float(np.mean(vals)) if vals else float("nan"),
                  "mean_candidates": float(np.mean([len(by_exp[e]["cand"]) for e in groups]))}
    rep["recall_at_4_candidates"] = rec
    for k in ("C0", "C1"):
        rep[k].pop("_model")
    # decisions
    ch = rep["chosen"]
    lo = rep["holdout_ci95"][f"{ch}-A1"][0]
    rep["H1"] = {"chosen": ch, "diff_vs_A1": rep["holdout_auc"][ch] - rep["holdout_auc"]["A1"], "ci95_low": lo, "holds": lo > 0}
    rep["H2"] = {"auc": rep["holdout_auc"][ch], "ci95": rep["holdout_ci95"][ch], "holds": rep["holdout_auc"][ch] >= 0.65}
    with open(out_path, "w") as f:
        json.dump(rep, f, indent=1, default=lambda o: dict(o) if isinstance(o, Counter) else str(o))
    print(json.dumps({k: rep[k] for k in ("n_pairs", "cutoff", "parts", "chosen", "holdout_auc", "holdout_ci95", "within_experience",
                                          "recall_at_4_candidates", "H1", "H2", "B", "C0", "C1", "A2", "A3")}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
