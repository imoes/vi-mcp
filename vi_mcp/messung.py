"""Messpunkte — woran man merkt, ob die VI nützt.

Hinweis-Lift: Erfolgsquote von Handlungen, vor denen das Gedächtnis etwas gezeigt hat (Erkenntnis, Regel, gelernte
Suche), gegenüber Handlungen ohne Hinweis. Steigt sie nicht, ist die Annahme „Hinweise nützen“ falsch
(docs/ARCHITEKTUR.md, „Verstärkt wird erst beim Erfolg“). Aus dem Gedächtnis beantwortete Aufrufe zählen nicht
(sie hatten keine Handlung). Unter MINDESTENS Fällen je Seite heißt das Ergebnis „zu wenig Daten“ — benannt, kein Limbo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import gedaechtnis as g

MINDESTENS = 10


def _mit_hinweis(o: g.Objekt) -> bool:
    v = o.daten.get("vorher") or {}
    return any(not oid.startswith("antwort:") for oid in v.get("gefunden", []))


def hinweis_lift(stunden: float = 24, tool: str | None = None, betrachter: str | None = None) -> dict:
    """{'mit': {'n', 'ok'}, 'ohne': {'n', 'ok'}, 'quote_mit', 'quote_ohne', 'lift', 'urteil', 'je_tool': {...}}"""
    seit = (datetime.now(timezone.utc) - timedelta(hours=stunden)).isoformat(timespec="seconds")
    filt = "art:erfahrung (ok:ja OR ok:nein)" + (f" tool:{tool}" if tool else "")
    je_tool: dict[str, dict] = {}
    gesamt = {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}}
    for _, o, _g in g.erinnere(filt, limit=5000, betrachter=betrachter):
        if o.zeit < seit or (o.daten.get("vorher") or {}).get("aus_gedaechtnis"):
            continue
        t = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        seite = "mit" if _mit_hinweis(o) else "ohne"
        ok = "ok:ja" in o.hashtags
        for ziel in (gesamt, je_tool.setdefault(t, {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}})):
            ziel[seite]["n"] += 1
            ziel[seite]["ok"] += 1 if ok else 0
    return {**gesamt, **_bewerte(gesamt), "je_tool": {t: {**d, **_bewerte(d)} for t, d in je_tool.items()}, "stunden": stunden}


def _bewerte(d: dict) -> dict:
    qm = d["mit"]["ok"] / d["mit"]["n"] if d["mit"]["n"] else None
    qo = d["ohne"]["ok"] / d["ohne"]["n"] if d["ohne"]["n"] else None
    if d["mit"]["n"] < MINDESTENS or d["ohne"]["n"] < MINDESTENS:
        urteil = f"zu wenig Daten (mindestens {MINDESTENS} je Seite)"
    elif qm > qo + 0.05:
        urteil = "Hinweise nützen"
    elif qm < qo - 0.05:
        urteil = "Hinweise schaden — Annahme widerlegt, Gewichtung prüfen"
    else:
        urteil = "kein messbarer Unterschied"
    return {"quote_mit": qm, "quote_ohne": qo, "lift": (qm - qo) if qm is not None and qo is not None else None, "urteil": urteil}


def zeile(l: dict) -> str:
    f = lambda q: "—" if q is None else f"{q * 100:.0f} %"
    return (f"Hinweis-Lift {l['stunden']:g} h: mit Hinweis {l['mit']['ok']}/{l['mit']['n']} ok ({f(l['quote_mit'])}), "
            f"ohne {l['ohne']['ok']}/{l['ohne']['n']} ok ({f(l['quote_ohne'])})"
            + (f", Lift {l['lift'] * 100:+.0f} Punkte" if l["lift"] is not None else "") + f" → {l['urteil']}")
