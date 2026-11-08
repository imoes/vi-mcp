"""Bandit — Thompson Sampling je Hinweis (Stufe 2, docs/TRAINING.md 4b), gemessen am Vorteil gegenüber dem Werkzeug ohne Hinweis.

Jeder Hinweis führt `daten.nuetzlich = {"ja": a, "nein": b, "n": gezeigt}`. Gutgeschrieben wird nicht jeder Erfolg nach dem Zeigen, sondern nur, was über
das Erwartbare hinausgeht: p = Erfolgsquote des Werkzeugs ohne Hinweis (grundrate); Erfolg → a += 1 − p, Misserfolg → b += p.
Ein wirkungsloser Hinweis bleibt so im Erwartungswert bei a ≈ b, also bei 50 %; früher stieg er mit der Erfolgsquote des Werkzeugs (Nachbarschaft ist keine
Ursache: gemessen 08.11.2026, ein inhaltsleerer Skill vor Bash „226-mal genützt“). Beim Ordnen zieht der Router je Hinweis eine Stichprobe aus
Beta(1 + a, 1 + b) — selten gezeigte Hinweise haben breite Verteilungen und kommen von selbst wieder dran (Russo et al. 2017, arXiv 1707.02038).
Die Zähler sind abgeleitet: Der Schlaf berechnet sie aus den gespeicherten Erfahrungen neu (`neu_berechnen`), live wird nur fortgeschrieben.

Rangordnung des Routers (erschöpfend, in `zugriff.router` benannt):
  modell     — das gelernte Modell ist aktiv (Stufe 1, Lift)
  bandit     — kein aktives Modell, aber mindestens ein Kandidat hat schon Zähler
  heuristik  — weder noch: Aktualität + Wichtigkeit + Bonus
"""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict

from . import gedaechtnis as g

HINWEIS_ARTEN = ("erkenntnis:", "regel:", "suche:", "skill:")


GRUND_TAGE = 90
GRUND_MIN = 10
VERFAHREN = "vorteil-v1"
_grund: dict = {"zeit": 0.0, "je": {}, "alle": 0.5}


def zaehler(o: g.Objekt) -> tuple[float, float]:
    n = o.daten.get("nuetzlich") or {}
    return round(float(n.get("ja", 0)), 3), round(float(n.get("nein", 0)), 3)


def gezeigt(o: g.Objekt) -> int:
    return int((o.daten.get("nuetzlich") or {}).get("n", 0))


def _beobachtungen(seit: str | None = None):
    """(tool, ok, gezeigt) je bewerteter Handlung; das Urteil des Scorers schlägt „Werkzeug ohne Fehler“, aus dem Gedächtnis Beantwortetes zählt nicht."""
    from .scorer import GUT_AB
    with g.sperre:
        zeilen = g.db().execute("SELECT o.daten, (SELECT group_concat(tag, ' ') FROM tag t WHERE t.objekt_id = o.id AND (t.tag LIKE 'tool:%' OR t.tag LIKE 'ok:%')) "
                                "FROM objekt o WHERE o.art = 'erfahrung' AND o.modus = 'aktiv'" + (" AND o.zeit >= ?" if seit else ""), (seit,) if seit else ()).fetchall()
    for daten, tags in zeilen:
        tags = (tags or "").split()
        d = json.loads(daten)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        s = d.get("score")
        ok = (s["note"] >= GUT_AB) if s else (True if "ok:ja" in tags else False if "ok:nein" in tags else None)
        tool = next((t[5:] for t in tags if t.startswith("tool:")), None)
        if ok is None or not tool:
            continue
        yield tool, ok, [h for h in v.get("gezeigt", []) if h.startswith(HINWEIS_ARTEN)]


def _grundraten() -> tuple[dict[str, float], float]:
    """Erfolgsquote je Werkzeug aus Handlungen ohne gezeigten Hinweis; zu wenige → alle Handlungen des Werkzeugs; nichts → über alles. Laplace-geglättet."""
    seit = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - GRUND_TAGE * 86400))
    ohne, alle = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for tool, ok, gez in _beobachtungen(seit):
        for d in ((alle,) if gez else (alle, ohne)):
            d[tool][0] += ok
            d[tool][1] += 1
    je = {t: (z[0] + 1) / (z[1] + 2) for t, z in alle.items()}
    je.update({t: (z[0] + 1) / (z[1] + 2) for t, z in ohne.items() if z[1] >= GRUND_MIN})
    gesamt = [sum(z[0] for z in alle.values()), sum(z[1] for z in alle.values())]
    return je, (gesamt[0] + 1) / (gesamt[1] + 2)


def grundrate(tool: str) -> float:
    if time.time() - _grund["zeit"] > 300:
        je, alle = _grundraten()
        _grund.update(zeit=time.time(), je=je, alle=alle)
    return _grund["je"].get(tool, _grund["alle"])


def neu_berechnen() -> dict:
    """Schlaf: alle Hinweis-Zähler aus den Erfahrungen. Hinweise ohne bewertete Handlung verlieren alte Zähler."""
    je, alle = _grundraten()
    _grund.update(zeit=time.time(), je=je, alle=alle)
    summe: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0, 0, 0.0])  # ja, nein, gezeigt, gelungen, erwartet
    for tool, ok, gez in _beobachtungen():
        p = je.get(tool, alle)
        for h in gez:
            z = summe[h]
            if ok:
                z[0] += 1 - p
            else:
                z[1] += p
            z[2] += 1
            z[3] += ok
            z[4] += p
    with g.sperre:
        alt = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE json_extract(daten, '$.nuetzlich') IS NOT NULL")]
        g.db().executemany("UPDATE objekt SET daten = json_remove(daten, '$.nuetzlich') WHERE id = ?", [(i,) for i in alt if i not in summe])
        g.db().executemany("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich', json(?)) WHERE id = ?",
                           [(json.dumps({"ja": round(a, 4), "nein": round(b, 4), "n": n, "ok": k, "erwartet": round(e, 4), "verfahren": VERFAHREN}), h) for h, (a, b, n, k, e) in summe.items()])
        g.db().commit()
    return {"hinweise": len(summe), "zurueckgesetzt": len([i for i in alt if i not in summe]), "grundraten": {t: round(p, 3) for t, p in sorted(je.items(), key=lambda x: -x[1])[:8]}}


def stichprobe(o: g.Objekt, rnd: random.Random | None = None) -> float:
    ja, nein = zaehler(o)
    return (rnd or random).betavariate(1 + ja, 1 + nein)


def erwartung(o: g.Objekt) -> float:
    ja, nein = zaehler(o)
    return (1 + ja) / (2 + ja + nein)


def hat_zaehler(kandidaten: list[g.Objekt]) -> bool:
    return any(sum(zaehler(o)) > 0 for o in kandidaten)


def ordne(kandidaten: list[g.Objekt], rnd: random.Random | None = None) -> list[g.Objekt]:
    """Thompson Sampling: eine Stichprobe je Kandidat, absteigend. Stabil bei Gleichstand (Heuristik-Reihenfolge)."""
    proben = {o.id: stichprobe(o, rnd) for o in kandidaten}
    return sorted(kandidaten, key=lambda o: -proben[o.id])


def verbuche(gezeigt: list[str], ok: bool | None, tool: str | None = None) -> int:
    """Nach der Handlung: Vorteil gegenüber der Grundrate je gezeigtem Hinweis. ok None (kein Ergebnis gemeldet) zählt nicht. Atomar in der DB."""
    if ok is None:
        return 0
    p = grundrate(tool) if tool else _grund["alle"]
    feld, wert = ("ja", 1 - p) if ok else ("nein", p)
    n = 0
    plus_ok = 1 if ok else 0
    with g.sperre:
        for oid in gezeigt:
            if not oid.startswith(HINWEIS_ARTEN):
                continue
            # JSON-Zähler in daten relativ erhöhen — kein Lesen-Ändern-Schreiben über die Objekt-Klasse (kein verlorener Zähler)
            # zuletzt_gezeigt zählt fürs Housekeeping als Verwendung, verändert aber die Aktualität nicht (kein Matthäus-Effekt)
            cur = g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.' || ?, "
                                 "COALESCE(json_extract(daten, '$.nuetzlich.' || ?), 0) + ?, '$.nuetzlich.n', COALESCE(json_extract(daten, '$.nuetzlich.n'), 0) + 1, "
                                 "'$.nuetzlich.ok', COALESCE(json_extract(daten, '$.nuetzlich.ok'), 0) + ?, '$.nuetzlich.erwartet', COALESCE(json_extract(daten, '$.nuetzlich.erwartet'), 0) + ?, "
                                 "'$.zuletzt_gezeigt', ?) WHERE id = ?", (feld, feld, wert, plus_ok, p, g.jetzt(), oid))
            n += cur.rowcount
        g.db().commit()
    return n


def umbuchen(gezeigt: list[str], tool: str | None = None) -> int:
    """Der Scorer stellt nachträglich fest, dass eine als gelungen gezählte Handlung misslungen ist: die Gutschrift (1 − p) geht zurück, p kommt als Nein dazu."""
    p = grundrate(tool) if tool else _grund["alle"]
    n = 0
    with g.sperre:
        for oid in gezeigt:
            if oid.startswith(HINWEIS_ARTEN):
                n += g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.ja', max(COALESCE(json_extract(daten, '$.nuetzlich.ja'), 0) - ?, 0), "
                                    "'$.nuetzlich.nein', COALESCE(json_extract(daten, '$.nuetzlich.nein'), 0) + ?) WHERE id = ?", (1 - p, p, oid)).rowcount
        g.db().commit()
    return n


def lift(o: g.Objekt) -> float | None:
    """Erfolgsquote nach dem Zeigen minus erwartete Quote des Werkzeugs, in Anteilen; None ohne Daten."""
    z = o.daten.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    return (z.get("ok", 0) - z.get("erwartet", 0)) / n if n and "erwartet" in z else None


def zeile(o: g.Objekt) -> str:
    z = o.daten.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    if not n:
        return "noch nie nach dem Zeigen bewertet"
    if "erwartet" not in z:
        return f"{n}× gezeigt, Wirkung noch nicht berechnet"
    return f"{n}× gezeigt, Erfolg danach {z['ok'] / n * 100:.0f} % statt erwartet {z['erwartet'] / n * 100:.0f} % ({lift(o) * 100:+.0f} Punkte)"
