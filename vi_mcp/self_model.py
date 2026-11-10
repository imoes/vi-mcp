"""The self — an object every session loads and that changes only with reason, evidence and confirmation.

Model: Conway's Self-Memory System and the profile in Park et al. 2023 (docs/FORSCHUNG.md A12, B1, C1).
Intension and extension kept apart:
  soll  values, goals, style, limits — sentences with origin. Changes only via a **proposal** (object kind
        `selbst`, mode `test`, ≥ 3 pieces of evidence from ≥ 2 days) that **another, trusted instance** confirms.
        "Trusted" = instance with reflex right — assumption: a human who releases stands behind it (named).
  ist   competence, weaknesses, relations — computed from data by sleep, never by hand.
  erzaehlung  ≤ 150 words from soll + ist (template, no model); goes into `initialize.instructions` and every
        REPEAT_PER actions as a hint (persona drift after a few rounds, Li et al. 2024).
History: table `selbst_version` — complete, not truncated (unlike `aenderungen`).
"""
from __future__ import annotations

import json
from datetime import datetime

from . import memory as g

CORE = "selbst:kern"
AREAS = ("werte", "ziele", "stil", "grenzen")
EVIDENCE_MIN, DAYS_MIN = 3, 2
REPEAT_PER = 25

DEFAULT_TARGET = {
    "werte": [{"satz": "Every statement with evidence; what has no evidence is called a hypothesis.", "quelle": "CLAUDE.md, answers only with evidence", "seit": "2026-11-08"},
              {"satz": "Check first, then change; every change with a reason.", "quelle": "CLAUDE.md, logic rules 2 and 4", "seit": "2026-11-08"}],
    "ziele": [{"satz": "Learn from the experiences of all instances and have what was learned ready before the matching action.", "quelle": "docs/ARCHITECTURE.md, Target picture", "seit": "2026-11-08"}],
    "stil": [{"satz": "Answer in the user's language, concise; numbers with unit, period and origin.", "quelle": "CLAUDE.md", "seit": "2026-11-08"}],
    "grenzen": [{"satz": "Never acts in the world itself; never answers calls of writing tools from memory.", "quelle": "docs/ARCHITECTURE.md, Reporting an action", "seit": "2026-11-08"},
                {"satz": "Private experiences and results stay with their instance.", "quelle": "docs/ARCHITECTURE.md, Visibilities", "seit": "2026-11-08"}],
}


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS selbst_version (version INTEGER PRIMARY KEY, zeit TEXT NOT NULL, wer TEXT NOT NULL, "
                       "bereich TEXT NOT NULL, satz TEXT NOT NULL, grund TEXT NOT NULL, belege TEXT NOT NULL, vorschlag TEXT)")
        g.db().commit()


def core() -> g.MemoryObject:
    """Load the self; the first time, create it with the default target (version 1, reason: project rules)."""
    _table()
    o = g.load(CORE)
    if o:
        return o
    o = g.new_object("selbst", "Self of the VI (version 1)", ["selbst:kern"],
                       {"version": 1, "soll": json.loads(json.dumps(DEFAULT_TARGET)), "ist": {}, "erzaehlung": ""},
                       importance=3, who="vi", oid=CORE, reason="created from the project rules (CLAUDE.md, ARCHITECTURE.md)",
                       instance=g.SERVER_INSTANCE)
    with g.lock:
        for area, sentences in DEFAULT_TARGET.items():
            for s in sentences:
                g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege) VALUES (?,?,?,?,?,?)",
                               (g.now(), "vi", area, s["satz"], "version 1: project rules", s["quelle"]))
        g.db().commit()
    o.data["erzaehlung"] = narrative(o)
    return g.save(o)


def narrative(o: g.MemoryObject) -> str:
    """Profile from soll + ist, from a template — never a source of its own facts."""
    desired, actual = o.data.get("soll", {}), o.data.get("ist", {})
    parts = [f"I am the VI (self v{o.data.get('version', 1)}), a memory for many instances."]
    for area, word in (("werte", "Values"), ("ziele", "Goals"), ("stil", "Style"), ("grenzen", "Limits")):
        if desired.get(area):
            parts.append(f"{word}: " + " ".join(s["satz"] for s in desired[area]))
    comp = sorted(actual.get("kompetenz", []), key=lambda k: -k["erfahrungen"])[:3]
    if comp:
        parts.append("Experienced in: " + ", ".join(f"{k['bereich']} ({k['erfahrungen']} actions, {k['erfolgsquote'] * 100:.0f} % ok, {k['zeitraum']})" for k in comp) + ".")
    weak = actual.get("schwaechen", [])[:2]
    if weak:
        parts.append("Weaknesses: " + ", ".join(f"{s['bereich']} {s['fehler']} ({s['n']}×)" for s in weak) + ".")
    relations = actual.get("beziehungen", [])
    if relations:
        parts.append("Instances: " + ", ".join(f"{b['instanz']} ({b['gespraeche']} conversations)" for b in relations[:4]) + ".")
    text = " ".join(parts)
    words = text.split()
    return " ".join(words[:150]) + (" …" if len(words) > 150 else "")


def proposal(instance: str, area: str, sentence: str, reason: str, evidence_list: list[str]) -> g.MemoryObject:
    """Proposal for the target: mode test until another trusted instance confirms."""
    if area not in AREAS:
        raise ValueError(f"bereich must be one of {', '.join(AREAS)}")
    if len((sentence or "").strip()) < 10 or len((reason or "").strip()) < 10:
        raise ValueError("satz and grund (one sentence each) are required")
    ids = [b.strip() for b in evidence_list or [] if isinstance(b, str) and b.strip()]
    mem_objects = [g.load(i) for i in ids]
    if len(ids) < EVIDENCE_MIN or any(o is None for o in mem_objects):
        missing = [i for i, o in zip(ids, mem_objects) if o is None]
        raise ValueError(f"at least {EVIDENCE_MIN} pieces of evidence as object IDs; unknown: {missing}" if missing else f"at least {EVIDENCE_MIN} pieces of evidence as object IDs")
    days = {o.ts[:10] for o in mem_objects}
    if len(days) < DAYS_MIN:
        raise ValueError(f"evidence must come from at least {DAYS_MIN} different days (spacing instead of burst); here: {sorted(days)}")
    o = g.new_object("selbst", f"Proposal {area}: {sentence.strip()[:300]}", [f"selbstbereich:{area}", "modus:test"],
                       {"bereich": area, "satz": sentence.strip()[:500], "grund": reason.strip()[:500], "belege": ids, "von": instance},
                       importance=2, who=f"ki@{instance}", mode="test", reason=reason, instance=instance)
    for i in ids:
        o.link(i, "Beleg for self proposal")
    return o


def adopt(v: g.MemoryObject, instance: str, trusted: bool, reason: str) -> g.MemoryObject:
    """A proposal becomes part of the target — only through ANOTHER, trusted instance."""
    if v.kind != "selbst" or v.id == CORE or v.mode != "test":
        raise ValueError("not an open self proposal")
    if v.instance == instance:
        raise ValueError("one's own proposal does not count as confirmation (no self-confirmation)")
    if not trusted:
        raise ValueError(f"instance {instance} is not trusted (reflex right) — only a trusted instance confirms self changes")
    k = core()
    entry = {"satz": v.data["satz"], "quelle": f"proposal {v.id} from {v.data['von']}, confirmed by {instance}: {reason.strip()[:200]}",
               "seit": g.now()[:10], "belege": v.data["belege"]}
    k.data["soll"].setdefault(v.data["bereich"], []).append(entry)
    k.data["version"] = k.data.get("version", 1) + 1
    k.text = f"Self of the VI (version {k.data['version']})"
    with g.lock:
        g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege, vorschlag) VALUES (?,?,?,?,?,?,?)",
                       (g.now(), f"ki@{instance}", v.data["bereich"], v.data["satz"], f"{v.data['grund']} // confirmation: {reason.strip()[:300]}",
                        json.dumps(v.data["belege"]), v.id))
        g.db().commit()
    k.change(f"ki@{instance}", f"soll.{v.data['bereich']} += proposal {v.id}", reason)
    k.data["erzaehlung"] = narrative(k)
    g.save(k)
    v.mode = "aktiv"
    v.hashtags = [t for t in v.hashtags if not t.startswith("modus:")] + ["modus:aktiv"]
    v.change(f"ki@{instance}", "adopted into the self", reason)
    g.save(v)
    return k


def set_actual(actual: dict, reason: str) -> g.MemoryObject:
    """From sleep: extension recomputed (no version in the target sense, but history)."""
    k = core()
    k.data["ist"] = actual
    k.data["erzaehlung"] = narrative(k)
    k.change("vi", "ist recomputed", reason)
    return g.save(k)


def versions(limit: int = 20) -> list[tuple]:
    _table()
    with g.lock:
        return g.db().execute("SELECT version, zeit, wer, bereich, satz, grund FROM selbst_version ORDER BY version DESC LIMIT ?", (limit,)).fetchall()


def hint() -> str:
    k = core()
    return "[Self] " + (k.data.get("erzaehlung") or narrative(k))


def _day_of(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except ValueError:
        return ts[:10]
