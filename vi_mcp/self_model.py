"""Das Selbst — ein Objekt, das jede Sitzung lädt und das sich nur mit Grund, Belegen und Bestätigung ändert.

Vorbild: Conways Self-Memory-System und der Steckbrief in Park et al. 2023 (docs/FORSCHUNG.md A12, B1, C1).
Intension und Extension getrennt:
  soll  Werte, Ziele, Stil, Grenzen — Sätze mit Herkunft. Ändert sich nur über einen **Vorschlag** (Objekt art
        `selbst`, Modus `test`, ≥ 3 Belege aus ≥ 2 Tagen), den eine **andere, vertraute Instanz** bestätigt.
        „Vertraut“ = Instanz mit Reflex-Recht — Annahme: dahinter steht ein Mensch, der freigibt (benannt).
  ist   Kompetenz, Schwächen, Beziehungen — vom Schlaf aus Daten berechnet, nie von Hand.
  erzaehlung  ≤ 150 Wörter aus soll + ist (Vorlage, kein Modell); geht in `initialize.instructions` und alle
        WIEDERHOLUNG_JE Handlungen als Hinweis (Persona-Drift nach wenigen Runden, Li et al. 2024).
Geschichte: Tabelle `selbst_version` — vollständig, nicht gekürzt (anders als `aenderungen`).
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
    "werte": [{"satz": "Jede Aussage mit Beleg; was unbelegt ist, heißt Hypothese.", "quelle": "CLAUDE.md, Antworten nur mit Beleg", "seit": "2026-11-08"},
              {"satz": "Erst prüfen, dann ändern; jede Änderung mit Grund.", "quelle": "CLAUDE.md, Logik-Regeln 2 und 4", "seit": "2026-11-08"}],
    "ziele": [{"satz": "Aus den Erfahrungen aller Instanzen lernen und das Gelernte vor der passenden Handlung bereithalten.", "quelle": "docs/ARCHITEKTUR.md, Zielbild", "seit": "2026-11-08"}],
    "stil": [{"satz": "Deutsch, knapp, Zahlen mit Einheit, Zeitraum und Herkunft.", "quelle": "CLAUDE.md", "seit": "2026-11-08"}],
    "grenzen": [{"satz": "Handelt nie selbst in der Welt; schreibende Werkzeuge nie aus dem Gedächtnis beantworten.", "quelle": "docs/ARCHITEKTUR.md, Handlung melden", "seit": "2026-11-08"},
                {"satz": "Private Erfahrungen und Ergebnisse bleiben bei ihrer Instanz.", "quelle": "docs/ARCHITEKTUR.md, Urheber und Sicht", "seit": "2026-11-08"}],
}


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS selbst_version (version INTEGER PRIMARY KEY, zeit TEXT NOT NULL, wer TEXT NOT NULL, "
                       "bereich TEXT NOT NULL, satz TEXT NOT NULL, grund TEXT NOT NULL, belege TEXT NOT NULL, vorschlag TEXT)")
        g.db().commit()


def core() -> g.MemoryObject:
    """Das Selbst laden; beim ersten Mal mit dem Standard-Soll anlegen (Version 1, Grund: Projektregeln)."""
    _table()
    o = g.load(CORE)
    if o:
        return o
    o = g.new_object("selbst", "Selbst der VI (Version 1)", ["selbst:kern"],
                       {"version": 1, "soll": json.loads(json.dumps(DEFAULT_TARGET)), "ist": {}, "erzaehlung": ""},
                       importance=3, who="vi", oid=CORE, reason="angelegt aus den Projektregeln (CLAUDE.md, ARCHITEKTUR.md)",
                       instance=g.SERVER_INSTANCE)
    with g.lock:
        for area, sentences in DEFAULT_TARGET.items():
            for s in sentences:
                g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege) VALUES (?,?,?,?,?,?)",
                               (g.now(), "vi", area, s["satz"], "Version 1: Projektregeln", s["quelle"]))
        g.db().commit()
    o.data["erzaehlung"] = narrative(o)
    return g.save(o)


def narrative(o: g.MemoryObject) -> str:
    """Steckbrief aus soll + ist, aus Vorlage — nie Quelle eigener Fakten."""
    desired, actual = o.data.get("soll", {}), o.data.get("ist", {})
    parts = [f"Ich bin die VI (Selbst v{o.data.get('version', 1)}), ein Gedächtnis für viele Instanzen."]
    for area, word in (("werte", "Werte"), ("ziele", "Ziele"), ("stil", "Stil"), ("grenzen", "Grenzen")):
        if desired.get(area):
            parts.append(f"{word}: " + " ".join(s["satz"] for s in desired[area]))
    comp = sorted(actual.get("kompetenz", []), key=lambda k: -k["erfahrungen"])[:3]
    if comp:
        parts.append("Erfahren in: " + ", ".join(f"{k['bereich']} ({k['erfahrungen']} Handlungen, {k['erfolgsquote'] * 100:.0f} % ok, {k['zeitraum']})" for k in comp) + ".")
    weak = actual.get("schwaechen", [])[:2]
    if weak:
        parts.append("Schwächen: " + ", ".join(f"{s['bereich']} {s['fehler']} ({s['n']}×)" for s in weak) + ".")
    relations = actual.get("beziehungen", [])
    if relations:
        parts.append("Instanzen: " + ", ".join(f"{b['instanz']} ({b['gespraeche']} Gespräche)" for b in relations[:4]) + ".")
    text = " ".join(parts)
    words = text.split()
    return " ".join(words[:150]) + (" …" if len(words) > 150 else "")


def proposal(instance: str, area: str, sentence: str, reason: str, evidence_list: list[str]) -> g.MemoryObject:
    """Vorschlag für das Soll: Modus test, bis eine andere vertraute Instanz bestätigt."""
    if area not in AREAS:
        raise ValueError(f"bereich muss {', '.join(AREAS)} sein")
    if len((sentence or "").strip()) < 10 or len((reason or "").strip()) < 10:
        raise ValueError("satz und grund (je ein Satz) sind Pflicht")
    ids = [b.strip() for b in evidence_list or [] if isinstance(b, str) and b.strip()]
    mem_objects = [g.load(i) for i in ids]
    if len(ids) < EVIDENCE_MIN or any(o is None for o in mem_objects):
        missing = [i for i, o in zip(ids, mem_objects) if o is None]
        raise ValueError(f"mindestens {EVIDENCE_MIN} Belege als Objekt-IDs; unbekannt: {missing}" if missing else f"mindestens {EVIDENCE_MIN} Belege als Objekt-IDs")
    days = {o.ts[:10] for o in mem_objects}
    if len(days) < DAYS_MIN:
        raise ValueError(f"Belege müssen aus mindestens {DAYS_MIN} verschiedenen Tagen stammen (Spacing statt Burst); hier: {sorted(days)}")
    o = g.new_object("selbst", f"Vorschlag {area}: {sentence.strip()[:300]}", [f"selbstbereich:{area}", "modus:test"],
                       {"bereich": area, "satz": sentence.strip()[:500], "grund": reason.strip()[:500], "belege": ids, "von": instance},
                       importance=2, who=f"ki@{instance}", mode="test", reason=reason, instance=instance)
    for i in ids:
        o.link(i, "Beleg für Selbst-Vorschlag")
    return o


def adopt(v: g.MemoryObject, instance: str, trusted: bool, reason: str) -> g.MemoryObject:
    """Ein Vorschlag wird Teil des Soll — nur durch eine ANDERE, vertraute Instanz."""
    if v.kind != "selbst" or v.id == CORE or v.mode != "test":
        raise ValueError("kein offener Selbst-Vorschlag")
    if v.instance == instance:
        raise ValueError("der eigene Vorschlag zählt nicht als Bestätigung (keine Selbstbestätigung)")
    if not trusted:
        raise ValueError(f"Instanz {instance} ist nicht vertraut (Reflex-Recht) — Selbst-Änderungen bestätigt nur eine vertraute Instanz")
    k = core()
    entry = {"satz": v.data["satz"], "quelle": f"Vorschlag {v.id} von {v.data['von']}, bestätigt von {instance}: {reason.strip()[:200]}",
               "seit": g.now()[:10], "belege": v.data["belege"]}
    k.data["soll"].setdefault(v.data["bereich"], []).append(entry)
    k.data["version"] = k.data.get("version", 1) + 1
    k.text = f"Selbst der VI (Version {k.data['version']})"
    with g.lock:
        g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege, vorschlag) VALUES (?,?,?,?,?,?,?)",
                       (g.now(), f"ki@{instance}", v.data["bereich"], v.data["satz"], f"{v.data['grund']} // Bestätigung: {reason.strip()[:300]}",
                        json.dumps(v.data["belege"]), v.id))
        g.db().commit()
    k.change(f"ki@{instance}", f"soll.{v.data['bereich']} += Vorschlag {v.id}", reason)
    k.data["erzaehlung"] = narrative(k)
    g.save(k)
    v.mode = "aktiv"
    v.hashtags = [t for t in v.hashtags if not t.startswith("modus:")] + ["modus:aktiv"]
    v.change(f"ki@{instance}", "übernommen ins Selbst", reason)
    g.save(v)
    return k


def set_actual(actual: dict, reason: str) -> g.MemoryObject:
    """Vom Schlaf: Extension neu berechnet (keine Version im Soll-Sinn, aber Geschichte)."""
    k = core()
    k.data["ist"] = actual
    k.data["erzaehlung"] = narrative(k)
    k.change("vi", "ist neu berechnet", reason)
    return g.save(k)


def versions(limit: int = 20) -> list[tuple]:
    _table()
    with g.lock:
        return g.db().execute("SELECT version, zeit, wer, bereich, satz, grund FROM selbst_version ORDER BY version DESC LIMIT ?", (limit,)).fetchall()


def hint() -> str:
    k = core()
    return "[Selbst] " + (k.data.get("erzaehlung") or narrative(k))


def _day_of(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except ValueError:
        return ts[:10]
