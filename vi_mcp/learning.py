"""Learning — the router learns from the hint lift instead of us setting its weights (docs/TRAINING.md 4a/4b).

Observation = a reported action with label `ok` (0/1); features = triggers of the action (tool, skill, host, thema,
time of day) × shown hints (`hinweis:<id>`, `hinweisart:<art>`, `hinweis_n`). From this a **logistic regression**
learns P(ok | triggers, hint) — the weight per feature is directly readable (sufficient reason). The router then orders
candidates by expected **lift** = P(ok | triggers, hint) − P(ok | triggers) instead of recency + importance.

Training runs during sleep with scikit-learn (Debian: Depends python3-sklearn; if it is missing in a development environment,
the step is skipped with a named reason); the weights are stored as JSON in the object `modell:router` — prediction needs
no sklearn (plain sigmoid sum), so the weights stay readable for everyone.

Minimum amounts (Peduzzi et al. 1996: ≥ 10 events per feature; Harrell): features with < MIN_PER_FEATURE occurrences
are dropped; if min(ok, not ok) < MIN_EVENTS afterwards or the holdout AUC ≤ AUC_MIN, the model stays in mode
`test` (saved, shown, not used) — the router then stays heuristic. This is recorded in the model object.
Feedback loop (labels only for what was shown): each observation keeps `kandidaten`, `gezeigt`, `router`, `exploration`;
a share EPSILON of actions gets a random candidate as exploration (marked).
"""
from __future__ import annotations

import json
import math

from . import memory as g
from .log_output import log

MODEL = "modell:router"
MIN_PER_FEATURE = 10
MIN_EVENTS = 50
AUC_MIN = 0.6
#: 0.20.8: Warning before risky actions. Training sets the threshold on the holdout: a warning is given only where at least
#: WARN_PRECISION of the actions classified that way actually failed there, with at least WARN_MIN_N cases. The model's probabilities
#: are not calibrated because of class_weight="balanced" — so the warning names counted rates, not P(ok).
WARN_PRECISION = 0.5
WARN_MIN_N = 10
EPSILON = 0.1
#: Semantic proximity and content group as features (content.py). Can be switched off to measure the difference.
CONTENT = True
HOLDOUT = 0.2
#: 0.20.9: The holdout (most recent part in time) grows up to HOLDOUT_MAX until it contains at least this many failures. On 09.11. the
#: holdout AUC fell from 0.92 to 0.70 when the most recent 20 % consisted almost only of successful Bash calls (9 failures in 230 actions).
HOLDOUT_MAX = 0.5
HOLDOUT_MIN_ERRORS = 30
#: 0.30.0 utility gate: the model's ranking must order shown hints by their measured advantage, not only separate ok from not ok.
#: Top quarter of holdout pairs by the model's lift against the bottom quarter, advantage = label − base rate of the tool.
UTILITY_MIN_PER_QUARTER = 30
#: 0.32.0 (Mayo, severe testing): the gap must exceed UTILITY_SE standard errors. With 1 SE a model without any real ranking effect
#: passed in about 16 % of trainings (normal approximation); with 2 SE in about 2 %.
UTILITY_SE = 2.0
#: 0.32.0 (generality problem of reliabilism): "advantage over the base rate" depends on the reference class. The gate must hold for
#: each of them — the tool alone, and tool plus host — so that no single arbitrary choice decides.
REFERENCE_CLASSES = ("tool", "tool+host")
TRIGGER_KINDS = ("tool:", "skill:", "host:", "thema:", "fehler:")  # 0.56.0: fehler: — which solution helps which error


def action_features(triggers: list[str], ts: str) -> dict:
    m = {t: 1.0 for t in triggers if t.startswith(TRIGGER_KINDS)}
    m[f"stunde:{ts[11:13]}"] = 1.0
    return m


def _born(hid: str, cache: dict | None) -> str | None:
    """Creation time of a hint (fixed field, so a cache per run is safe)."""
    if cache is not None and hid in cache:
        return cache[hid]
    with g.lock:
        r = g.db().execute("SELECT zeit FROM objekt WHERE id = ?", (hid,)).fetchone()
    if cache is not None:
        cache[hid] = r[0] if r else None
    return r[0] if r else None


def hint_features(hid: str, triggers: list[str] | None = None, ts: str | None = None, born: dict | None = None) -> dict:
    m = {f"hinweis:{hid}": 1.0, f"hinweisart:{hid.split(':')[0]}": 1.0}
    # 0.30.0: was the hint new when it was shown (≤ metrics.NEW_DAYS)? Its weight answers the cold-start question directly, and the
    # router can make up for it. Same threshold as the observation point metrics.lift_by_age — one definition of "new".
    if ts and (b := _born(hid, born)):
        from .metrics import NEW_DAYS
        from datetime import datetime
        if (datetime.fromisoformat(ts) - datetime.fromisoformat(b)).total_seconds() <= NEW_DAYS * 86400:
            m["alter:neu"] = 1.0
    if CONTENT:
        from . import content
        if (c := content.group(hid)) is not None:
            m[f"inhalt:{c}"] = 1.0
        if triggers and (n := content.proximity(hid, [r for r in triggers if r.startswith(TRIGGER_KINDS)])) is not None:
            m["naehe"] = n
    return m


def observations(since: str | None = None) -> list[tuple[dict, int, str]]:
    """(features, ok, experience_id) per reported action with a label; actions answered from memory are dropped.
    One example per shown hint (pair) plus one without hint features (base) — so the model learns both."""
    return [(f, y, o) for f, y, o, _w in weighted_observations(since)]


def weighted_observations(since: str | None = None) -> list[tuple[dict, int, str, float]]:
    """0.55.0: as observations(), with the label's weight (scorer.label: source of the label)."""
    outputs = []
    with g.lock:
        rows = g.db().execute("SELECT id, zeit, daten, gespraech FROM objekt WHERE art = 'erfahrung' AND modus = 'aktiv'" + (" AND zeit >= ?" if since else "") + " ORDER BY zeit",
                              (since,) if since else ()).fetchall()
        labeled = {r[0] for r in g.db().execute("SELECT DISTINCT objekt_id FROM tag WHERE tag IN ('ok:ja', 'ok:nein')")}
        ok_yes = {r[0] for r in g.db().execute("SELECT objekt_id FROM tag WHERE tag = 'ok:ja'")}
    from . import scorer
    grades = scorer.grade_details()
    born: dict = {}
    for oid, ts, data, serial in rows:
        if oid not in labeled:
            continue
        d = json.loads(data)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        y, w, _src = scorer.label(d, oid in ok_yes, serial, grades)
        base = action_features(v.get("reize", []), ts)
        shown = [h for h in v.get("gezeigt", v.get("gefunden", [])) if not h.startswith("antwort:")]
        base[f"hinweis_n:{min(4, len(shown))}"] = 1.0
        if not shown:
            outputs.append((base, y, oid, w))
        for h in shown:  # 0.20.9: direct feedback on this hint replaces the pair's indirect label (scorer.label)
            yh, wh, _s = scorer.label(d, oid in ok_yes, serial, grades, hint=h)
            outputs.append(({**base, **hint_features(h, v.get("reize", []), ts, born)}, yh, oid, wh))
    return outputs


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def model() -> g.MemoryObject | None:
    return g.load(MODEL)


def prediction(m: g.MemoryObject, features: dict) -> float:
    """P(ok | features) from the stored weights — standard library only."""
    w = m.data["gewichte"]
    return _sigmoid(m.data["achsenabschnitt"] + sum(w.get(k, 0.0) * v for k, v in features.items()))


def contributions(m: g.MemoryObject, features: dict) -> list[tuple[str, float]]:
    """0.29.0: weight × value per feature the model knows, largest effect first. Sum + intercept = logit of prediction()."""
    w = m.data["gewichte"]
    return sorted(((k, w[k] * v) for k, v in features.items() if k in w), key=lambda kv: -abs(kv[1]))


def why(m: g.MemoryObject, hint_id: str, triggers: list[str], ts: str | None = None) -> dict:
    """0.29.0: the same arithmetic as ranking() for one hint, laid open: P(ok) without and with the hint, the lift, and which
    features carry it. Situation features cancel out in the lift; the hint's own features and hinweis_n decide.
    0.30.0: hinweis_n is the same for every candidate — it moves every lift alike and never changes the order. It is reported apart
    ("same_for_all"), and "distinguishing" holds only what sets this hint apart from the other candidates (measured 10.11.2026: a hint
    with +3 points measured usefulness showed "lift −14", mostly from hinweis_n:1 −0.35, which says nothing about this hint)."""
    ts = ts or g.now()
    base = action_features(triggers, ts)
    hint = hint_features(hint_id, triggers, ts)
    p0 = prediction(m, {**base, "hinweis_n:0": 1.0})
    p1 = prediction(m, {**base, "hinweis_n:1": 1.0, **hint})
    w = m.data["gewichte"]
    own = contributions(m, hint)
    return {"p_without": p0, "p_with": p1, "lift": p1 - p0, "intercept": m.data["achsenabschnitt"],
            "hint": contributions(m, {"hinweis_n:1": 1.0, **hint}), "distinguishing": own,
            "distinguishing_sum": sum(c for _, c in own),
            "same_for_all": w.get("hinweis_n:1", 0.0) - w.get("hinweis_n:0", 0.0),
            "hint_unknown": [k for k in hint if k not in w], "situation": contributions(m, base)}


def ranking(m: g.MemoryObject, triggers: list[str], candidates: list[str], ts: str | None = None) -> list[tuple[str, float]]:
    """Candidates by expected lift (descending). Unknown hints have lift 0 (only their kind counts)."""
    ts = ts or g.now()
    base = action_features(triggers, ts)
    with_hint = {**base, "hinweis_n:1": 1.0}
    p0 = prediction(m, {**base, "hinweis_n:0": 1.0})
    born: dict = {}
    return sorted(((h, prediction(m, {**with_hint, **hint_features(h, triggers, ts, born)}) - p0) for h in candidates), key=lambda x: -x[1])


def active() -> g.MemoryObject | None:
    m = model()
    return m if m and m.mode == "aktiv" else None


def train(reason: str = "sleep") -> dict:
    """Train with scikit-learn, store weights as JSON. Returns the report (also when skipping, with a named reason)."""
    try:
        import numpy as np
        from sklearn import __version__ as skv
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
    except ImportError as e:
        return {"zustand": "uebersprungen", "grund": f"scikit-learn missing ({e.name}) — install python3-sklearn"}
    wobs = weighted_observations()
    obs = [(f, y, o) for f, y, o, _w in wobs]
    if not obs:
        return {"zustand": "zu_wenig_daten", "grund": "no labeled observations", "n": 0}
    tally: dict[str, int] = {}
    for m, _y, _o in obs:
        for k in m:
            tally[k] = tally.get(k, 0) + 1
    kept = {k for k, n in tally.items() if n >= MIN_PER_FEATURE}
    X_d = [{k: v for k, v in m.items() if k in kept} for m, _y, _o in obs]
    y = np.array([yy for _m, yy, _o in obs])
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    report = {"n": len(obs), "ok": n_pos, "nicht_ok": n_neg, "merkmale": len(kept), "verworfen": len(tally) - len(kept),
               "sklearn": skv, "trainiert": g.now(), "grund": reason}
    if min(n_pos, n_neg) < MIN_EVENTS or not kept:
        report.update(zustand="zu_wenig_daten", urteil=f"min(ok, not ok) = {min(n_pos, n_neg)} < {MIN_EVENTS} or no features ≥ {MIN_PER_FEATURE}")
        _save(report, {}, 0.0, "test")
        return report
    # split by time: older data trains, newer data tests (no look into the future)
    n_test = _holdout_size([yy for _m, yy, _o in obs])
    vec = DictVectorizer(sparse=True)
    X = vec.fit_transform(X_d)
    Xtr, Xte, ytr, yte = X[:-n_test], X[-n_test:], y[:-n_test], y[-n_test:]
    wts = np.array([w for _f, _y, _o, w in wobs])
    clf, fit_report = fit_calibrated(Xtr, ytr, wts[:-n_test])
    report.update(fit_report)
    auc = float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])) if len(set(yte.tolist())) == 2 else None
    weights = {name: round(float(w), 4) for name, w in zip(vec.get_feature_names_out(), clf.coef_[0]) if abs(w) > 1e-6}
    report.update(auc_holdout=None if auc is None else round(auc, 3), holdout=n_test, holdout_fehler=int(len(yte) - yte.sum()),
                   rueckmeldungen=sum(len((json.loads(r[0]) or {}).get("rueckmeldung") or {}) for r in _feedbacks()))
    u = utility(weights, float(clf.intercept_[0]), obs[-n_test:], obs[:-n_test])
    report["nutzen_holdout"] = u
    report["untrennbar"] = inseparable(obs)
    report.update(holdout_metrics(clf, Xte, yte))
    # 0.55.0: champion / challenger — the model of the last sleep against the new one, on what the champion has not seen
    report["champion"] = compare_champion(champion(), weights, float(clf.intercept_[0]), obs[-n_test:])
    if auc is None or auc <= AUC_MIN:
        report.update(zustand="test", urteil=f"holdout AUC {auc} ≤ {AUC_MIN} or not determinable — model saved, router stays heuristic")
        mode = "test"
    elif u["zustand"] != "nutzen":  # 0.30.0: classification alone is not enough, the order has to pay off
        report.update(zustand="test", urteil=f"holdout AUC {auc:.3f} > {AUC_MIN}, but ranking utility {u['zustand']}: "
                                             f"{u.get('urteil') or u.get('grund')} — model saved, router stays heuristic/bandit")
        mode = "test"
    elif report["champion"]["zustand"] == "schlechter":
        report.update(zustand="test", urteil=f"holdout AUC {auc:.3f} > {AUC_MIN} and ranking pays off, but worse than the model of the last "
                                             f"sleep: {report['champion']['urteil']} — the previous weights stay in use")
        mode = "test"
    else:
        report.update(zustand="aktiv", urteil=f"holdout AUC {auc:.3f} > {AUC_MIN} and ranking pays off ({u['urteil']}) — router uses the model")
        mode = "aktiv"
    # 0.30.0: the warning needs only that the model tells failures apart (AUC); the ranking needs more (utility). Two abilities, two gates.
    auc_ok = auc is not None and auc > AUC_MIN
    report["warnung"] = _warn_threshold(clf, vec, obs[-n_test:]) if auc_ok else {"zustand": "aus", "grund": f"holdout AUC {auc} ≤ {AUC_MIN}"}
    report["quoten"] = _ratios(obs, kept)
    if mode == "test" and report["champion"]["zustand"] == "schlechter":
        _keep_champion(report)  # the worse challenger is recorded, the champion's weights stay active
    else:
        _save(report, weights, float(clf.intercept_[0]), mode, new_champion=(reason == "sleep" and mode == "aktiv"))
    log(f"Learning: {report['zustand']} — n {len(obs)}, features {len(kept)}, AUC {report.get('auc_holdout')}, "
        f"warning {report['warnung'].get('zustand')}")
    return report


#: 0.55.0: regularisation strengths tried; sample weights scale the effective C (scikit-learn linear_model), so it is chosen again.
#: 0.1 is left out: measured on a production copy (12.11.2026) it improved log loss (0.400 → 0.393) but cut the hint-ranking gap from
#: +42.4 to +30.6 points — the ranking is what the router is for.
C_GRID = (0.3, 1.0, 3.0)
#: share of the training part (its most recent end) that chooses C; the holdout stays untouched for the verdict
VALIDATION = 0.2
VALIDATION_MIN = 50


def fit_calibrated(Xtr, ytr, wtr):
    """0.55.0 (scikit-learn user guide: linear_model, common_pitfalls). Choose C by the weighted log loss on the newest 20 % of the
    training part (models fitted on the older 80 % with the label weights), then refit on the whole training part with that C — the
    newest observations carry the newest hints. Without both classes in enough validation data: C = 1.
    Checked and rejected: Platt calibration (sigmoid on the logit, folded into the weights). Found on the validation part it did not
    carry over in time — holdout log loss 0.427 → 0.473 and ranking gap +42.4 → +36.9 points (production copy, 12.11.2026)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    n = Xtr.shape[0]
    cut = int(n * (1 - VALIDATION))
    yv, wv = ytr[cut:], wtr[cut:]
    C, chosen = 1.0, {"zustand": "standard", "grund": f"validation part {n - cut} observations or one class only — C = 1"}
    if n - cut >= VALIDATION_MIN and len(set(yv.tolist())) == 2 and len(set(ytr[:cut].tolist())) == 2:
        losses = {}
        for c in C_GRID:
            m = LogisticRegression(class_weight="balanced", C=c, max_iter=1000).fit(Xtr[:cut], ytr[:cut], sample_weight=wtr[:cut])
            losses[c] = round(float(log_loss(yv, m.predict_proba(Xtr[cut:])[:, 1], sample_weight=wv, labels=[0, 1])), 4)
        C = min(losses, key=losses.get)
        chosen = {"zustand": "gewaehlt", "log_loss_validierung": losses, "n": int(n - cut)}
    clf = LogisticRegression(class_weight="balanced", C=C, max_iter=1000).fit(Xtr, ytr, sample_weight=wtr)
    return clf, {"C": C, "c_wahl": chosen}


def _ref_rates(train_obs: list) -> dict:
    """Success rate without a hint per (tool, host), Laplace-smoothed, only with at least 10 cases (as bandit.BASE_MIN)."""
    from . import bandit
    counts: dict[tuple[str, str], list[int]] = {}
    for f, y, _o in train_obs:
        if "hinweis_n:0" not in f:
            continue
        key = (next((k[5:] for k in f if k.startswith("tool:")), "?"), next((k for k in f if k.startswith("host:")), "—"))
        c = counts.setdefault(key, [0, 0])
        c[0] += y
        c[1] += 1
    return {k: (ok + 1) / (n + 2) for k, (ok, n) in counts.items() if n >= bandit.BASE_MIN}


def _gap(scored: list[tuple[float, float]], q: int) -> dict:
    top, bottom = [a for _, a in scored[:q]], [a for _, a in scored[-q:]]
    mean = lambda v: sum(v) / len(v)
    var = lambda v: sum((x - mean(v)) ** 2 for x in v) / (len(v) - 1)
    gap, se = mean(top) - mean(bottom), math.sqrt(var(top) / q + var(bottom) / q)
    ok = gap > 0 and gap > UTILITY_SE * se
    return {"zustand": "nutzen" if ok else "kein_nutzen", "oben": round(mean(top), 4), "unten": round(mean(bottom), 4),
            "abstand": round(gap, 4), "standardfehler": round(se, 4),
            "urteil": (f"top quarter {mean(top) * 100:+.1f} points over the base rate, bottom {mean(bottom) * 100:+.1f} → gap "
                       f"{gap * 100:+.1f} ± {se * 100:.1f} points ({gap / se if se else float('inf'):.1f} SE)"
                       + ("" if ok else f" — not larger than 0 and {UTILITY_SE:g} standard errors"))}


def utility(weights: dict, intercept: float, holdout: list, train_obs: list | None = None) -> dict:
    """0.30.0: does the model's order bring more success? Over the holdout pairs (a shown hint with its label) the pairs are sorted by
    the model's lift for that hint; the gap = mean advantage (label − base rate) of the top quarter minus the bottom quarter, with its
    standard error. AUC only says whether ok and not ok are told apart — a model can do that from the situation alone and still order the
    hints at random. Not an off-policy estimate (propensities exist only for the ε slot); a proxy on the hints that were shown.
    Not compared with the previous model: training on demand runs every minute, so the previous model has seen most of this holdout.
    0.32.0: the gap must exceed UTILITY_SE standard errors (severity) and hold in every reference class (generality problem); the base
    rates for tool+host come from the training part only, never from the holdout."""
    from . import bandit
    m = type("M", (), {"data": {"gewichte": weights, "achsenabschnitt": intercept}})()
    rates = _ref_rates(train_obs or [])
    scored = []  # (lift, y, tool, host)
    for f, y, _o in holdout:
        if not any(k.startswith("hinweis:") for k in f):
            continue
        tool = next((k[5:] for k in f if k.startswith("tool:")), "?")
        host = next((k for k in f if k.startswith("host:")), "—")
        scored.append((prediction(m, f) - prediction(m, _base(f)), y, tool, host))
    q = len(scored) // 4
    if q < UTILITY_MIN_PER_QUARTER:
        return {"zustand": "nicht_bestimmbar", "paare": len(scored),
                "grund": f"{len(scored)} holdout pairs with a hint — at least {4 * UTILITY_MIN_PER_QUARTER} needed ({UTILITY_MIN_PER_QUARTER} per quarter)"}
    scored.sort(key=lambda t: -t[0])
    base = {"tool": lambda tool, host: bandit.base_rate(tool),
            "tool+host": lambda tool, host: rates.get((tool, host), bandit.base_rate(tool))}
    per = {c: _gap([(s_, y - base[c](t, h)) for s_, y, t, h in scored], q) for c in REFERENCE_CLASSES}
    ok = all(r["zustand"] == "nutzen" for r in per.values())
    first = per[REFERENCE_CLASSES[0]]
    return {"zustand": "nutzen" if ok else "kein_nutzen", "paare": len(scored), "je_viertel": q,
            **{k: first[k] for k in ("oben", "unten", "abstand", "standardfehler")}, "je_bezugsklasse": per,
            "urteil": "; ".join(f"{c}: {r['urteil']}" for c, r in per.items())}


def inseparable(obs: list) -> dict:
    """0.32.0 (Duhem): hints that were always shown together (in the same actions, at least MIN_PER_FEATURE times) cannot be told apart
    — an outcome confirms or refutes them only as a group. Named so that their weights are not read as individual evidence."""
    shown_in: dict[str, set] = {}
    for f, _y, oid in obs:
        for k in f:
            if k.startswith("hinweis:"):
                shown_in.setdefault(k[8:], set()).add(oid)
    groups: dict[frozenset, list[str]] = {}
    for h, oids in shown_in.items():
        if len(oids) >= MIN_PER_FEATURE:
            groups.setdefault(frozenset(oids), []).append(h)
    multi = sorted((sorted(v) for v in groups.values() if len(v) > 1), key=lambda v: -len(v))
    return {"gruppen": len(multi), "hinweise": sum(len(v) for v in multi), "beispiele": [v[:4] for v in multi[:5]]}


def _holdout_size(y: list[int]) -> int:
    """Most recent part of the data as holdout: HOLDOUT, grown in 5 % steps up to HOLDOUT_MAX until it has HOLDOUT_MIN_ERRORS failures."""
    n = len(y)
    share = HOLDOUT
    while share < HOLDOUT_MAX and (len(y[-max(1, int(n * share)):]) - sum(y[-max(1, int(n * share)):])) < HOLDOUT_MIN_ERRORS:
        share = round(share + 0.05, 2)
    return max(1, int(n * share))


def _feedbacks() -> list:
    with g.lock:
        return g.db().execute("SELECT daten FROM objekt WHERE art = 'erfahrung' AND daten LIKE '%\"rueckmeldung\"%'").fetchall()


def _base(m: dict) -> dict:
    """Only the situation of the action (without hints) — as vi_before knows it before showing anything."""
    return {**{k: v for k, v in m.items() if k.startswith(TRIGGER_KINDS + ("stunde:",))}, "hinweis_n:0": 1.0}


def _per_experience(obs: list) -> list[tuple[dict, int]]:
    seen, outputs = set(), []
    for m, y, oid in obs:
        if oid not in seen:
            seen.add(oid)
            outputs.append((_base(m), y))
    return outputs


def _ratios(obs: list, kept: set) -> dict:
    """[actions, failed] per situation feature, counted once per experience; "_gesamt" for all."""
    q: dict[str, list[int]] = {"_gesamt": [0, 0]}
    for b, y in _per_experience(obs):
        for k in ["_gesamt"] + [k for k in b if k in kept and k.startswith(TRIGGER_KINDS)]:
            e = q.setdefault(k, [0, 0])
            e[0] += 1
            e[1] += 1 - y
    return q


def _warn_threshold(clf, vec, holdout: list) -> dict:
    """Largest threshold t at which at least WARN_PRECISION of the holdout actions with P(ok) ≤ t failed (≥ WARN_MIN_N cases)."""
    cases = _per_experience(holdout)
    if not cases:
        return {"zustand": "aus", "grund": "no holdout"}
    p = clf.predict_proba(vec.transform([b for b, _y in cases]))[:, 1]
    pairs = sorted(zip(p.tolist(), [y for _b, y in cases]))
    failed_total = sum(1 - y for _p, y in pairs)
    best, n, f = None, 0, 0
    for i, (pp, y) in enumerate(pairs):
        n, f = i + 1, f + (1 - y)
        if n >= WARN_MIN_N and f / n >= WARN_PRECISION and (i + 1 == len(pairs) or pairs[i + 1][0] > pp):
            best = {"schwelle": round(pp, 4), "gewarnt": n, "scheiterten": f}
    if not best:
        return {"zustand": "aus", "grund": f"no threshold with ≥ {WARN_MIN_N} cases and ≥ {int(WARN_PRECISION * 100)} % failed in the holdout"}
    return {"zustand": "aktiv", **best, "praezision_pct": round(100 * best["scheiterten"] / best["gewarnt"]),
            "abdeckung_pct": round(100 * best["scheiterten"] / failed_total) if failed_total else 0, "holdout_handlungen": len(pairs)}


def warning(triggers: list[str], ts: str | None = None) -> str | None:
    """Warning before a risky action — only with an active threshold (set when the holdout AUC passed, also for a model whose ranking
    is not active, 0.30.0) and only with a nameable reason (counted rate)."""
    m = model()
    w = (m.data.get("warnung") or {}) if m else {}
    if w.get("zustand") != "aktiv":
        return None
    base = _base(action_features(triggers, ts or g.now()))
    if prediction(m, base) > w["schwelle"]:
        return None
    q, gw = m.data.get("quoten") or {}, m.data.get("gewichte") or {}
    tot = q.get("_gesamt") or [1, 0]
    rate_total = tot[1] / max(1, tot[0])
    reasons = sorted((k for k in base if gw.get(k, 0.0) < 0 and k in q and q[k][1] / max(1, q[k][0]) > rate_total), key=lambda k: gw[k])[:3]
    if not reasons:
        return None  # no nameable reason, no warning
    parts = "; ".join(f"{k}: {q[k][1]} of {q[k][0]} actions failed ({round(100 * q[k][1] / q[k][0])} %)" for k in reasons)
    return (f"[VI warning] Actions like this one often fail — {parts}; overall {round(100 * rate_total)} %. In the test, "
            f"{w['scheiterten']} of {w['gewarnt']} actions classified this way failed ({w['praezision_pct']} %). Check arguments, paths and reachability first.")


def _save(report: dict, weights: dict, intercept: float, mode: str, new_champion: bool = False) -> g.MemoryObject:
    m = g.load(MODEL)
    data = {**report, "gewichte": weights, "achsenabschnitt": round(intercept, 4)}
    # 0.55.0: the champion is the model of the last sleep in which it went active; carried over by every other training
    if new_champion:
        data["champion_modell"] = {"gewichte": weights, "achsenabschnitt": round(intercept, 4), "trainiert": report.get("trainiert")}
    elif m is not None and m.data.get("champion_modell"):
        data["champion_modell"] = m.data["champion_modell"]
    text = (f"Router model ({report.get('zustand')}): {report.get('n', 0)} observations, {report.get('merkmale', 0)} features, "
            f"AUC {report.get('auc_holdout', '—')} — {report.get('urteil', report.get('grund', ''))}")
    if m is None:
        return g.new_object("modell", text, ["modell:router"], data, importance=2, who="vi", oid=MODEL,
                              mode=mode, reason=report.get("grund", "learning"), instance=g.SERVER_INSTANCE)
    m.text, m.data, m.mode = text, {**data, "versionen": m.data.get("versionen", 0) + 1}, mode
    m.change("vi", f"retrained → {mode}", report.get("grund", "learning"))
    return g.save(m)


#: 0.55.0: a challenger is compared with the champion on at least this many holdout observations the champion has not seen
CHAMPION_MIN_N = 200


def champion() -> dict | None:
    """The model of the last sleep in which a model went active (weights, intercept, trained) — or None."""
    m = model()
    return (m.data.get("champion_modell") or None) if m else None


def _times(oids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    with g.lock:
        for i in range(0, len(oids), 500):
            part = oids[i:i + 500]
            out.update({r[0]: r[1] for r in g.db().execute(f"SELECT id, zeit FROM objekt WHERE id IN ({','.join('?' * len(part))})", part)})
    return out


def compare_champion(champ: dict | None, weights: dict, intercept: float, holdout: list) -> dict:
    """0.55.0: champion / challenger. Both models predict the holdout observations that arose after the champion was trained (it has not
    seen them; the challenger has not either — they are its holdout). Paired difference of the log loss per observation (scikit-learn
    model_evaluation: log loss is the proper scoring rule for probabilities); the challenger is `schlechter` when its mean loss is higher
    by more than one standard error of that difference. Exhaustive: kein_champion · nicht_bestimmbar · schlechter · nicht_schlechter."""
    if not champ or not champ.get("gewichte"):
        return {"zustand": "kein_champion", "urteil": "no model of an earlier sleep to compare with"}
    since = str(champ.get("trainiert") or "")
    ts = _times([o for _f, _y, o in holdout])
    unseen = [(f, y) for f, y, o in holdout if ts.get(o, "") > since]
    if len(unseen) < CHAMPION_MIN_N:
        return {"zustand": "nicht_bestimmbar", "n": len(unseen), "seit": since[:16],
                "urteil": f"{len(unseen)} holdout observations since the champion ({since[:16]}) — at least {CHAMPION_MIN_N} needed"}
    c = type("M", (), {"data": champ})()
    n = type("M", (), {"data": {"gewichte": weights, "achsenabschnitt": intercept}})()
    eps = 1e-12

    def loss(m, f, y):
        p = min(1 - eps, max(eps, prediction(m, f)))
        return -math.log(p if y else 1 - p)
    d = [loss(n, f, y) - loss(c, f, y) for f, y in unseen]
    mean = sum(d) / len(d)
    se = math.sqrt(sum((x - mean) ** 2 for x in d) / (len(d) - 1) / len(d))
    worse = mean > 0 and mean > se
    lc = sum(loss(c, f, y) for f, y in unseen) / len(unseen)
    return {"zustand": "schlechter" if worse else "nicht_schlechter", "n": len(unseen), "seit": since[:16],
            "log_loss_champion": round(lc, 4), "log_loss_neu": round(lc + mean, 4), "differenz": round(mean, 4), "standardfehler": round(se, 4),
            "urteil": f"log loss new {lc + mean:.4f} vs champion {lc:.4f} on {len(unseen)} observations since {since[:16]} "
                      f"(difference {mean:+.4f} ± {se:.4f})" + (" — worse by more than one standard error" if worse else "")}


def holdout_metrics(clf, Xte, yte) -> dict:
    """0.55.0: besides AUC (ranking of ok/not ok) the proper scoring rules for the probabilities and the precision-recall summary
    (scikit-learn model_evaluation). class_weight='balanced' shifts the probabilities, so log loss and Brier show the miscalibration too."""
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss
    if len(set(yte.tolist())) < 2:
        return {}
    p = clf.predict_proba(Xte)[:, 1]
    return {"log_loss_holdout": round(float(log_loss(yte, p, labels=[0, 1])), 4), "brier_holdout": round(float(brier_score_loss(yte, p)), 4),
            # average precision for the minority class "not ok" — the warning works on it
            "ap_fehler_holdout": round(float(average_precision_score(1 - yte, 1 - p)), 4)}


def _keep_champion(report: dict) -> None:
    """A challenger worse than the champion: record its report, keep the champion's weights active (named in the model text)."""
    m = g.load(MODEL)
    champ = champion()
    if m is None or not champ:
        return
    data = {**report, "gewichte": champ["gewichte"], "achsenabschnitt": champ["achsenabschnitt"], "champion_modell": champ,
            "zustand": "aktiv", "herausforderer_verworfen": report.get("trainiert"),
            "warnung": m.data.get("warnung") or {"zustand": "aus", "grund": "champion kept without a warning threshold"}}
    m.text = (f"Router model (aktiv, champion of {str(champ.get('trainiert'))[:16]}): challenger rejected — {report['champion']['urteil']}")
    m.data, m.mode = {**data, "versionen": m.data.get("versionen", 0) + 1}, "aktiv"
    m.change("vi", "challenger rejected, champion kept", report.get("grund", "learning"))
    g.save(m)


def training_notice() -> str:
    """0.57.0: the short [Training] block at the top of the instructions — what an AI needs to read the hints: who chooses them, from
    what they learn, what the marker on each line means, and what to do with a solution found elsewhere. With the model's own numbers."""
    m = model()
    if m is None:
        state = "the router has no model yet (heuristic order)"
    else:
        d = m.data
        word = {"aktiv": "active", "test": "in test, not used", "zu_wenig_daten": "too little data"}.get(d.get("zustand", m.mode), d.get("zustand", m.mode))
        state = f"router {word}, AUC {d.get('auc_holdout', '—')}, {d.get('n', 0)} observations, trained {str(d.get('trainiert', '—'))[:10]}"
    return ("[Training] Hints and error solutions are chosen by a model retrained daily on the outcomes of all agents (" + state + "); "
            "your vi_after outcomes and vi_feedback are its labels. Each hint says what was measured: \"measured +X pts/N×\" = success "
            "after showing it over the tool's base rate, \"unmeasured\" = no data yet, \"exploration\" = a random pick to learn from. "
            "Solved something via web or docs: vi_solved with the URL. vi_why <id> explains a hint.")


def explanation(limit: int = 12) -> str:
    m = model()
    if not m:
        return "no router model yet — it is created during sleep once there are enough observations (router: heuristic)"
    d = m.data
    z = [m.text, f"  trained {str(d.get('trainiert', '—'))[:16]} · sklearn {d.get('sklearn', '—')} · ok {d.get('ok', 0)} / not ok {d.get('nicht_ok', 0)} "
                 f"· features {d.get('merkmale', 0)} (dropped {d.get('verworfen', 0)}: < {MIN_PER_FEATURE} occurrences) · holdout {d.get('holdout', 0)} "
                 f"({d.get('holdout_fehler', '—')} failures) · direct feedback on hints {d.get('rueckmeldungen', 0)}"]
    if d.get("C") is not None:  # 0.55.0
        cw = d.get("c_wahl") or {}
        z.append(f"  Regularisation C {d['C']} (" + (f"chosen by log loss on the newest {cw.get('n')} training observations: {cw.get('log_loss_validierung')}"
                                                     if cw.get("zustand") == "gewaehlt" else cw.get("grund", "—")) + ")")
    if d.get("log_loss_holdout") is not None:  # 0.55.0
        z.append(f"  Holdout probabilities: log loss {d['log_loss_holdout']} · Brier {d.get('brier_holdout')} · average precision for "
                 f"failures {d.get('ap_fehler_holdout')}")
    if d.get("champion"):  # 0.55.0
        z.append(f"  Champion / challenger: {d['champion']['zustand']} — {d['champion'].get('urteil', '')}")
    u = d.get("nutzen_holdout")
    if u:  # 0.30.0
        z.append(f"  Ranking utility on the holdout: {u['zustand']} — {u.get('urteil') or u.get('grund')}")
    t = d.get("untrennbar")
    if t is not None:  # 0.32.0
        z.append("  Inseparable hints (always shown together, the model cannot tell their effect apart): "
                 + (f"{t['gruppen']} group(s) with {t['hinweise']} hints, e.g. " + "; ".join(" + ".join(g) for g in t["beispiele"][:2])
                    if t["gruppen"] else "none"))
    w = sorted(d.get("gewichte", {}).items(), key=lambda kv: -abs(kv[1]))[:limit]
    if w:
        z.append("  strongest weights (positive = raises P(ok)):")
        from . import content
        z += [f"    {k:50} {v:+.3f}" + (f"  ({content.group_name(int(k[7:]))})" if k.startswith("inhalt:") and k[7:].isdigit() else "")
              + ("  (semantic proximity hint ↔ situation, 0–1)" if k == "naehe" else "") for k, v in w]
    w = d.get("warnung") or {}
    z.append("  Warning before risky actions: " + (f"active — threshold P ≤ {w['schwelle']}, in the holdout {w['scheiterten']} of "
             f"{w['gewarnt']} warned actions failed ({w['praezision_pct']} %), covers {w['abdeckung_pct']} % of all failures"
             if w.get("zustand") == "aktiv" else f"off — {w.get('grund', 'not trained yet')}"))
    if CONTENT:
        from . import content
        z.append(f"  Content: {content.line()}")
    from . import weight_audit
    z.append("  " + weight_audit.line(weight_audit.audit(m)))
    return "\n".join(z)
