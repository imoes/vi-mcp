"""Rückfragen zwischen Instanzen — Instanzen lernen voneinander, indem sie einander fragen.

Eine Frage ist ein Objekt `art:frage` (geteilt) mit `daten`:
  von, an (Instanzname oder "alle"), text, reize, zustand, zugestellt_an [Instanzen], antworten [{instanz, text,
  belege, zeit}], gemeldet (Antworten, die der Fragesteller schon gesehen hat).
Zustände (erschöpfend): `offen` (noch keiner Zielinstanz gezeigt) · `zugestellt` (mindestens einer gezeigt) ·
`beantwortet` (mindestens eine Antwort) · `abgelaufen` (nach ABLAUF_TAGE ohne Antwort; vom Loop gesetzt).
Zustellung: beim nächsten `vi_vorher` der Zielinstanz als Hinweis (je Instanz einmal). Antworten erreichen den
Fragesteller ebenso beim nächsten `vi_vorher` — oder über `vi_fragen`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import gedaechtnis as g

ZUSTAENDE = ("offen", "zugestellt", "beantwortet", "abgelaufen")
ABLAUF_TAGE = 7


def _setze_zustand(o: g.Objekt, zustand: str) -> None:
    o.daten["zustand"] = zustand
    o.hashtags = [t for t in o.hashtags if not t.startswith("zustand:")] + [f"zustand:{zustand}"]


def stelle(von: str, an: str, text: str, reize: list[str], quelle: str) -> g.Objekt:
    if len((text or "").strip()) < 10:
        raise ValueError("text (die Frage, ein Satz) ist Pflicht")
    if not an or not all(c.isalnum() or c in "-_." for c in an):
        raise ValueError("an: Name einer Instanz oder 'alle'")
    if an == von:
        raise ValueError("eine Frage an sich selbst ist keine Rückfrage — vi_erinnere nutzen")
    tags = [t.strip() for t in reize or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.VERWALTUNG)]
    o = g.neues_objekt("frage", text.strip()[:1000], tags + [f"an:{an}", f"von:{von}", "zustand:offen"],
                       {"von": von, "an": an, "zustand": "offen", "quelle": (quelle or "").strip()[:500],
                        "zugestellt_an": [], "antworten": [], "gemeldet": 0},
                       wichtigkeit=2, wer=f"ki@{von}", grund="vi_frage", instanz=von)
    return o


def zustellen(instanz: str | None) -> list[str]:
    """Hinweise für `vi_vorher`: neue Fragen an diese Instanz und neue Antworten auf ihre Fragen. Markiert sie."""
    if not instanz:
        return []
    hinweise = []
    with g.sperre:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt', 'beantwortet') "
            "AND (json_extract(daten, '$.an') IN (?, 'alle') OR json_extract(daten, '$.von') = ?) ORDER BY zeit", (instanz, instanz))]
        for oid in ids:
            o = g.lade(oid)
            d = o.daten
            if d["von"] != instanz and instanz not in d["zugestellt_an"] and d["zustand"] != "abgelaufen":
                hinweise.append(f"Rückfrage von {d['von']} [{o.id}]: {o.text[:400]} — antworten mit vi_antwort(id, text, belege)")
                d["zugestellt_an"] = d["zugestellt_an"] + [instanz]
                if d["zustand"] == "offen":
                    _setze_zustand(o, "zugestellt")
                o.aendere("vi", f"zugestellt an {instanz}", "nächstes vi_vorher der Zielinstanz")
                g.speichere(o)
            elif d["von"] == instanz and len(d["antworten"]) > d.get("gemeldet", 0):
                neu = d["antworten"][d.get("gemeldet", 0):]
                hinweise += [f"Antwort von {a['instanz']} auf deine Frage [{o.id}] „{o.text[:80]}“: {a['text'][:400]}"
                             + (f" [Belege: {a['belege'][:160]}]" if a.get("belege") else "") for a in neu]
                d["gemeldet"] = len(d["antworten"])
                g.speichere(o)
    return hinweise


def beantworte(oid: str, instanz: str, text: str, belege: str) -> g.Objekt:
    o = g.lade(oid)
    if not o or o.art != "frage":
        raise ValueError(f"Frage {oid} unbekannt")
    d = o.daten
    if d["zustand"] == "abgelaufen":
        raise ValueError(f"Frage {oid} ist abgelaufen ({ABLAUF_TAGE} Tage ohne Antwort)")
    if d["von"] == instanz:
        raise ValueError("die eigene Frage beantwortet man nicht — vi_lerne nutzen, wenn du es selbst herausgefunden hast")
    if d["an"] not in (instanz, "alle"):
        raise ValueError(f"die Frage ging an {d['an']}, nicht an {instanz}")
    if len((text or "").strip()) < 10 or len((belege or "").strip()) < 8:
        raise ValueError("text (die Antwort) und belege (Befehl/URL/Messung) sind Pflicht")
    d["antworten"] = d["antworten"] + [{"instanz": instanz, "text": text.strip()[:2000], "belege": belege.strip()[:500], "zeit": g.jetzt()}]
    _setze_zustand(o, "beantwortet")
    o.aendere(f"ki@{instanz}", "beantwortet", "vi_antwort")
    return g.speichere(o)


def liste(instanz: str) -> tuple[list[g.Objekt], list[g.Objekt]]:
    """(Fragen an mich, offen/zugestellt), (meine Fragen, alle Zustände)."""
    with g.sperre:
        an_mich = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt') "
            "AND json_extract(daten, '$.an') IN (?, 'alle') AND json_extract(daten, '$.von') <> ? ORDER BY zeit DESC LIMIT 50", (instanz, instanz))]
        meine = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.von') = ? ORDER BY zeit DESC LIMIT 50", (instanz,))]
    return [g.lade(i) for i in an_mich], [g.lade(i) for i in meine]


def lass_ablaufen() -> int:
    grenze = (datetime.now(timezone.utc) - timedelta(days=ABLAUF_TAGE)).isoformat(timespec="seconds")
    with g.sperre:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND zeit < ? AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt')", (grenze,))]
        for oid in ids:
            o = g.lade(oid)
            _setze_zustand(o, "abgelaufen")
            o.aendere("vi", "abgelaufen", f"{ABLAUF_TAGE} Tage ohne Antwort")
            g.speichere(o)
    return len(ids)
