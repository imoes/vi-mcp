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

from . import memory as g

HINT_KINDS = ("erkenntnis:", "regel:", "suche:", "skill:")


BASE_DAYS = 90
BASE_MIN = 10
METHOD_ID = "vorteil-v1"
_reason: dict = {"zeit": 0.0, "je": {}, "alle": 0.5}


def counter(o: g.MemoryObject) -> tuple[float, float]:
    n = o.data.get("nuetzlich") or {}
    return round(float(n.get("ja", 0)), 3), round(float(n.get("nein", 0)), 3)


def shown(o: g.MemoryObject) -> int:
    return int((o.data.get("nuetzlich") or {}).get("n", 0))


def _observations(since: str | None = None):
    """(tool, ok, gezeigt) je bewerteter Handlung; das Urteil des Scorers schlägt „Werkzeug ohne Fehler“, aus dem Gedächtnis Beantwortetes zählt nicht."""
    from .scorer import GOOD_FROM
    with g.lock:
        lines = g.db().execute("SELECT o.daten, (SELECT group_concat(tag, ' ') FROM tag t WHERE t.objekt_id = o.id AND (t.tag LIKE 'tool:%' OR t.tag LIKE 'ok:%')) "
                                "FROM objekt o WHERE o.art = 'erfahrung' AND o.modus = 'aktiv'" + (" AND o.zeit >= ?" if since else ""), (since,) if since else ()).fetchall()
    for data, tags in lines:
        tags = (tags or "").split()
        d = json.loads(data)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        s = d.get("score")
        ok = (s["note"] >= GOOD_FROM) if s else (True if "ok:ja" in tags else False if "ok:nein" in tags else None)
        tool = next((t[5:] for t in tags if t.startswith("tool:")), None)
        if ok is None or not tool:
            continue
        yield tool, ok, [h for h in v.get("gezeigt", []) if h.startswith(HINT_KINDS)]


def _base_rates() -> tuple[dict[str, float], float]:
    """Erfolgsquote je Werkzeug aus Handlungen ohne gezeigten Hinweis; zu wenige → alle Handlungen des Werkzeugs; nichts → über alles. Laplace-geglättet."""
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - BASE_DAYS * 86400))
    without, all_ = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for tool, ok, shown_flag in _observations(since):
        for d in ((all_,) if shown_flag else (all_, without)):
            d[tool][0] += ok
            d[tool][1] += 1
    per_tool_rate = {t: (z[0] + 1) / (z[1] + 2) for t, z in all_.items()}
    per_tool_rate.update({t: (z[0] + 1) / (z[1] + 2) for t, z in without.items() if z[1] >= BASE_MIN})
    total = [sum(z[0] for z in all_.values()), sum(z[1] for z in all_.values())]
    return per_tool_rate, (total[0] + 1) / (total[1] + 2)


def base_rate(tool: str) -> float:
    if time.time() - _reason["zeit"] > 300:
        per_tool_rate, all_ = _base_rates()
        _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_)
    return _reason["je"].get(tool, _reason["alle"])


def recompute() -> dict:
    """Schlaf: alle Hinweis-Zähler aus den Erfahrungen. Hinweise ohne bewertete Handlung verlieren alte Zähler."""
    per_tool_rate, all_ = _base_rates()
    _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_)
    sum_total: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0, 0, 0.0])  # ja, nein, gezeigt, gelungen, erwartet
    for tool, ok, shown_flag in _observations():
        p = per_tool_rate.get(tool, all_)
        for h in shown_flag:
            z = sum_total[h]
            if ok:
                z[0] += 1 - p
            else:
                z[1] += p
            z[2] += 1
            z[3] += ok
            z[4] += p
    with g.lock:
        old = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE json_extract(daten, '$.nuetzlich') IS NOT NULL")]
        g.db().executemany("UPDATE objekt SET daten = json_remove(daten, '$.nuetzlich') WHERE id = ?", [(i,) for i in old if i not in sum_total])
        g.db().executemany("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich', json(?)) WHERE id = ?",
                           [(json.dumps({"ja": round(a, 4), "nein": round(b, 4), "n": n, "ok": k, "erwartet": round(e, 4), "verfahren": METHOD_ID}), h) for h, (a, b, n, k, e) in sum_total.items()])
        g.db().commit()
    return {"hinweise": len(sum_total), "zurueckgesetzt": len([i for i in old if i not in sum_total]), "grundraten": {t: round(p, 3) for t, p in sorted(per_tool_rate.items(), key=lambda x: -x[1])[:8]}}


def random_sample(o: g.MemoryObject, rnd: random.Random | None = None) -> float:
    yes, no = counter(o)
    return (rnd or random).betavariate(1 + yes, 1 + no)


def expectation(o: g.MemoryObject) -> float:
    yes, no = counter(o)
    return (1 + yes) / (2 + yes + no)


def has_counter(candidates: list[g.MemoryObject]) -> bool:
    return any(sum(counter(o)) > 0 for o in candidates)


def arrange(candidates: list[g.MemoryObject], rnd: random.Random | None = None) -> list[g.MemoryObject]:
    """Thompson Sampling: eine Stichprobe je Kandidat, absteigend. Stabil bei Gleichstand (Heuristik-Reihenfolge)."""
    samples = {o.id: random_sample(o, rnd) for o in candidates}
    return sorted(candidates, key=lambda o: -samples[o.id])


def book_entry(shown: list[str], ok: bool | None, tool: str | None = None) -> int:
    """Nach der Handlung: Vorteil gegenüber der Grundrate je gezeigtem Hinweis. ok None (kein Ergebnis gemeldet) zählt nicht. Atomar in der DB."""
    if ok is None:
        return 0
    p = base_rate(tool) if tool else _reason["alle"]
    field_name, value = ("ja", 1 - p) if ok else ("nein", p)
    n = 0
    plus_ok = 1 if ok else 0
    with g.lock:
        for oid in shown:
            if not oid.startswith(HINT_KINDS):
                continue
            # JSON-Zähler in daten relativ erhöhen — kein Lesen-Ändern-Schreiben über die Objekt-Klasse (kein verlorener Zähler)
            # zuletzt_gezeigt zählt fürs Housekeeping als Verwendung, verändert aber die Aktualität nicht (kein Matthäus-Effekt)
            cur = g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.' || ?, "
                                 "COALESCE(json_extract(daten, '$.nuetzlich.' || ?), 0) + ?, '$.nuetzlich.n', COALESCE(json_extract(daten, '$.nuetzlich.n'), 0) + 1, "
                                 "'$.nuetzlich.ok', COALESCE(json_extract(daten, '$.nuetzlich.ok'), 0) + ?, '$.nuetzlich.erwartet', COALESCE(json_extract(daten, '$.nuetzlich.erwartet'), 0) + ?, "
                                 "'$.zuletzt_gezeigt', ?) WHERE id = ?", (field_name, field_name, value, plus_ok, p, g.now(), oid))
            n += cur.rowcount
        g.db().commit()
    return n


def rebook(shown: list[str], tool: str | None = None) -> int:
    """Der Scorer stellt nachträglich fest, dass eine als gelungen gezählte Handlung misslungen ist: die Gutschrift (1 − p) geht zurück, p kommt als Nein dazu."""
    p = base_rate(tool) if tool else _reason["alle"]
    n = 0
    with g.lock:
        for oid in shown:
            if oid.startswith(HINT_KINDS):
                n += g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.ja', max(COALESCE(json_extract(daten, '$.nuetzlich.ja'), 0) - ?, 0), "
                                    "'$.nuetzlich.nein', COALESCE(json_extract(daten, '$.nuetzlich.nein'), 0) + ?) WHERE id = ?", (1 - p, p, oid)).rowcount
        g.db().commit()
    return n


def lift(o: g.MemoryObject) -> float | None:
    """Erfolgsquote nach dem Zeigen minus erwartete Quote des Werkzeugs, in Anteilen; None ohne Daten."""
    z = o.data.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    return (z.get("ok", 0) - z.get("erwartet", 0)) / n if n and "erwartet" in z else None


def line(o: g.MemoryObject) -> str:
    z = o.data.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    if not n:
        return "noch nie nach dem Zeigen bewertet"
    if "erwartet" not in z:
        return f"{n}× gezeigt, Wirkung noch nicht berechnet"
    return f"{n}× gezeigt, Erfolg danach {z['ok'] / n * 100:.0f} % statt erwartet {z['erwartet'] / n * 100:.0f} % ({lift(o) * 100:+.0f} Punkte)"
