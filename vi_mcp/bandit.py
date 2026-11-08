"""Bandit — Thompson Sampling je Hinweis (Stufe 2, docs/TRAINING.md 4b).

Jeder Hinweis (Erkenntnis, Regel, gelernte Suche) führt ein Zählerpaar `daten.nuetzlich = {"ja": a, "nein": b}`:
a = Handlungen, die nach dem Zeigen gelangen, b = die scheiterten (ok:unbekannt zählt nicht). Beim Ordnen zieht der
Router je Hinweis eine Stichprobe aus Beta(1 + a, 1 + b) und sortiert danach — selten gezeigte Hinweise haben breite
Verteilungen und kommen von selbst wieder dran (Russo et al. 2017, arXiv 1707.02038; Agrawal & Goyal 2012,
arXiv 1209.3352). Das ist der heutige Zugriffszähler, nur mit Nenner — kein sklearn, kein Export, ab der ersten Handlung.

Rangordnung des Routers (erschöpfend, in `zugriff.router` benannt):
  modell     — das gelernte Modell ist aktiv (Stufe 1, Lift)
  bandit     — kein aktives Modell, aber mindestens ein Kandidat hat schon Zähler
  heuristik  — weder noch: Aktualität + Wichtigkeit + Bonus
"""
from __future__ import annotations

import random

from . import gedaechtnis as g

HINWEIS_ARTEN = ("erkenntnis:", "regel:", "suche:", "skill:")


def zaehler(o: g.Objekt) -> tuple[int, int]:
    n = o.daten.get("nuetzlich") or {}
    return int(n.get("ja", 0)), int(n.get("nein", 0))


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


def verbuche(gezeigt: list[str], ok: bool | None) -> int:
    """Nach der Handlung: ja/nein je gezeigtem Hinweis. ok None (kein Ergebnis gemeldet) zählt nicht. Atomar in der DB."""
    if ok is None:
        return 0
    feld = "ja" if ok else "nein"
    n = 0
    with g.sperre:
        for oid in gezeigt:
            if not oid.startswith(HINWEIS_ARTEN):
                continue
            # JSON-Zähler in daten relativ erhöhen — kein Lesen-Ändern-Schreiben über die Objekt-Klasse (kein verlorener Zähler)
            # zuletzt_gezeigt zählt fürs Housekeeping als Verwendung, verändert aber die Aktualität nicht (kein Matthäus-Effekt)
            cur = g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.' || ?, "
                                 "COALESCE(json_extract(daten, '$.nuetzlich.' || ?), 0) + 1, '$.zuletzt_gezeigt', ?) WHERE id = ?",
                                 (feld, feld, g.jetzt(), oid))
            n += cur.rowcount
        g.db().commit()
    return n


def umbuchen(gezeigt: list[str]) -> int:
    """Der Scorer stellt nachträglich fest, dass eine als gelungen gezählte Handlung misslungen ist: ein Ja wird zum Nein."""
    n = 0
    with g.sperre:
        for oid in gezeigt:
            if oid.startswith(HINWEIS_ARTEN):
                n += g.db().execute("UPDATE objekt SET daten = json_set(daten, '$.nuetzlich.ja', max(COALESCE(json_extract(daten, '$.nuetzlich.ja'), 0) - 1, 0), "
                                    "'$.nuetzlich.nein', COALESCE(json_extract(daten, '$.nuetzlich.nein'), 0) + 1) WHERE id = ?", (oid,)).rowcount
        g.db().commit()
    return n


def zeile(o: g.Objekt) -> str:
    ja, nein = zaehler(o)
    return f"genützt {ja} / nicht {nein} (Erwartung {erwartung(o) * 100:.0f} %)" if ja + nein else "noch nie nach dem Zeigen bewertet"
