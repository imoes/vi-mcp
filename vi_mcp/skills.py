"""Skills — Lösungswege, die entstehen, wenn etwas als gelöst gilt (Stufe 6; prozedurales Gedächtnis, docs/FORSCHUNG.md A3).

Ein Skill ist ein geteiltes Objekt `skill:<name>`:
  Problem    Reize (tool:, skill:, host:, thema:, fehler:), an denen er vor einer Handlung erscheint
  Lösungsweg Schritte (Werkzeugfolge) + ein Satz Anleitung — zunächst Text, der dem Bewusstsein gezeigt wird;
             ausführbar wird ein Skill nur über den geprüften Reflex-Weg (Code im Gedächtnis), nie von selbst
  Versionen  jede Weiterentwicklung mit Zeit, Urheber, Grund, Belegen (vollständig in daten.versionen)
  Zähler     genützt/nicht nach dem Zeigen (bandit) — ein Skill, der dreimal scheitert und nie nützt, wird `strittig`
Entstehung:
  vi_geloest      eine Instanz meldet: Problem X wurde so gelöst (Schritte, Grund, Belege)
  Schlaf 4c       automatisch: eine Handlung gelang nach Fehlern desselben Werkzeugs im selben Gespräch
                  (`ueberraschung:erholt`) — die Werkzeugfolge vom ersten Fehler bis zum Erfolg ist der Lösungsweg
Zusammenführen:
  vi_skill_fusion(a, b, grund)  neuer Skill aus beiden (Reize vereinigt, Schritte hintereinander, Belege vereinigt);
                  a und b bekommen Modus `aufgegangen` mit Verweis — sie verschwinden nicht, sie sind aufgegangen.
  Schlaf          gleicher Problem-Schlüssel (tool + Fehlersignatur) oder Vektornähe ≥ 0,95 → `fusion:vorschlag` + Kante;
                  zusammengeführt wird nur von einer Instanz, nie vom Server.
"""
from __future__ import annotations

import re

from . import gedaechtnis as g

SCHLECHT_AB = 3
SCHLECHT_QUOTE = 0.3

#: Werkzeuge, die in fast jedem Gespräch vorkommen. Ein Lösungsweg nur aus ihnen sagt nichts darüber, was das Problem gelöst hat.
ALLGEMEINE_WERKZEUGE = {"Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "AskUserQuestion", "ToolSearch", "TodoWrite", "WebSearch", "WebFetch",
                        "Agent", "Task", "Skill", "SendMessage", "NotebookEdit", "BashOutput", "KillShell", "Monitor", "ScheduleWakeup", "ListAgents"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:40]


def _reize_ok(reize: list[str]) -> list[str]:
    return sorted({t.strip() for t in reize if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.VERWALTUNG)})


def _schritte_ok(schritte) -> list[dict]:
    aus = []
    for s in schritte or []:
        if isinstance(s, str) and s.strip():
            aus.append({"tool": s.strip()[:80]})
        elif isinstance(s, dict) and str(s.get("tool", "")).strip():
            aus.append({"tool": str(s["tool"]).strip()[:80], **({"hinweis": str(s["hinweis"])[:200]} if s.get("hinweis") else {})})
    return aus[:20]


def _inhalt(anleitung: str) -> dict:
    """Eine ausführliche Anleitung (Befehle, Code) bleibt vollständig erhalten, der Hinweis zeigt nur den Anfang."""
    a = (anleitung or "").strip()
    if len(a) > g.INHALT_MAX:
        raise ValueError(f"anleitung hat {len(a)} Zeichen, erlaubt sind {g.INHALT_MAX}")
    return {"inhalt": a} if len(a) > 600 else {}


def neu(name: str, reize: list[str], schritte, anleitung: str, grund: str, belege: list[str], instanz: str,
        quelle: str = "", oid: str | None = None, wer: str | None = None) -> g.Objekt:
    n = _slug(name)
    if len(n) < 2:
        raise ValueError("name: mindestens 2 Zeichen a-z, 0-9, -")
    rz = _reize_ok(reize)
    if not rz:
        raise ValueError("mindestens ein Reiz (Hashtag art:wert), an dem der Skill erscheint")
    st = _schritte_ok(schritte)
    if not st:
        raise ValueError("mindestens ein Schritt (Werkzeugname)")
    if len((anleitung or "").strip()) < 10 or len((grund or "").strip()) < 5:
        raise ValueError("anleitung (der Lösungsweg, mindestens 10 Zeichen) und grund sind Pflicht")
    oid = oid or f"skill:{n}"
    alt = g.lade(oid)
    if alt and alt.art == "skill":
        return weiterentwickeln(alt, st, anleitung, grund, belege, instanz, wer)
    o = g.neues_objekt("skill", anleitung.strip()[:600], rz + [f"skill:{n}", "modus:test"],
                       {"name": n, "problem": {"reize": rz}, "loesung": {"schritte": st, "text": anleitung.strip()[:600]}, **_inhalt(anleitung),
                        "version": 1, "versionen": [{"version": 1, "zeit": g.jetzt(), "wer": wer or f"ki@{instanz}", "grund": grund.strip()[:300],
                                                     "belege": list(belege or [])[:50]}],
                        "belege": list(belege or [])[:200], "quelle": (quelle or grund).strip()[:300]},
                       wichtigkeit=2, wer=wer or f"ki@{instanz}", oid=oid, modus="test", grund=grund, instanz=instanz)
    for b in belege or []:
        o.verknuepfe(b, "Beleg (Lösung)")
    return o


def weiterentwickeln(o: g.Objekt, schritte, anleitung: str, grund: str, belege: list[str], instanz: str, wer: str | None = None) -> g.Objekt:
    """Neue Version: Schritte, die noch fehlen, kommen hinten dazu; Anleitung wird ersetzt, alte steht in der Version."""
    st = _schritte_ok(schritte)
    vorhanden = {s["tool"] for s in o.daten["loesung"]["schritte"]}
    o.daten["loesung"]["schritte"] += [s for s in st if s["tool"] not in vorhanden]
    o.daten["versionen"].append({"version": o.daten["version"] + 1, "zeit": g.jetzt(), "wer": wer or f"ki@{instanz}", "grund": grund.strip()[:300],
                                 "belege": list(belege or [])[:50], "vorher_text": o.daten["loesung"]["text"]})
    o.daten["version"] += 1
    if (anleitung or "").strip():
        o.daten["loesung"]["text"] = anleitung.strip()[:600]
        o.text = o.daten["loesung"]["text"]
        o.daten.pop("inhalt", None)
        o.daten.update(_inhalt(anleitung))
    o.daten["belege"] = (o.daten.get("belege", []) + [b for b in belege or [] if b not in o.daten.get("belege", [])])[:200]
    o.aendere(wer or f"ki@{instanz}", f"Version {o.daten['version']}", grund)
    g.speichere(o)
    for b in belege or []:
        o.verknuepfe(b, "Beleg (Lösung)")
    return o


def fusion(a_id: str, b_id: str, name: str, grund: str, instanz: str) -> g.Objekt:
    a, b = g.lade(a_id), g.lade(b_id)
    for x, xid in ((a, a_id), (b, b_id)):
        if not x or x.art != "skill":
            raise ValueError(f"{xid} ist kein Skill")
        if x.modus == "aufgegangen":
            raise ValueError(f"{xid} ist bereits aufgegangen in {x.daten.get('aufgegangen_in')}")
        if x.modus == "quarantaene":
            raise ValueError(f"{xid} liegt in der Quarantäne")
    if a.id == b.id:
        raise ValueError("ein Skill kann nicht mit sich selbst zusammengeführt werden")
    reize = sorted(set(a.daten["problem"]["reize"]) | set(b.daten["problem"]["reize"]))
    schritte = list(a.daten["loesung"]["schritte"]) + [s for s in b.daten["loesung"]["schritte"] if s["tool"] not in {x["tool"] for x in a.daten["loesung"]["schritte"]}]
    anleitung = f"{a.daten['loesung']['text']} — {b.daten['loesung']['text']}"[:600]
    belege = sorted(set(a.daten.get("belege", [])) | set(b.daten.get("belege", [])))
    neu_o = neu(name, reize, schritte, anleitung, f"Fusion aus {a.id} und {b.id}: {grund}", belege, instanz,
                quelle=f"Fusion {a.id} + {b.id}")
    neu_o.daten["fusion_aus"] = [a.id, b.id]
    if "herkunft:p2p" in a.hashtags or "herkunft:p2p" in b.hashtags:  # die Herkunft überlebt die Fusion
        neu_o.hashtags = sorted(set(neu_o.hashtags) | {"herkunft:p2p"})
    g.speichere(neu_o)
    for x in (a, b):
        x.modus = "aufgegangen"
        x.daten["aufgegangen_in"] = neu_o.id
        x.hashtags = [t for t in x.hashtags if not t.startswith(("modus:", "fusion:"))] + ["modus:aufgegangen"]
        x.aendere(f"ki@{instanz}", f"aufgegangen in {neu_o.id}", grund)
        g.speichere(x)
        neu_o.verknuepfe(x.id, "hervorgegangen aus")
    return neu_o


def zeile(o: g.Objekt) -> str:
    from . import bandit
    schritte = " → ".join(s["tool"] for s in o.daten["loesung"]["schritte"][:6])
    return (f"Skill „{o.daten['name']}“ v{o.daten['version']} ({o.modus}, von {o.instanz}, {bandit.zeile(o)}): {o.text[:200]}"
            f" — Schritte: {schritte}")


# ── Schlaf-Schritte ───────────────────────────────────────────────────────────

def aus_erholung(seit: str) -> dict:
    """4c: Erfolg nach Fehlern desselben Werkzeugs im selben Gespräch → Skill (test) oder neue Version."""
    neu_n = weiter_n = 0
    with g.sperre:
        erholt = g.db().execute(
            "SELECT o.id FROM objekt o JOIN tag t ON t.objekt_id = o.id AND t.tag = 'ueberraschung:erholt' "
            "WHERE o.art = 'erfahrung' AND o.zeit > ? AND o.gespraech IS NOT NULL ORDER BY o.zeit", (seit,)).fetchall()
    for (eid,) in erholt:
        e = g.lade(eid)
        tool = next((t[5:] for t in e.hashtags if t.startswith("tool:")), None)
        if not tool or not e.gespraech:
            continue
        with g.sperre:
            rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND gespraech = ? AND zeit < ? ORDER BY zeit", (e.gespraech, e.zeit)).fetchall()
        episode = [g.lade(r[0]) for r in rows]
        fehler_idx = [i for i, x in enumerate(episode) if x and f"tool:{tool}" in x.hashtags and "ok:nein" in x.hashtags]
        if not fehler_idx:
            continue
        weg = [x for x in episode[fehler_idx[0]:] if x] + [e]
        schritte = []
        for x in weg:
            t = next((tg[5:] for tg in x.hashtags if tg.startswith("tool:")), None)
            if t and (not schritte or schritte[-1] != t):
                schritte.append(t)
        sig = next((tg for tg in episode[fehler_idx[0]].hashtags if tg.startswith("fehler:")), None)
        reize = sorted({tg for x in weg for tg in x.hashtags if tg.startswith(("host:", "thema:"))} | {f"tool:{tool}", f"skill:{tool.split('_')[0]}"} | ({sig} if sig else set()))
        if not _hat_inhalt(tool, schritte):
            continue  # „Bash scheiterte und gelang danach“ ohne weiteren Schritt ist kein Wissen, nur der Normalfall
        name = f"auto-{g.hashwert(tool, sig or '', 'erholung')[:12]}"
        anleitung = (f"{tool} scheiterte ({sig[7:] if sig else 'Fehler'}) und gelang danach im selben Gespräch — Lösungsweg: "
                     + " → ".join(schritte))
        vorher = g.lade(f"skill:{name}")
        o = neu(name, reize, schritte, anleitung, f"Schlaf: Erholung in Gespräch {e.gespraech}", [x.id for x in weg], g.SERVER_INSTANZ,
                quelle=f"Schlaf: Erfahrungen {weg[0].id} … {e.id}", wer="vi")
        if vorher is None:
            neu_n += 1
        else:
            weiter_n += 1
        o.verknuepfe(e.id, "Erholung (Schlaf)")
    return {"neu": neu_n, "weiterentwickelt": weiter_n}


def _hat_inhalt(tool: str, schritte) -> bool:
    """Ein Erholungsweg sagt etwas, wenn zwischen Fehler und Erfolg ein anderer Schritt lag. Bash zählt dabei nur, wenn nicht Bash selbst gescheitert ist
    (dann wurde am System etwas getan); Lesen, Schreiben, Rückfragen kommen in fast jedem Gespräch vor."""
    allgemein = ALLGEMEINE_WERKZEUGE - ({"Bash"} if tool != "Bash" else set())
    return bool(set(schritte) - allgemein - {tool})


def inhaltsleer(o: g.Objekt) -> bool:
    """Ein automatischer Erholungs-Skill ohne aussagekräftigen Schritt."""
    if not o.daten.get("name", "").startswith("auto-"):
        return False
    tool = next((r[5:] for r in (o.daten.get("problem") or {}).get("reize", []) if r.startswith("tool:")), "")
    return not _hat_inhalt(tool, [s.get("tool") for s in (o.daten.get("loesung") or {}).get("schritte", [])])


def bewerte() -> dict:
    """Skills, die wiederholt scheitern und nie nützen → strittig (benannt), nicht gelöscht. Inhaltsleere automatische Skills → widerlegt."""
    from . import bandit
    strittig = 0
    for _, o, _g in g.erinnere("art:skill (modus:test OR modus:aktiv OR modus:strittig)", limit=500, betrachter=None):
        if inhaltsleer(o):
            o.modus = "widerlegt"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:widerlegt"]
            o.aendere("vi", "widerlegt", "Schlaf: Lösungsweg besteht nur aus allgemeinen Werkzeugen; „genützt“ zählte nur, dass das Werkzeug ohnehin meist gelingt")
            g.speichere(o)
    for _, o, _g in g.erinnere("art:skill (modus:test OR modus:aktiv)", limit=500, betrachter=None):
        ja, nein = bandit.zaehler(o)
        if nein >= SCHLECHT_AB and (ja / (ja + nein)) < SCHLECHT_QUOTE and o.modus != "strittig":
            o.modus = "strittig"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:strittig"]
            o.aendere("vi", "strittig", f"Schlaf: genützt {ja}, nicht genützt {nein} — Lösungsweg prüfen oder widerlegen")
            g.speichere(o)
            strittig += 1
    return {"strittig": strittig}


def fusions_vorschlaege() -> dict:
    """Gleicher Problem-Schlüssel (tool + Fehlersignatur) bei zwei Skills → fusion:vorschlag + Kante. Entscheidet eine Instanz."""
    skills = [o for _, o, _g in g.erinnere("art:skill !modus:aufgegangen", limit=500, betrachter=None)]
    nach_schluessel: dict[tuple, list[g.Objekt]] = {}
    for o in skills:
        tools = tuple(sorted(t for t in o.daten["problem"]["reize"] if t.startswith("tool:")))
        fehler = tuple(sorted(t for t in o.daten["problem"]["reize"] if t.startswith("fehler:")))
        if tools:
            nach_schluessel.setdefault((tools, fehler), []).append(o)
    n = 0
    for gruppe in nach_schluessel.values():
        if len(gruppe) < 2:
            continue
        for o in gruppe:
            andere = [x.id for x in gruppe if x.id != o.id]
            if "fusion:vorschlag" not in o.hashtags:
                o.hashtags = o.hashtags + ["fusion:vorschlag"]
                o.aendere("vi", "fusion:vorschlag", f"Schlaf: gleiches Problem wie {', '.join(andere)} — vi_skill_fusion entscheidet eine Instanz")
                g.speichere(o)
                n += 1
            for a in andere:
                o.verknuepfe(a, "gleiches Problem (Fusionsvorschlag)")
    return {"vorschlaege": n}
