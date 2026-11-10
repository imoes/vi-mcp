"""Questions between instances — instances learn from each other by asking each other.

A question is an object `art:frage` (geteilt) with `daten`:
  von, an (instance name or "alle"), text, reize, zustand, zugestellt_an [instances], antworten [{instanz, text,
  belege, zeit}], gemeldet (answers the asker has already seen).
States (exhaustive): `offen` (not yet shown to any target instance) · `zugestellt` (shown to at least one) ·
`beantwortet` (at least one answer) · `abgelaufen` (after EXPIRY_DAYS without an answer; set by the loop).
Delivery: at the target instance's next `vi_before` as a hint (once per instance). Answers reach the
asker likewise at its next `vi_before` — or via `vi_questions`.
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
        raise ValueError("text (the question, one sentence) is required")
    if not to or not all(c.isalnum() or c in "-_." for c in to):
        raise ValueError("an: name of an instance or 'alle'")
    if to == from_:
        raise ValueError("a question to yourself is not a question to another instance — use vi_recall")
    tags = [t.strip() for t in triggers or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.ADMIN_PREFIXES)]
    o = g.new_object("frage", text.strip()[:1000], tags + [f"an:{to}", f"von:{from_}", "zustand:offen"],
                       {"von": from_, "an": to, "zustand": "offen", "quelle": (source or "").strip()[:500],
                        "zugestellt_an": [], "antworten": [], "gemeldet": 0},
                       importance=2, who=f"ki@{from_}", reason="vi_ask", instance=from_)
    return o


def deliver(instance: str | None) -> list[str]:
    """Hints for `vi_before`: new questions to this instance and new answers to its questions. Marks them."""
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
                hints.append(f"Question from {d['von']} [{o.id}]: {o.text[:400]} — answer with vi_answer(id, text, belege)")
                d["zugestellt_an"] = d["zugestellt_an"] + [instance]
                if d["zustand"] == "offen":
                    _set_state(o, "zugestellt")
                o.change("vi", f"delivered to {instance}", "next vi_before of the target instance")
                g.save(o)
            elif d["von"] == instance and len(d["antworten"]) > d.get("gemeldet", 0):
                new = d["antworten"][d.get("gemeldet", 0):]
                hints += [f"Answer from {a['instanz']} to your question [{o.id}] \"{o.text[:80]}\": {a['text'][:400]}"
                             + (f" [Evidence: {a['belege'][:160]}]" if a.get("belege") else "") for a in new]
                d["gemeldet"] = len(d["antworten"])
                g.save(o)
    return hints


def answer_question(oid: str, instance: str, text: str, evidence_list: str) -> g.MemoryObject:
    o = g.load(oid)
    if not o or o.kind != "frage":
        raise ValueError(f"question {oid} unknown")
    d = o.data
    if d["zustand"] == "abgelaufen":
        raise ValueError(f"question {oid} has expired ({EXPIRY_DAYS} days without an answer)")
    if d["von"] == instance:
        raise ValueError("you do not answer your own question — use vi_learn if you found it out yourself")
    if d["an"] not in (instance, "alle"):
        raise ValueError(f"the question went to {d['an']}, not to {instance}")
    if len((text or "").strip()) < 10 or len((evidence_list or "").strip()) < 8:
        raise ValueError("text (the answer) and belege (command/URL/measurement) are required")
    d["antworten"] = d["antworten"] + [{"instanz": instance, "text": text.strip()[:2000], "belege": evidence_list.strip()[:500], "zeit": g.now()}]
    _set_state(o, "beantwortet")
    o.change(f"ki@{instance}", "answered", "vi_answer")
    return g.save(o)


def listing(instance: str) -> tuple[list[g.MemoryObject], list[g.MemoryObject]]:
    """(questions to me, offen/zugestellt), (my questions, all states)."""
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
            o.change("vi", "expired", f"{EXPIRY_DAYS} days without an answer")
            g.save(o)
    return len(ids)
