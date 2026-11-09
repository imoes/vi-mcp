"""Rückfragen zwischen Instanzen — Instanzen lernen voneinander, indem sie einander fragen.

Eine Frage ist ein Objekt `art:frage` (geteilt) mit `daten`:
  von, an (Instanzname oder "alle"), text, reize, zustand, zugestellt_an [Instanzen], antworten [{instanz, text,
  belege, zeit}], gemeldet (Antworten, die der Fragesteller schon gesehen hat).
Zustände (erschöpfend): `offen` (noch keiner Zielinstanz gezeigt) · `zugestellt` (mindestens einer gezeigt) ·
`beantwortet` (mindestens eine Antwort) · `abgelaufen` (nach ABLAUF_TAGE ohne Antwort; vom Loop gesetzt).
Zustellung: beim nächsten `vi_before` der Zielinstanz als Hinweis (je Instanz einmal). Antworten erreichen den
Fragesteller ebenso beim nächsten `vi_before` — oder über `vi_questions`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import memory as g

STATES = ("offen", "zugestellt", "beantwortet", "abgelaufen")
EXPIRY_DAYS = 7


def _set_state(o: g.MemoryObject, state: str) -> None:
    o.data["zustand"] = state
    o.hashtags = [t for t in o.hashtags if not t.startswith("zustand:")] + [f"zustand:{state}"]


def ask(from_: str, to: str, text: str, triggers: list[str], source: str) -> g.MemoryObject:
    if len((text or "").strip()) < 10:
        raise ValueError("text (die Frage, ein Satz) ist Pflicht")
    if not to or not all(c.isalnum() or c in "-_." for c in to):
        raise ValueError("an: Name einer Instanz oder 'alle'")
    if to == from_:
        raise ValueError("eine Frage an sich selbst ist keine Rückfrage — vi_recall nutzen")
    tags = [t.strip() for t in triggers or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.ADMIN_PREFIXES)]
    o = g.new_object("frage", text.strip()[:1000], tags + [f"an:{to}", f"von:{from_}", "zustand:offen"],
                       {"von": from_, "an": to, "zustand": "offen", "quelle": (source or "").strip()[:500],
                        "zugestellt_an": [], "antworten": [], "gemeldet": 0},
                       importance=2, who=f"ki@{from_}", reason="vi_ask", instance=from_)
    return o


def deliver(instance: str | None) -> list[str]:
    """Hinweise für `vi_before`: neue Fragen an diese Instanz und neue Antworten auf ihre Fragen. Markiert sie."""
    if not instance:
        return []
    hints = []
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt', 'beantwortet') "
            "AND (json_extract(daten, '$.an') IN (?, 'alle') OR json_extract(daten, '$.von') = ?) ORDER BY zeit", (instance, instance))]
        for oid in ids:
            o = g.load(oid)
            d = o.data
            if d["von"] != instance and instance not in d["zugestellt_an"] and d["zustand"] != "abgelaufen":
                hints.append(f"Rückfrage von {d['von']} [{o.id}]: {o.text[:400]} — antworten mit vi_answer(id, text, belege)")
                d["zugestellt_an"] = d["zugestellt_an"] + [instance]
                if d["zustand"] == "offen":
                    _set_state(o, "zugestellt")
                o.change("vi", f"zugestellt an {instance}", "nächstes vi_before der Zielinstanz")
                g.save(o)
            elif d["von"] == instance and len(d["antworten"]) > d.get("gemeldet", 0):
                new = d["antworten"][d.get("gemeldet", 0):]
                hints += [f"Antwort von {a['instanz']} auf deine Frage [{o.id}] „{o.text[:80]}“: {a['text'][:400]}"
                             + (f" [Belege: {a['belege'][:160]}]" if a.get("belege") else "") for a in new]
                d["gemeldet"] = len(d["antworten"])
                g.save(o)
    return hints


def answer_question(oid: str, instance: str, text: str, evidence_list: str) -> g.MemoryObject:
    o = g.load(oid)
    if not o or o.kind != "frage":
        raise ValueError(f"Frage {oid} unbekannt")
    d = o.data
    if d["zustand"] == "abgelaufen":
        raise ValueError(f"Frage {oid} ist abgelaufen ({EXPIRY_DAYS} Tage ohne Antwort)")
    if d["von"] == instance:
        raise ValueError("die eigene Frage beantwortet man nicht — vi_learn nutzen, wenn du es selbst herausgefunden hast")
    if d["an"] not in (instance, "alle"):
        raise ValueError(f"die Frage ging an {d['an']}, nicht an {instance}")
    if len((text or "").strip()) < 10 or len((evidence_list or "").strip()) < 8:
        raise ValueError("text (die Antwort) und belege (Befehl/URL/Messung) sind Pflicht")
    d["antworten"] = d["antworten"] + [{"instanz": instance, "text": text.strip()[:2000], "belege": evidence_list.strip()[:500], "zeit": g.now()}]
    _set_state(o, "beantwortet")
    o.change(f"ki@{instance}", "beantwortet", "vi_answer")
    return g.save(o)


def listing(instance: str) -> tuple[list[g.MemoryObject], list[g.MemoryObject]]:
    """(Fragen an mich, offen/zugestellt), (meine Fragen, alle Zustände)."""
    with g.lock:
        to_me = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt') "
            "AND json_extract(daten, '$.an') IN (?, 'alle') AND json_extract(daten, '$.von') <> ? ORDER BY zeit DESC LIMIT 50", (instance, instance))]
        mine = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.von') = ? ORDER BY zeit DESC LIMIT 50", (instance,))]
    return [g.load(i) for i in to_me], [g.load(i) for i in mine]


def let_expire() -> int:
    bound = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).isoformat(timespec="seconds")
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'frage' AND zeit < ? AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt')", (bound,))]
        for oid in ids:
            o = g.load(oid)
            _set_state(o, "abgelaufen")
            o.change("vi", "abgelaufen", f"{EXPIRY_DAYS} Tage ohne Antwort")
            g.save(o)
    return len(ids)
