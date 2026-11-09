"""Lernen — der Router lernt aus dem Hinweis-Lift, statt dass wir seine Gewichte setzen (docs/TRAINING.md 4a/4b).

Beobachtung = eine gemeldete Handlung mit Label `ok` (0/1); Merkmale = Reize der Handlung (tool, skill, host, thema,
Tageszeit) × gezeigte Hinweise (`hinweis:<id>`, `hinweisart:<art>`, `hinweis_n`). Daraus lernt eine **logistische
Regression** P(ok | Reize, Hinweis) — das Gewicht je Merkmal ist direkt lesbar (zureichender Grund). Der Router ordnet
Kandidaten dann nach erwartetem **Lift** = P(ok | Reize, Hinweis) − P(ok | Reize), statt nach Aktualität + Wichtigkeit.

Trainiert wird im Schlaf mit scikit-learn (Debian: Depends python3-sklearn; fehlt es in einer Entwicklungsumgebung,
wird der Schritt benannt übersprungen); die Gewichte stehen als JSON im Objekt `modell:router` — Vorhersage braucht
kein sklearn (reine Sigmoid-Summe), damit die Gewichte für jeden nachlesbar bleiben.

Mindestmengen (Peduzzi et al. 1996: ≥ 10 Ereignisse je Merkmal; Harrell): Merkmale mit < MIN_JE_MERKMAL Vorkommen
fallen weg; ist danach min(ok, nicht ok) < MIN_EREIGNISSE oder die Holdout-AUC ≤ AUC_MIN, bleibt das Modell im Modus
`test` (gespeichert, gezeigt, nicht benutzt) — der Router bleibt dann Heuristik. Das steht im Modellobjekt.
Rückkopplung (Labels nur für Gezeigtes): jede Beobachtung hält `kandidaten`, `gezeigt`, `router`, `exploration`;
ein Anteil EPSILON der Handlungen bekommt einen zufälligen Kandidaten als Erkundung (markiert).
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
#: 0.20.8: Warnung vor riskanten Handlungen. Die Schwelle legt das Training im Holdout fest: gewarnt wird nur, wo dort mindestens
#: WARN_PRAEZISION der so eingestuften Handlungen tatsächlich scheiterte, bei mindestens WARN_MIN_N Fällen. Die Wahrscheinlichkeiten
#: des Modells sind wegen class_weight="balanced" nicht kalibriert — deshalb nennt die Warnung gezählte Quoten, nicht P(ok).
WARN_PRECISION = 0.5
WARN_MIN_N = 10
EPSILON = 0.1
#: Bedeutungsnähe und Inhaltsgruppe als Merkmale (inhalt.py). Abschaltbar, um den Unterschied zu messen.
CONTENT = True
HOLDOUT = 0.2
#: 0.20.9: Das Holdout (zeitlich jüngster Teil) wächst bis HOLDOUT_MAX, bis es mindestens so viele Fehlschläge enthält. Am 09.11. fiel die
#: Holdout-AUC von 0,92 auf 0,70, als die jüngsten 20 % fast nur aus gelungenen Bash-Aufrufen bestanden (9 Fehlschläge in 230 Handlungen).
HOLDOUT_MAX = 0.5
HOLDOUT_MIN_ERRORS = 30
TRIGGER_KINDS = ("tool:", "skill:", "host:", "thema:")


def action_features(triggers: list[str], ts: str) -> dict:
    m = {t: 1.0 for t in triggers if t.startswith(TRIGGER_KINDS)}
    m[f"stunde:{ts[11:13]}"] = 1.0
    return m


def hint_features(hid: str, triggers: list[str] | None = None) -> dict:
    m = {f"hinweis:{hid}": 1.0, f"hinweisart:{hid.split(':')[0]}": 1.0}
    if CONTENT:
        from . import content
        if (c := content.group(hid)) is not None:
            m[f"inhalt:{c}"] = 1.0
        if triggers and (n := content.proximity(hid, [r for r in triggers if r.startswith(TRIGGER_KINDS)])) is not None:
            m["naehe"] = n
    return m


def observations(since: str | None = None) -> list[tuple[dict, int, str]]:
    """(Merkmale, ok, erfahrung_id) je gemeldeter Handlung mit Label; aus dem Gedächtnis beantwortete fallen weg.
    Ein Beispiel je gezeigtem Hinweis (Paar) plus eines ohne Hinweis-Merkmale (Basis) — so lernt das Modell beides."""
    outputs = []
    with g.lock:
        rows = g.db().execute("SELECT id, zeit, daten, gespraech FROM objekt WHERE art = 'erfahrung' AND modus = 'aktiv'" + (" AND zeit >= ?" if since else "") + " ORDER BY zeit",
                              (since,) if since else ()).fetchall()
        labeled = {r[0] for r in g.db().execute("SELECT DISTINCT objekt_id FROM tag WHERE tag IN ('ok:ja', 'ok:nein')")}
        ok_yes = {r[0] for r in g.db().execute("SELECT objekt_id FROM tag WHERE tag = 'ok:ja'")}
    from . import scorer
    grades = scorer.conversation_grades()
    for oid, ts, data, serial in rows:
        if oid not in labeled:
            continue
        d = json.loads(data)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        s = d.get("score")  # Label: Urteil des Scorers, sonst „Werkzeug ohne Fehler“; eine schlechte Gesprächsnote gilt für alle Handlungen
        y = (1 if s["note"] >= scorer.GOOD_FROM else 0) if s else (1 if oid in ok_yes else 0)
        if serial in grades and grades[serial] < scorer.BAD_BELOW:
            y = 0
        base = action_features(v.get("reize", []), ts)
        shown = [h for h in v.get("gezeigt", v.get("gefunden", [])) if not h.startswith("antwort:")]
        base[f"hinweis_n:{min(4, len(shown))}"] = 1.0
        if not shown:
            outputs.append((base, y, oid))
        rm = d.get("rueckmeldung") or {}  # 0.20.9: direkte Rückmeldung (vi_bestaetige/vi_widerlege) ersetzt das indirekte Label des Paares
        for h in shown:
            outputs.append(({**base, **hint_features(h, v.get("reize", []))}, (1 if rm[h] > 0 else 0) if h in rm else y, oid))
    return outputs


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def model() -> g.MemoryObject | None:
    return g.load(MODEL)


def prediction(m: g.MemoryObject, features: dict) -> float:
    """P(ok | Merkmale) aus den gespeicherten Gewichten — reine Standardbibliothek."""
    w = m.data["gewichte"]
    return _sigmoid(m.data["achsenabschnitt"] + sum(w.get(k, 0.0) * v for k, v in features.items()))


def ranking(m: g.MemoryObject, triggers: list[str], candidates: list[str], ts: str | None = None) -> list[tuple[str, float]]:
    """Kandidaten nach erwartetem Lift (absteigend). Unbekannte Hinweise haben Lift 0 (nur ihre Art zählt)."""
    base = action_features(triggers, ts or g.now())
    with_hint = {**base, "hinweis_n:1": 1.0}
    p0 = prediction(m, {**base, "hinweis_n:0": 1.0})
    return sorted(((h, prediction(m, {**with_hint, **hint_features(h, triggers)}) - p0) for h in candidates), key=lambda x: -x[1])


def active() -> g.MemoryObject | None:
    m = model()
    return m if m and m.mode == "aktiv" else None


def train(reason: str = "Schlaf") -> dict:
    """Mit scikit-learn trainieren, Gewichte als JSON speichern. Liefert den Bericht (auch bei Verzicht, benannt)."""
    try:
        import numpy as np
        from sklearn import __version__ as skv
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
    except ImportError as e:
        return {"zustand": "uebersprungen", "grund": f"scikit-learn fehlt ({e.name}) — python3-sklearn installieren"}
    obs = observations()
    if not obs:
        return {"zustand": "zu_wenig_daten", "grund": "keine Beobachtungen mit Label", "n": 0}
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
        report.update(zustand="zu_wenig_daten", urteil=f"min(ok, nicht ok) = {min(n_pos, n_neg)} < {MIN_EVENTS} oder keine Merkmale ≥ {MIN_PER_FEATURE}")
        _save(report, {}, 0.0, "test")
        return report
    # zeitliche Teilung: Älteres lernt, Neueres prüft (kein Blick in die Zukunft)
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
    if auc is None or auc <= AUC_MIN:
        report.update(zustand="test", urteil=f"Holdout-AUC {auc} ≤ {AUC_MIN} oder nicht bestimmbar — Modell gespeichert, Router bleibt Heuristik")
        mode = "test"
    else:
        report.update(zustand="aktiv", urteil=f"Holdout-AUC {auc:.3f} > {AUC_MIN} — Router nutzt das Modell")
        mode = "aktiv"
    report["warnung"] = _warn_threshold(clf, vec, obs[-n_test:]) if mode == "aktiv" else {"zustand": "aus", "grund": "Modell nicht aktiv"}
    report["quoten"] = _ratios(obs, kept)
    _save(report, weights, float(clf.intercept_[0]), mode)
    log(f"Lernen: {report['zustand']} — n {len(obs)}, Merkmale {len(kept)}, AUC {report.get('auc_holdout')}, "
        f"Warnung {report['warnung'].get('zustand')}")
    return report


def _holdout_size(y: list[int]) -> int:
    """Jüngster Teil der Daten als Holdout: HOLDOUT, vergrößert in 5-%-Schritten bis HOLDOUT_MAX, bis er HOLDOUT_MIN_FEHLER Fehlschläge hat."""
    n = len(y)
    share = HOLDOUT
    while share < HOLDOUT_MAX and (len(y[-max(1, int(n * share)):]) - sum(y[-max(1, int(n * share)):])) < HOLDOUT_MIN_ERRORS:
        share = round(share + 0.05, 2)
    return max(1, int(n * share))


def _feedbacks() -> list:
    with g.lock:
        return g.db().execute("SELECT daten FROM objekt WHERE art = 'erfahrung' AND daten LIKE '%\"rueckmeldung\"%'").fetchall()


def _base(m: dict) -> dict:
    """Nur die Lage der Handlung (ohne Hinweise) — so, wie vi_vorher sie vor dem Zeigen kennt."""
    return {**{k: v for k, v in m.items() if k.startswith(TRIGGER_KINDS + ("stunde:",))}, "hinweis_n:0": 1.0}


def _per_experience(obs: list) -> list[tuple[dict, int]]:
    seen, outputs = set(), []
    for m, y, oid in obs:
        if oid not in seen:
            seen.add(oid)
            outputs.append((_base(m), y))
    return outputs


def _ratios(obs: list, kept: set) -> dict:
    """[Handlungen, gescheitert] je Situationsmerkmal, je Erfahrung einmal gezählt; „_gesamt“ für alle."""
    q: dict[str, list[int]] = {"_gesamt": [0, 0]}
    for b, y in _per_experience(obs):
        for k in ["_gesamt"] + [k for k in b if k in kept and k.startswith(TRIGGER_KINDS)]:
            e = q.setdefault(k, [0, 0])
            e[0] += 1
            e[1] += 1 - y
    return q


def _warn_threshold(clf, vec, holdout: list) -> dict:
    """Größte Schwelle t, bei der im Holdout von den Handlungen mit P(ok) ≤ t mindestens WARN_PRAEZISION scheiterten (≥ WARN_MIN_N Fälle)."""
    cases = _per_experience(holdout)
    if not cases:
        return {"zustand": "aus", "grund": "kein Holdout"}
    p = clf.predict_proba(vec.transform([b for b, _y in cases]))[:, 1]
    pairs = sorted(zip(p.tolist(), [y for _b, y in cases]))
    failed_total = sum(1 - y for _p, y in pairs)
    best, n, f = None, 0, 0
    for i, (pp, y) in enumerate(pairs):
        n, f = i + 1, f + (1 - y)
        if n >= WARN_MIN_N and f / n >= WARN_PRECISION and (i + 1 == len(pairs) or pairs[i + 1][0] > pp):
            best = {"schwelle": round(pp, 4), "gewarnt": n, "scheiterten": f}
    if not best:
        return {"zustand": "aus", "grund": f"keine Schwelle mit ≥ {WARN_MIN_N} Fällen und ≥ {int(WARN_PRECISION * 100)} % gescheitert im Holdout"}
    return {"zustand": "aktiv", **best, "praezision_pct": round(100 * best["scheiterten"] / best["gewarnt"]),
            "abdeckung_pct": round(100 * best["scheiterten"] / failed_total) if failed_total else 0, "holdout_handlungen": len(pairs)}


def warning(triggers: list[str], ts: str | None = None) -> str | None:
    """Warnung vor einer riskanten Handlung — nur bei aktivem Modell und aktiver Schwelle, nur mit benennbarem Grund (gezählte Quote)."""
    m = active()
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
        return None  # ohne benennbaren Grund keine Warnung
    parts = "; ".join(f"{k}: {q[k][1]} von {q[k][0]} Handlungen scheiterten ({round(100 * q[k][1] / q[k][0])} %)" for k in reasons)
    return (f"[VI-Warnung] Handlungen wie diese scheitern oft — {parts}; insgesamt {round(100 * rate_total)} %. Im Test scheiterten "
            f"{w['scheiterten']} von {w['gewarnt']} so eingestuften Handlungen ({w['praezision_pct']} %). Vorher Argumente, Pfade und Erreichbarkeit prüfen.")


def _save(report: dict, weights: dict, intercept: float, mode: str) -> g.MemoryObject:
    m = g.load(MODEL)
    data = {**report, "gewichte": weights, "achsenabschnitt": round(intercept, 4)}
    text = (f"Router-Modell ({report.get('zustand')}): {report.get('n', 0)} Beobachtungen, {report.get('merkmale', 0)} Merkmale, "
            f"AUC {report.get('auc_holdout', '—')} — {report.get('urteil', report.get('grund', ''))}")
    if m is None:
        return g.new_object("modell", text, ["modell:router"], data, importance=2, who="vi", oid=MODEL,
                              mode=mode, reason=report.get("grund", "Lernen"), instance=g.SERVER_INSTANCE)
    m.text, m.data, m.mode = text, {**data, "versionen": m.data.get("versionen", 0) + 1}, mode
    m.change("vi", f"neu trainiert → {mode}", report.get("grund", "Lernen"))
    return g.save(m)


def explanation(limit: int = 12) -> str:
    m = model()
    if not m:
        return "noch kein Router-Modell — entsteht im Schlaf, sobald genug Beobachtungen vorliegen (Router: Heuristik)"
    d = m.data
    z = [m.text, f"  trainiert {str(d.get('trainiert', '—'))[:16]} · sklearn {d.get('sklearn', '—')} · ok {d.get('ok', 0)} / nicht ok {d.get('nicht_ok', 0)} "
                 f"· Merkmale {d.get('merkmale', 0)} (verworfen {d.get('verworfen', 0)}: < {MIN_PER_FEATURE} Vorkommen) · Holdout {d.get('holdout', 0)} "
                 f"({d.get('holdout_fehler', '—')} Fehlschläge) · direkte Rückmeldungen zu Hinweisen {d.get('rueckmeldungen', 0)}"]
    w = sorted(d.get("gewichte", {}).items(), key=lambda kv: -abs(kv[1]))[:limit]
    if w:
        z.append("  stärkste Gewichte (positiv = erhöht P(ok)):")
        from . import content
        z += [f"    {k:50} {v:+.3f}" + (f"  ({content.group_name(int(k[7:]))})" if k.startswith("inhalt:") and k[7:].isdigit() else "")
              + ("  (Bedeutungsnähe Hinweis ↔ Situation, 0–1)" if k == "naehe" else "") for k, v in w]
    w = d.get("warnung") or {}
    z.append("  Warnung vor riskanten Handlungen: " + (f"aktiv — Schwelle P ≤ {w['schwelle']}, im Holdout scheiterten {w['scheiterten']} von "
             f"{w['gewarnt']} gewarnten ({w['praezision_pct']} %), erfasst {w['abdeckung_pct']} % aller Fehlschläge"
             if w.get("zustand") == "aktiv" else f"aus — {w.get('grund', 'noch nicht trainiert')}"))
    if CONTENT:
        from . import content
        z.append(f"  Inhalt: {content.line()}")
    return "\n".join(z)
