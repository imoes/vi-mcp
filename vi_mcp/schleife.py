"""Der Loop — genau einer, weil es genau einen Serverprozess gibt.

Alle LOOP_S Sekunden: abgelaufene Antworten löschen, wiederholte Fehler zu Regeln (Modus test) verdichten,
offene Gespräche sichern, Gespräche im Leerlauf als `abgelaufen` schließen, WAL zurückschreiben.
Fehler eines Laufs werden gezählt und im Status genannt — nichts verschwindet still.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from . import gedaechtnis as g
from .protokoll import log

LOOP_S = 60
FEHLER_REGEL_AB = 3
stand = {"laeufe": 0, "zuletzt": None, "regeln_neu": 0, "fehler": 0, "letzter_fehler": None}
_halt = threading.Event()


def schritt() -> int:
    from . import intuition, sitzung
    neu = 0
    grenze = (datetime.now(timezone.utc) - timedelta(seconds=intuition.TTL_MAX)).isoformat(timespec="seconds")
    seit = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.sperre:
        alt = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE art = 'antwort' AND zeit < ?", (grenze,))]
        g.loesche(alt)
        rows = g.db().execute(
            "SELECT t1.tag, t2.tag, COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag LIKE 'tool:%' "
            "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag LIKE 'fehler:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t1.tag, t2.tag HAVING COUNT(*) >= ?", (seit, FEHLER_REGEL_AB)).fetchall()
        for tool_tag, fehler_tag, n in rows:
            rid = f"regel:{g.hashwert(tool_tag, fehler_tag, 'wiederholter-fehler')}"
            o = g.lade(rid)
            if o is None:
                g.neues_objekt("regel", f"{tool_tag[5:]} scheiterte {n}× in 24 h gleich ({fehler_tag[7:]}) — vor dem nächsten "
                                        "Aufruf Argumente oder Erreichbarkeit prüfen",
                               [tool_tag, f"skill:{tool_tag[5:].split('_')[0]}", fehler_tag, "regelart:wiederholter-fehler", "modus:test"],
                               {"treffer": n, "quelle": "Loop: Erfahrungen der letzten 24 h"}, wichtigkeit=2, oid=rid, modus="test",
                               grund=f"{n} gleiche Fehler in 24 h")  # gespraech None: der Loop handelt in keinem Gespräch
                neu += 1
            elif o.daten.get("treffer") != n:
                o.daten["treffer"] = n
                g.speichere(o)
    for s in sitzung.offene():
        if len(s.zuege) != s.gesichert_bis:
            sitzung.sichere(s)
    abgelaufen = sitzung.raeume_auf()
    if abgelaufen:
        log(f"Gespräche abgelaufen (Leerlauf): {', '.join(abgelaufen)}")
    with g.sperre:
        g.db().execute("PRAGMA wal_checkpoint(PASSIVE)")
    return neu


def _lauf() -> None:
    while not _halt.wait(LOOP_S):
        try:
            n = schritt()
            stand["laeufe"] += 1
            stand["zuletzt"] = g.jetzt()
            stand["regeln_neu"] += n
            if n:
                log(f"Loop: {n} neue Regel(n) aus Erfahrung")
        except Exception as exc:  # noqa: BLE001 — gezählt und im Status benannt
            stand["fehler"] += 1
            stand["letzter_fehler"] = f"{g.jetzt()} {type(exc).__name__}: {exc}"[:300]
            log(f"Loop-Fehler: {exc}")


def starte() -> threading.Thread:
    _halt.clear()
    th = threading.Thread(target=_lauf, name="vi-loop", daemon=True)
    th.start()
    return th


def halte() -> None:
    _halt.set()
