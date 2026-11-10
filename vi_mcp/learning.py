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
TRIGGER_KINDS = ("tool:", "skill:", "host:", "thema:")


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
    outputs = []
    with g.lock:
        rows = g.db().execute("SELECT id, zeit, daten, gespraech FROM objekt WHERE art = 'erfahrung' AND modus = 'aktiv'" + (" AND zeit >= ?" if since else "") + " ORDER BY zeit",
                              (since,) if since else ()).fetchall()
        labeled = {r[0] for r in g.db().execute("SELECT DISTINCT objekt_id FROM tag WHERE tag IN ('ok:ja', 'ok:nein')")}
        ok_yes = {r[0] for r in g.db().execute("SELECT objekt_id FROM tag WHERE tag = 'ok:ja'")}
    from . import scorer
    grades = scorer.conversation_grades()
    born: dict = {}
    for oid, ts, data, serial in rows:
        if oid not in labeled:
            continue
        d = json.loads(data)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        s = d.get("score")  # label: the scorer's verdict, else "tool without error"; a bad conversation grade applies to all actions
        y = (1 if s["note"] >= scorer.GOOD_FROM else 0) if s else (1 if oid in ok_yes else 0)
        if serial in grades and grades[serial] < scorer.BAD_BELOW:
            y = 0
        base = action_features(v.get("reize", []), ts)
        shown = [h for h in v.get("gezeigt", v.get("gefunden", [])) if not h.startswith("antwort:")]
        base[f"hinweis_n:{min(4, len(shown))}"] = 1.0
        if not shown:
            outputs.append((base, y, oid))
        rm = d.get("rueckmeldung") or {}  # 0.20.9: direct feedback (vi_confirm/vi_refute) replaces the pair's indirect label
        for h in shown:
            outputs.append(({**base, **hint_features(h, v.get("reize", []), ts, born)}, (1 if rm[h] > 0 else 0) if h in rm else y, oid))
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
    obs = observations()
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
    clf = LogisticRegression(class_weight="balanced", C=1.0, max_iter=1000)
    clf.fit(Xtr, ytr)
    auc = float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])) if len(set(yte.tolist())) == 2 else None
    weights = {name: round(float(w), 4) for name, w in zip(vec.get_feature_names_out(), clf.coef_[0]) if abs(w) > 1e-6}
    report.update(auc_holdout=None if auc is None else round(auc, 3), holdout=n_test, holdout_fehler=int(len(yte) - yte.sum()),
                   rueckmeldungen=sum(len((json.loads(r[0]) or {}).get("rueckmeldung") or {}) for r in _feedbacks()))
    u = utility(weights, float(clf.intercept_[0]), obs[-n_test:])
    report["nutzen_holdout"] = u
    if auc is None or auc <= AUC_MIN:
        report.update(zustand="test", urteil=f"holdout AUC {auc} ≤ {AUC_MIN} or not determinable — model saved, router stays heuristic")
        mode = "test"
    elif u["zustand"] != "nutzen":  # 0.30.0: classification alone is not enough, the order has to pay off
        report.update(zustand="test", urteil=f"holdout AUC {auc:.3f} > {AUC_MIN}, but ranking utility {u['zustand']}: "
                                             f"{u.get('urteil') or u.get('grund')} — model saved, router stays heuristic/bandit")
        mode = "test"
    else:
        report.update(zustand="aktiv", urteil=f"holdout AUC {auc:.3f} > {AUC_MIN} and ranking pays off ({u['urteil']}) — router uses the model")
        mode = "aktiv"
    # 0.30.0: the warning needs only that the model tells failures apart (AUC); the ranking needs more (utility). Two abilities, two gates.
    auc_ok = auc is not None and auc > AUC_MIN
    report["warnung"] = _warn_threshold(clf, vec, obs[-n_test:]) if auc_ok else {"zustand": "aus", "grund": f"holdout AUC {auc} ≤ {AUC_MIN}"}
    report["quoten"] = _ratios(obs, kept)
    _save(report, weights, float(clf.intercept_[0]), mode)
    log(f"Learning: {report['zustand']} — n {len(obs)}, features {len(kept)}, AUC {report.get('auc_holdout')}, "
        f"warning {report['warnung'].get('zustand')}")
    return report


def utility(weights: dict, intercept: float, holdout: list) -> dict:
    """0.30.0: does the model's order bring more success? Over the holdout pairs (a shown hint with its label) the pairs are sorted by
    the model's lift for that hint; the gap = mean advantage (label − base rate of the tool) of the top quarter minus the bottom quarter,
    with its standard error. AUC only says whether ok and not ok are told apart — a model can do that from the situation alone and still
    order the hints at random. Not an off-policy estimate (propensities exist only for the ε slot); a proxy on the hints that were shown.
    Not compared with the previous model: training on demand runs every minute, so the previous model has seen most of this holdout."""
    from . import bandit
    m = type("M", (), {"data": {"gewichte": weights, "achsenabschnitt": intercept}})()
    scored = []
    for f, y, _o in holdout:
        if not any(k.startswith("hinweis:") for k in f):
            continue
        tool = next((k[5:] for k in f if k.startswith("tool:")), "?")
        scored.append((prediction(m, f) - prediction(m, _base(f)), y - bandit.base_rate(tool)))
    q = len(scored) // 4
    if q < UTILITY_MIN_PER_QUARTER:
        return {"zustand": "nicht_bestimmbar", "paare": len(scored),
                "grund": f"{len(scored)} holdout pairs with a hint — at least {4 * UTILITY_MIN_PER_QUARTER} needed ({UTILITY_MIN_PER_QUARTER} per quarter)"}
    scored.sort(key=lambda t: -t[0])
    top, bottom = [a for _, a in scored[:q]], [a for _, a in scored[-q:]]
    mean = lambda v: sum(v) / len(v)
    var = lambda v: sum((x - mean(v)) ** 2 for x in v) / (len(v) - 1)
    gap, se = mean(top) - mean(bottom), math.sqrt(var(top) / q + var(bottom) / q)
    ok = gap > 0 and gap > se
    return {"zustand": "nutzen" if ok else "kein_nutzen", "paare": len(scored), "je_viertel": q, "oben": round(mean(top), 4),
            "unten": round(mean(bottom), 4), "abstand": round(gap, 4), "standardfehler": round(se, 4),
            "urteil": (f"top quarter {mean(top) * 100:+.1f} points over the base rate, bottom {mean(bottom) * 100:+.1f} → gap "
                       f"{gap * 100:+.1f} ± {se * 100:.1f} points" + ("" if ok else " — not larger than 0 and its standard error"))}


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


def _save(report: dict, weights: dict, intercept: float, mode: str) -> g.MemoryObject:
    m = g.load(MODEL)
    data = {**report, "gewichte": weights, "achsenabschnitt": round(intercept, 4)}
    text = (f"Router model ({report.get('zustand')}): {report.get('n', 0)} observations, {report.get('merkmale', 0)} features, "
            f"AUC {report.get('auc_holdout', '—')} — {report.get('urteil', report.get('grund', ''))}")
    if m is None:
        return g.new_object("modell", text, ["modell:router"], data, importance=2, who="vi", oid=MODEL,
                              mode=mode, reason=report.get("grund", "learning"), instance=g.SERVER_INSTANCE)
    m.text, m.data, m.mode = text, {**data, "versionen": m.data.get("versionen", 0) + 1}, mode
    m.change("vi", f"retrained → {mode}", report.get("grund", "learning"))
    return g.save(m)


def explanation(limit: int = 12) -> str:
    m = model()
    if not m:
        return "no router model yet — it is created during sleep once there are enough observations (router: heuristic)"
    d = m.data
    z = [m.text, f"  trained {str(d.get('trainiert', '—'))[:16]} · sklearn {d.get('sklearn', '—')} · ok {d.get('ok', 0)} / not ok {d.get('nicht_ok', 0)} "
                 f"· features {d.get('merkmale', 0)} (dropped {d.get('verworfen', 0)}: < {MIN_PER_FEATURE} occurrences) · holdout {d.get('holdout', 0)} "
                 f"({d.get('holdout_fehler', '—')} failures) · direct feedback on hints {d.get('rueckmeldungen', 0)}"]
    u = d.get("nutzen_holdout")
    if u:  # 0.30.0
        z.append(f"  Ranking utility on the holdout: {u['zustand']} — {u.get('urteil') or u.get('grund')}")
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
