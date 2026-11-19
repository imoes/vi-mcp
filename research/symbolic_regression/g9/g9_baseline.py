"""G9 baselines on the same features and split: (1) every single-literal rule (the best on validation), (2) a decision tree
(scikit-learn, depth 1-6 chosen on validation, class_weight balanced) — both read once on the test period, same metrics as g9_search.
usage: g9_baseline.py"""
import json, os, re, sys
from collections import defaultdict

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import g9_search as GS  # noqa: E402


def rows(split):
    out = []
    for w in json.load(open(f"{GS.DATA}/{split}.json")):
        feats, gold = defaultdict(set), set(w["gold"])
        for line in w["facts"].splitlines():
            m = re.match(r"(\w+)\((\w+)(?:, (\w+))?\)", line)
            p, e, v = m.group(1), m.group(2), m.group(3)
            feats[e].add(f"{p}={v}" if v else p)
            if p in ("host", "topic"):
                feats[e].add(f"{p}=*")  # "has any host / topic"
        for e, fs in feats.items():
            out.append((fs, f"failed({e})" in gold))
    return out


def scores(pred, ys):
    tp = sum(p and y for p, y in zip(pred, ys)); fp = sum(p and not y for p, y in zip(pred, ys)); fn = sum((not p) and y for p, y in zip(pred, ys))
    prec = tp / (tp + fp) if tp + fp else 0.0; rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "wilson_low": round(GS.wilson_low(tp, tp + fp), 4)}


tr, va, te = rows("train"), rows("valid"), rows("test")
base = sum(y for _f, y in te) / len(te)
vocab = sorted({f for fs, _y in tr for f in fs})
best = max(vocab, key=lambda f: scores([f in fs for fs, _y in va], [y for _f, y in va])["f1"])
out = {"test_base_rate": round(base, 4),
       "single_rule": {"feature": best, "valid": scores([best in fs for fs, _y in va], [y for _f, y in va]),
                       "test": scores([best in fs for fs, _y in te], [y for _f, y in te])}}
from sklearn.tree import DecisionTreeClassifier, export_text  # noqa: E402
idx = {f: i for i, f in enumerate(vocab)}


def X(rs):
    return [[1 if f in fs else 0 for f in vocab] for fs, _y in rs]


cands = []
for depth in range(1, 7):
    m = DecisionTreeClassifier(max_depth=depth, class_weight="balanced", random_state=0).fit(X(tr), [y for _f, y in tr])
    cands.append((scores(list(m.predict(X(va))), [y for _f, y in va])["f1"], depth, m))
f1v, depth, m = max(cands, key=lambda c: c[0])
out["tree"] = {"depth": depth, "valid_f1": f1v, "test": scores(list(m.predict(X(te))), [y for _f, y in te]),
               "leaves": m.get_n_leaves(), "rules": export_text(m, feature_names=vocab, max_depth=3)[:800]}
for k in ("single_rule", "tree"):
    t = out[k]["test"]
    out[k]["popper_gate_passed"] = t["wilson_low"] > base
    out[k]["lift"] = round(t["precision"] / base, 2) if base else None
json.dump(out, open(f"{D}/baseline.json", "w"), indent=1, default=int)
print(json.dumps(out, indent=1, default=int))
