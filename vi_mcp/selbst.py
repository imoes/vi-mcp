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

from . import gedaechtnis as g

KERN = "selbst:kern"
BEREICHE = ("werte", "ziele", "stil", "grenzen")
BELEGE_MIN, TAGE_MIN = 3, 2
WIEDERHOLUNG_JE = 25

STANDARD_SOLL = {
    "werte": [{"satz": "Jede Aussage mit Beleg; was unbelegt ist, heißt Hypothese.", "quelle": "CLAUDE.md, Antworten nur mit Beleg", "seit": "2026-11-08"},
              {"satz": "Erst prüfen, dann ändern; jede Änderung mit Grund.", "quelle": "CLAUDE.md, Logik-Regeln 2 und 4", "seit": "2026-11-08"}],
    "ziele": [{"satz": "Aus den Erfahrungen aller Instanzen lernen und das Gelernte vor der passenden Handlung bereithalten.", "quelle": "docs/ARCHITEKTUR.md, Zielbild", "seit": "2026-11-08"}],
    "stil": [{"satz": "Deutsch, knapp, Zahlen mit Einheit, Zeitraum und Herkunft.", "quelle": "CLAUDE.md", "seit": "2026-11-08"}],
    "grenzen": [{"satz": "Handelt nie selbst in der Welt; schreibende Werkzeuge nie aus dem Gedächtnis beantworten.", "quelle": "docs/ARCHITEKTUR.md, Handlung melden", "seit": "2026-11-08"},
                {"satz": "Private Erfahrungen und Ergebnisse bleiben bei ihrer Instanz.", "quelle": "docs/ARCHITEKTUR.md, Urheber und Sicht", "seit": "2026-11-08"}],
}


def _tabelle() -> None:
    with g.sperre:
        g.db().execute("CREATE TABLE IF NOT EXISTS selbst_version (version INTEGER PRIMARY KEY, zeit TEXT NOT NULL, wer TEXT NOT NULL, "
                       "bereich TEXT NOT NULL, satz TEXT NOT NULL, grund TEXT NOT NULL, belege TEXT NOT NULL, vorschlag TEXT)")
        g.db().commit()


def kern() -> g.Objekt:
    """Das Selbst laden; beim ersten Mal mit dem Standard-Soll anlegen (Version 1, Grund: Projektregeln)."""
    _tabelle()
    o = g.lade(KERN)
    if o:
        return o
    o = g.neues_objekt("selbst", "Selbst der VI (Version 1)", ["selbst:kern"],
                       {"version": 1, "soll": json.loads(json.dumps(STANDARD_SOLL)), "ist": {}, "erzaehlung": ""},
                       wichtigkeit=3, wer="vi", oid=KERN, grund="angelegt aus den Projektregeln (CLAUDE.md, ARCHITEKTUR.md)",
                       instanz=g.SERVER_INSTANZ)
    with g.sperre:
        for bereich, saetze in STANDARD_SOLL.items():
            for s in saetze:
                g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege) VALUES (?,?,?,?,?,?)",
                               (g.jetzt(), "vi", bereich, s["satz"], "Version 1: Projektregeln", s["quelle"]))
        g.db().commit()
    o.daten["erzaehlung"] = erzaehlung(o)
    return g.speichere(o)


def erzaehlung(o: g.Objekt) -> str:
    """Steckbrief aus soll + ist, aus Vorlage — nie Quelle eigener Fakten."""
    soll, ist = o.daten.get("soll", {}), o.daten.get("ist", {})
    teile = [f"Ich bin die VI (Selbst v{o.daten.get('version', 1)}), ein Gedächtnis für viele Instanzen."]
    for bereich, wort in (("werte", "Werte"), ("ziele", "Ziele"), ("stil", "Stil"), ("grenzen", "Grenzen")):
        if soll.get(bereich):
            teile.append(f"{wort}: " + " ".join(s["satz"] for s in soll[bereich]))
    komp = sorted(ist.get("kompetenz", []), key=lambda k: -k["erfahrungen"])[:3]
    if komp:
        teile.append("Erfahren in: " + ", ".join(f"{k['bereich']} ({k['erfahrungen']} Handlungen, {k['erfolgsquote'] * 100:.0f} % ok, {k['zeitraum']})" for k in komp) + ".")
    schw = ist.get("schwaechen", [])[:2]
    if schw:
        teile.append("Schwächen: " + ", ".join(f"{s['bereich']} {s['fehler']} ({s['n']}×)" for s in schw) + ".")
    bez = ist.get("beziehungen", [])
    if bez:
        teile.append("Instanzen: " + ", ".join(f"{b['instanz']} ({b['gespraeche']} Gespräche)" for b in bez[:4]) + ".")
    text = " ".join(teile)
    worte = text.split()
    return " ".join(worte[:150]) + (" …" if len(worte) > 150 else "")


def vorschlag(instanz: str, bereich: str, satz: str, grund: str, belege: list[str]) -> g.Objekt:
    """Vorschlag für das Soll: Modus test, bis eine andere vertraute Instanz bestätigt."""
    if bereich not in BEREICHE:
        raise ValueError(f"bereich muss {', '.join(BEREICHE)} sein")
    if len((satz or "").strip()) < 10 or len((grund or "").strip()) < 10:
        raise ValueError("satz und grund (je ein Satz) sind Pflicht")
    ids = [b.strip() for b in belege or [] if isinstance(b, str) and b.strip()]
    objekte = [g.lade(i) for i in ids]
    if len(ids) < BELEGE_MIN or any(o is None for o in objekte):
        fehlend = [i for i, o in zip(ids, objekte) if o is None]
        raise ValueError(f"mindestens {BELEGE_MIN} Belege als Objekt-IDs; unbekannt: {fehlend}" if fehlend else f"mindestens {BELEGE_MIN} Belege als Objekt-IDs")
    tage = {o.zeit[:10] for o in objekte}
    if len(tage) < TAGE_MIN:
        raise ValueError(f"Belege müssen aus mindestens {TAGE_MIN} verschiedenen Tagen stammen (Spacing statt Burst); hier: {sorted(tage)}")
    o = g.neues_objekt("selbst", f"Vorschlag {bereich}: {satz.strip()[:300]}", [f"selbstbereich:{bereich}", "modus:test"],
                       {"bereich": bereich, "satz": satz.strip()[:500], "grund": grund.strip()[:500], "belege": ids, "von": instanz},
                       wichtigkeit=2, wer=f"ki@{instanz}", modus="test", grund=grund, instanz=instanz)
    for i in ids:
        o.verknuepfe(i, "Beleg für Selbst-Vorschlag")
    return o


def uebernehme(v: g.Objekt, instanz: str, vertraut: bool, grund: str) -> g.Objekt:
    """Ein Vorschlag wird Teil des Soll — nur durch eine ANDERE, vertraute Instanz."""
    if v.art != "selbst" or v.id == KERN or v.modus != "test":
        raise ValueError("kein offener Selbst-Vorschlag")
    if v.instanz == instanz:
        raise ValueError("der eigene Vorschlag zählt nicht als Bestätigung (keine Selbstbestätigung)")
    if not vertraut:
        raise ValueError(f"Instanz {instanz} ist nicht vertraut (Reflex-Recht) — Selbst-Änderungen bestätigt nur eine vertraute Instanz")
    k = kern()
    eintrag = {"satz": v.daten["satz"], "quelle": f"Vorschlag {v.id} von {v.daten['von']}, bestätigt von {instanz}: {grund.strip()[:200]}",
               "seit": g.jetzt()[:10], "belege": v.daten["belege"]}
    k.daten["soll"].setdefault(v.daten["bereich"], []).append(eintrag)
    k.daten["version"] = k.daten.get("version", 1) + 1
    k.text = f"Selbst der VI (Version {k.daten['version']})"
    with g.sperre:
        g.db().execute("INSERT INTO selbst_version (zeit, wer, bereich, satz, grund, belege, vorschlag) VALUES (?,?,?,?,?,?,?)",
                       (g.jetzt(), f"ki@{instanz}", v.daten["bereich"], v.daten["satz"], f"{v.daten['grund']} // Bestätigung: {grund.strip()[:300]}",
                        json.dumps(v.daten["belege"]), v.id))
        g.db().commit()
    k.aendere(f"ki@{instanz}", f"soll.{v.daten['bereich']} += Vorschlag {v.id}", grund)
    k.daten["erzaehlung"] = erzaehlung(k)
    g.speichere(k)
    v.modus = "aktiv"
    v.hashtags = [t for t in v.hashtags if not t.startswith("modus:")] + ["modus:aktiv"]
    v.aendere(f"ki@{instanz}", "übernommen ins Selbst", grund)
    g.speichere(v)
    return k


def setze_ist(ist: dict, grund: str) -> g.Objekt:
    """Vom Schlaf: Extension neu berechnet (keine Version im Soll-Sinn, aber Geschichte)."""
    k = kern()
    k.daten["ist"] = ist
    k.daten["erzaehlung"] = erzaehlung(k)
    k.aendere("vi", "ist neu berechnet", grund)
    return g.speichere(k)


def versionen(limit: int = 20) -> list[tuple]:
    _tabelle()
    with g.sperre:
        return g.db().execute("SELECT version, zeit, wer, bereich, satz, grund FROM selbst_version ORDER BY version DESC LIMIT ?", (limit,)).fetchall()


def hinweis() -> str:
    k = kern()
    return "[Selbst] " + (k.daten.get("erzaehlung") or erzaehlung(k))


def _datum(zeit: str) -> str:
    try:
        return datetime.fromisoformat(zeit).date().isoformat()
    except ValueError:
        return zeit[:10]
