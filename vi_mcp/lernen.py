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

from . import gedaechtnis as g
from .protokoll import log

MODELL = "modell:router"
MIN_JE_MERKMAL = 10
MIN_EREIGNISSE = 50
AUC_MIN = 0.6
#: 0.20.8: Warnung vor riskanten Handlungen. Die Schwelle legt das Training im Holdout fest: gewarnt wird nur, wo dort mindestens
#: WARN_PRAEZISION der so eingestuften Handlungen tatsächlich scheiterte, bei mindestens WARN_MIN_N Fällen. Die Wahrscheinlichkeiten
#: des Modells sind wegen class_weight="balanced" nicht kalibriert — deshalb nennt die Warnung gezählte Quoten, nicht P(ok).
WARN_PRAEZISION = 0.5
WARN_MIN_N = 10
EPSILON = 0.1
#: Bedeutungsnähe und Inhaltsgruppe als Merkmale (inhalt.py). Abschaltbar, um den Unterschied zu messen.
INHALT = True
HOLDOUT = 0.2
#: 0.20.9: Das Holdout (zeitlich jüngster Teil) wächst bis HOLDOUT_MAX, bis es mindestens so viele Fehlschläge enthält. Am 09.11. fiel die
#: Holdout-AUC von 0,92 auf 0,70, als die jüngsten 20 % fast nur aus gelungenen Bash-Aufrufen bestanden (9 Fehlschläge in 230 Handlungen).
HOLDOUT_MAX = 0.5
HOLDOUT_MIN_FEHLER = 30
REIZ_ARTEN = ("tool:", "skill:", "host:", "thema:")


def merkmale_handlung(reize: list[str], zeit: str) -> dict:
    m = {t: 1.0 for t in reize if t.startswith(REIZ_ARTEN)}
    m[f"stunde:{zeit[11:13]}"] = 1.0
    return m


def merkmale_hinweis(hid: str, reize: list[str] | None = None) -> dict:
    m = {f"hinweis:{hid}": 1.0, f"hinweisart:{hid.split(':')[0]}": 1.0}
    if INHALT:
        from . import inhalt
        if (c := inhalt.gruppe(hid)) is not None:
            m[f"inhalt:{c}"] = 1.0
        if reize and (n := inhalt.naehe(hid, [r for r in reize if r.startswith(REIZ_ARTEN)])) is not None:
            m["naehe"] = n
    return m


def beobachtungen(seit: str | None = None) -> list[tuple[dict, int, str]]:
    """(Merkmale, ok, erfahrung_id) je gemeldeter Handlung mit Label; aus dem Gedächtnis beantwortete fallen weg.
    Ein Beispiel je gezeigtem Hinweis (Paar) plus eines ohne Hinweis-Merkmale (Basis) — so lernt das Modell beides."""
    aus = []
    with g.sperre:
        rows = g.db().execute("SELECT id, zeit, daten, gespraech FROM objekt WHERE art = 'erfahrung' AND modus = 'aktiv'" + (" AND zeit >= ?" if seit else "") + " ORDER BY zeit",
                              (seit,) if seit else ()).fetchall()
        gelabelt = {r[0] for r in g.db().execute("SELECT DISTINCT objekt_id FROM tag WHERE tag IN ('ok:ja', 'ok:nein')")}
        okja = {r[0] for r in g.db().execute("SELECT objekt_id FROM tag WHERE tag = 'ok:ja'")}
    from . import scorer
    noten = scorer.gespraech_noten()
    for oid, zeit, daten, serial in rows:
        if oid not in gelabelt:
            continue
        d = json.loads(daten)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        s = d.get("score")  # Label: Urteil des Scorers, sonst „Werkzeug ohne Fehler“; eine schlechte Gesprächsnote gilt für alle Handlungen
        y = (1 if s["note"] >= scorer.GUT_AB else 0) if s else (1 if oid in okja else 0)
        if serial in noten and noten[serial] < scorer.SCHLECHT_UNTER:
            y = 0
        basis = merkmale_handlung(v.get("reize", []), zeit)
        gezeigt = [h for h in v.get("gezeigt", v.get("gefunden", [])) if not h.startswith("antwort:")]
        basis[f"hinweis_n:{min(4, len(gezeigt))}"] = 1.0
        if not gezeigt:
            aus.append((basis, y, oid))
        rm = d.get("rueckmeldung") or {}  # 0.20.9: direkte Rückmeldung (vi_bestaetige/vi_widerlege) ersetzt das indirekte Label des Paares
        for h in gezeigt:
            aus.append(({**basis, **merkmale_hinweis(h, v.get("reize", []))}, (1 if rm[h] > 0 else 0) if h in rm else y, oid))
    return aus


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def modell() -> g.Objekt | None:
    return g.lade(MODELL)


def vorhersage(m: g.Objekt, merkmale: dict) -> float:
    """P(ok | Merkmale) aus den gespeicherten Gewichten — reine Standardbibliothek."""
    w = m.daten["gewichte"]
    return _sigmoid(m.daten["achsenabschnitt"] + sum(w.get(k, 0.0) * v for k, v in merkmale.items()))


def rangfolge(m: g.Objekt, reize: list[str], kandidaten: list[str], zeit: str | None = None) -> list[tuple[str, float]]:
    """Kandidaten nach erwartetem Lift (absteigend). Unbekannte Hinweise haben Lift 0 (nur ihre Art zählt)."""
    basis = merkmale_handlung(reize, zeit or g.jetzt())
    mit = {**basis, "hinweis_n:1": 1.0}
    p0 = vorhersage(m, {**basis, "hinweis_n:0": 1.0})
    return sorted(((h, vorhersage(m, {**mit, **merkmale_hinweis(h, reize)}) - p0) for h in kandidaten), key=lambda x: -x[1])


def aktiv() -> g.Objekt | None:
    m = modell()
    return m if m and m.modus == "aktiv" else None


def trainiere(grund: str = "Schlaf") -> dict:
    """Mit scikit-learn trainieren, Gewichte als JSON speichern. Liefert den Bericht (auch bei Verzicht, benannt)."""
    try:
        import numpy as np
        from sklearn import __version__ as skv
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
    except ImportError as e:
        return {"zustand": "uebersprungen", "grund": f"scikit-learn fehlt ({e.name}) — python3-sklearn installieren"}
    beob = beobachtungen()
    if not beob:
        return {"zustand": "zu_wenig_daten", "grund": "keine Beobachtungen mit Label", "n": 0}
    zaehl: dict[str, int] = {}
    for m, _y, _o in beob:
        for k in m:
            zaehl[k] = zaehl.get(k, 0) + 1
    behalten = {k for k, n in zaehl.items() if n >= MIN_JE_MERKMAL}
    X_d = [{k: v for k, v in m.items() if k in behalten} for m, _y, _o in beob]
    y = np.array([yy for _m, yy, _o in beob])
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    bericht = {"n": len(beob), "ok": n_pos, "nicht_ok": n_neg, "merkmale": len(behalten), "verworfen": len(zaehl) - len(behalten),
               "sklearn": skv, "trainiert": g.jetzt(), "grund": grund}
    if min(n_pos, n_neg) < MIN_EREIGNISSE or not behalten:
        bericht.update(zustand="zu_wenig_daten", urteil=f"min(ok, nicht ok) = {min(n_pos, n_neg)} < {MIN_EREIGNISSE} oder keine Merkmale ≥ {MIN_JE_MERKMAL}")
        _speichere(bericht, {}, 0.0, "test")
        return bericht
    # zeitliche Teilung: Älteres lernt, Neueres prüft (kein Blick in die Zukunft)
    n_test = _holdout_groesse([yy for _m, yy, _o in beob])
    vec = DictVectorizer(sparse=True)
    X = vec.fit_transform(X_d)
    Xtr, Xte, ytr, yte = X[:-n_test], X[-n_test:], y[:-n_test], y[-n_test:]
    clf = LogisticRegression(class_weight="balanced", C=1.0, max_iter=1000)
    clf.fit(Xtr, ytr)
    auc = float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])) if len(set(yte.tolist())) == 2 else None
    gewichte = {name: round(float(w), 4) for name, w in zip(vec.get_feature_names_out(), clf.coef_[0]) if abs(w) > 1e-6}
    bericht.update(auc_holdout=None if auc is None else round(auc, 3), holdout=n_test, holdout_fehler=int(len(yte) - yte.sum()),
                   rueckmeldungen=sum(len((json.loads(r[0]) or {}).get("rueckmeldung") or {}) for r in _rueckmeldungen()))
    if auc is None or auc <= AUC_MIN:
        bericht.update(zustand="test", urteil=f"Holdout-AUC {auc} ≤ {AUC_MIN} oder nicht bestimmbar — Modell gespeichert, Router bleibt Heuristik")
        modus = "test"
    else:
        bericht.update(zustand="aktiv", urteil=f"Holdout-AUC {auc:.3f} > {AUC_MIN} — Router nutzt das Modell")
        modus = "aktiv"
    bericht["warnung"] = _warnschwelle(clf, vec, beob[-n_test:]) if modus == "aktiv" else {"zustand": "aus", "grund": "Modell nicht aktiv"}
    bericht["quoten"] = _quoten(beob, behalten)
    _speichere(bericht, gewichte, float(clf.intercept_[0]), modus)
    log(f"Lernen: {bericht['zustand']} — n {len(beob)}, Merkmale {len(behalten)}, AUC {bericht.get('auc_holdout')}, "
        f"Warnung {bericht['warnung'].get('zustand')}")
    return bericht


def _holdout_groesse(y: list[int]) -> int:
    """Jüngster Teil der Daten als Holdout: HOLDOUT, vergrößert in 5-%-Schritten bis HOLDOUT_MAX, bis er HOLDOUT_MIN_FEHLER Fehlschläge hat."""
    n = len(y)
    anteil = HOLDOUT
    while anteil < HOLDOUT_MAX and (len(y[-max(1, int(n * anteil)):]) - sum(y[-max(1, int(n * anteil)):])) < HOLDOUT_MIN_FEHLER:
        anteil = round(anteil + 0.05, 2)
    return max(1, int(n * anteil))


def _rueckmeldungen() -> list:
    with g.sperre:
        return g.db().execute("SELECT daten FROM objekt WHERE art = 'erfahrung' AND daten LIKE '%\"rueckmeldung\"%'").fetchall()


def _basis(m: dict) -> dict:
    """Nur die Lage der Handlung (ohne Hinweise) — so, wie vi_vorher sie vor dem Zeigen kennt."""
    return {**{k: v for k, v in m.items() if k.startswith(REIZ_ARTEN + ("stunde:",))}, "hinweis_n:0": 1.0}


def _je_erfahrung(beob: list) -> list[tuple[dict, int]]:
    gesehen, aus = set(), []
    for m, y, oid in beob:
        if oid not in gesehen:
            gesehen.add(oid)
            aus.append((_basis(m), y))
    return aus


def _quoten(beob: list, behalten: set) -> dict:
    """[Handlungen, gescheitert] je Situationsmerkmal, je Erfahrung einmal gezählt; „_gesamt“ für alle."""
    q: dict[str, list[int]] = {"_gesamt": [0, 0]}
    for b, y in _je_erfahrung(beob):
        for k in ["_gesamt"] + [k for k in b if k in behalten and k.startswith(REIZ_ARTEN)]:
            e = q.setdefault(k, [0, 0])
            e[0] += 1
            e[1] += 1 - y
    return q


def _warnschwelle(clf, vec, holdout: list) -> dict:
    """Größte Schwelle t, bei der im Holdout von den Handlungen mit P(ok) ≤ t mindestens WARN_PRAEZISION scheiterten (≥ WARN_MIN_N Fälle)."""
    faelle = _je_erfahrung(holdout)
    if not faelle:
        return {"zustand": "aus", "grund": "kein Holdout"}
    p = clf.predict_proba(vec.transform([b for b, _y in faelle]))[:, 1]
    paare = sorted(zip(p.tolist(), [y for _b, y in faelle]))
    gescheitert_ges = sum(1 - y for _p, y in paare)
    best, n, f = None, 0, 0
    for i, (pp, y) in enumerate(paare):
        n, f = i + 1, f + (1 - y)
        if n >= WARN_MIN_N and f / n >= WARN_PRAEZISION and (i + 1 == len(paare) or paare[i + 1][0] > pp):
            best = {"schwelle": round(pp, 4), "gewarnt": n, "scheiterten": f}
    if not best:
        return {"zustand": "aus", "grund": f"keine Schwelle mit ≥ {WARN_MIN_N} Fällen und ≥ {int(WARN_PRAEZISION * 100)} % gescheitert im Holdout"}
    return {"zustand": "aktiv", **best, "praezision_pct": round(100 * best["scheiterten"] / best["gewarnt"]),
            "abdeckung_pct": round(100 * best["scheiterten"] / gescheitert_ges) if gescheitert_ges else 0, "holdout_handlungen": len(paare)}


def warnung(reize: list[str], zeit: str | None = None) -> str | None:
    """Warnung vor einer riskanten Handlung — nur bei aktivem Modell und aktiver Schwelle, nur mit benennbarem Grund (gezählte Quote)."""
    m = aktiv()
    w = (m.daten.get("warnung") or {}) if m else {}
    if w.get("zustand") != "aktiv":
        return None
    basis = _basis(merkmale_handlung(reize, zeit or g.jetzt()))
    if vorhersage(m, basis) > w["schwelle"]:
        return None
    q, gw = m.daten.get("quoten") or {}, m.daten.get("gewichte") or {}
    ges = q.get("_gesamt") or [1, 0]
    rate_ges = ges[1] / max(1, ges[0])
    gruende = sorted((k for k in basis if gw.get(k, 0.0) < 0 and k in q and q[k][1] / max(1, q[k][0]) > rate_ges), key=lambda k: gw[k])[:3]
    if not gruende:
        return None  # ohne benennbaren Grund keine Warnung
    teile = "; ".join(f"{k}: {q[k][1]} von {q[k][0]} Handlungen scheiterten ({round(100 * q[k][1] / q[k][0])} %)" for k in gruende)
    return (f"[VI-Warnung] Handlungen wie diese scheitern oft — {teile}; insgesamt {round(100 * rate_ges)} %. Im Test scheiterten "
            f"{w['scheiterten']} von {w['gewarnt']} so eingestuften Handlungen ({w['praezision_pct']} %). Vorher Argumente, Pfade und Erreichbarkeit prüfen.")


def _speichere(bericht: dict, gewichte: dict, achsenabschnitt: float, modus: str) -> g.Objekt:
    m = g.lade(MODELL)
    daten = {**bericht, "gewichte": gewichte, "achsenabschnitt": round(achsenabschnitt, 4)}
    text = (f"Router-Modell ({bericht.get('zustand')}): {bericht.get('n', 0)} Beobachtungen, {bericht.get('merkmale', 0)} Merkmale, "
            f"AUC {bericht.get('auc_holdout', '—')} — {bericht.get('urteil', bericht.get('grund', ''))}")
    if m is None:
        return g.neues_objekt("modell", text, ["modell:router"], daten, wichtigkeit=2, wer="vi", oid=MODELL,
                              modus=modus, grund=bericht.get("grund", "Lernen"), instanz=g.SERVER_INSTANZ)
    m.text, m.daten, m.modus = text, {**daten, "versionen": m.daten.get("versionen", 0) + 1}, modus
    m.aendere("vi", f"neu trainiert → {modus}", bericht.get("grund", "Lernen"))
    return g.speichere(m)


def erklaerung(limit: int = 12) -> str:
    m = modell()
    if not m:
        return "noch kein Router-Modell — entsteht im Schlaf, sobald genug Beobachtungen vorliegen (Router: Heuristik)"
    d = m.daten
    z = [m.text, f"  trainiert {str(d.get('trainiert', '—'))[:16]} · sklearn {d.get('sklearn', '—')} · ok {d.get('ok', 0)} / nicht ok {d.get('nicht_ok', 0)} "
                 f"· Merkmale {d.get('merkmale', 0)} (verworfen {d.get('verworfen', 0)}: < {MIN_JE_MERKMAL} Vorkommen) · Holdout {d.get('holdout', 0)} "
                 f"({d.get('holdout_fehler', '—')} Fehlschläge) · direkte Rückmeldungen zu Hinweisen {d.get('rueckmeldungen', 0)}"]
    w = sorted(d.get("gewichte", {}).items(), key=lambda kv: -abs(kv[1]))[:limit]
    if w:
        z.append("  stärkste Gewichte (positiv = erhöht P(ok)):")
        from . import inhalt
        z += [f"    {k:50} {v:+.3f}" + (f"  ({inhalt.gruppen_name(int(k[7:]))})" if k.startswith("inhalt:") and k[7:].isdigit() else "")
              + ("  (Bedeutungsnähe Hinweis ↔ Situation, 0–1)" if k == "naehe" else "") for k, v in w]
    w = d.get("warnung") or {}
    z.append("  Warnung vor riskanten Handlungen: " + (f"aktiv — Schwelle P ≤ {w['schwelle']}, im Holdout scheiterten {w['scheiterten']} von "
             f"{w['gewarnt']} gewarnten ({w['praezision_pct']} %), erfasst {w['abdeckung_pct']} % aller Fehlschläge"
             if w.get("zustand") == "aktiv" else f"aus — {w.get('grund', 'noch nicht trainiert')}"))
    if INHALT:
        from . import inhalt
        z.append(f"  Inhalt: {inhalt.zeile()}")
    return "\n".join(z)
