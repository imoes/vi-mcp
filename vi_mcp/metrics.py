"""Messpunkte — woran man merkt, ob die VI nützt.

Hinweis-Lift: Erfolgsquote von Handlungen, vor denen das Gedächtnis etwas gezeigt hat (Erkenntnis, Regel, gelernte
Suche), gegenüber Handlungen ohne Hinweis. Steigt sie nicht, ist die Annahme „Hinweise nützen“ falsch
(docs/ARCHITEKTUR.md, „Verstärkt wird erst beim Erfolg“). Aus dem Gedächtnis beantwortete Aufrufe zählen nicht
(sie hatten keine Handlung). Unter MINDESTENS Fällen je Seite heißt das Ergebnis „zu wenig Daten“ — benannt, kein Limbo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import memory as g

AT_LEAST = 10


def _with_hint(o: g.MemoryObject) -> bool:
    v = o.data.get("vorher") or {}
    return any(not oid.startswith("antwort:") for oid in v.get("gefunden", []))


def hint_lift(hours: float = 24, tool: str | None = None, viewer: str | None = None) -> dict:
    """{'mit': {'n', 'ok'}, 'ohne': {'n', 'ok'}, 'quote_mit', 'quote_ohne', 'lift', 'urteil', 'je_tool': {...}}"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    filt = "art:erfahrung (ok:ja OR ok:nein)" + (f" tool:{tool}" if tool else "")
    per_tool: dict[str, dict] = {}
    total = {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}}
    for _, o, _g in g.recall(filt, limit=5000, viewer=viewer):
        if o.ts < since or (o.data.get("vorher") or {}).get("aus_gedaechtnis"):
            continue
        t = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        page = "mit" if _with_hint(o) else "ohne"
        s = o.data.get("score")  # das Urteil des Scorers schlägt „Werkzeug ohne Fehler“
        ok = s["note"] >= 0.5 if s else "ok:ja" in o.hashtags
        for target in (total, per_tool.setdefault(t, {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}})):
            target[page]["n"] += 1
            target[page]["ok"] += 1 if ok else 0
    return {**total, **_rate(total), "je_tool": {t: {**d, **_rate(d)} for t, d in per_tool.items()}, "stunden": hours}


def _rate(d: dict) -> dict:
    qm = d["mit"]["ok"] / d["mit"]["n"] if d["mit"]["n"] else None
    qo = d["ohne"]["ok"] / d["ohne"]["n"] if d["ohne"]["n"] else None
    if d["mit"]["n"] < AT_LEAST or d["ohne"]["n"] < AT_LEAST:
        verdict = f"zu wenig Daten (mindestens {AT_LEAST} je Seite)"
    elif qm > qo + 0.05:
        verdict = "Hinweise nützen"
    elif qm < qo - 0.05:
        verdict = "Hinweise schaden — Annahme widerlegt, Gewichtung prüfen"
    else:
        verdict = "kein messbarer Unterschied"
    return {"quote_mit": qm, "quote_ohne": qo, "lift": (qm - qo) if qm is not None and qo is not None else None, "urteil": verdict}


def line(l: dict) -> str:
    f = lambda q: "—" if q is None else f"{q * 100:.0f} %"
    return (f"Hinweis-Lift {l['stunden']:g} h: mit Hinweis {l['mit']['ok']}/{l['mit']['n']} ok ({f(l['quote_mit'])}), "
            f"ohne {l['ohne']['ok']}/{l['ohne']['n']} ok ({f(l['quote_ohne'])})"
            + (f", Lift {l['lift'] * 100:+.0f} Punkte" if l["lift"] is not None else "") + f" → {l['urteil']}")
