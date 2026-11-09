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

from . import memory as g

BAD_FROM = 3
BAD_RATIO = 0.3

#: Werkzeuge, die in fast jedem Gespräch vorkommen. Ein Lösungsweg nur aus ihnen sagt nichts darüber, was das Problem gelöst hat.
GENERAL_TOOLS = {"Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "AskUserQuestion", "ToolSearch", "TodoWrite", "WebSearch", "WebFetch",
                        "Agent", "Task", "Skill", "SendMessage", "NotebookEdit", "BashOutput", "KillShell", "Monitor", "ScheduleWakeup", "ListAgents"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:40]


def _triggers_ok(triggers: list[str]) -> list[str]:
    return sorted({t.strip() for t in triggers if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.ADMIN_PREFIXES)})


def _steps_ok(steps) -> list[dict]:
    outputs = []
    for s in steps or []:
        if isinstance(s, str) and s.strip():
            outputs.append({"tool": s.strip()[:80]})
        elif isinstance(s, dict) and str(s.get("tool", "")).strip():
            outputs.append({"tool": str(s["tool"]).strip()[:80], **({"hinweis": str(s["hinweis"])[:200]} if s.get("hinweis") else {})})
    return outputs[:20]


def _content(instructions: str) -> dict:
    """Eine ausführliche Anleitung (Befehle, Code) bleibt vollständig erhalten, der Hinweis zeigt nur den Anfang."""
    a = (instructions or "").strip()
    if len(a) > g.CONTENT_MAX:
        raise ValueError(f"anleitung hat {len(a)} Zeichen, erlaubt sind {g.CONTENT_MAX}")
    return {"inhalt": a} if len(a) > 600 else {}


def new(name: str, triggers: list[str], steps, instructions: str, reason: str, evidence_list: list[str], instance: str,
        source: str = "", oid: str | None = None, who: str | None = None) -> g.MemoryObject:
    n = _slug(name)
    if len(n) < 2:
        raise ValueError("name: mindestens 2 Zeichen a-z, 0-9, -")
    rz = _triggers_ok(triggers)
    if not rz:
        raise ValueError("mindestens ein Reiz (Hashtag art:wert), an dem der Skill erscheint")
    st = _steps_ok(steps)
    if not st:
        raise ValueError("mindestens ein Schritt (Werkzeugname)")
    if len((instructions or "").strip()) < 10 or len((reason or "").strip()) < 5:
        raise ValueError("anleitung (der Lösungsweg, mindestens 10 Zeichen) und grund sind Pflicht")
    oid = oid or f"skill:{n}"
    old = g.load(oid)
    if old and old.kind == "skill":
        return evolve(old, st, instructions, reason, evidence_list, instance, who, triggers=rz)
    o = g.new_object("skill", instructions.strip()[:600], rz + [f"skill:{n}", "modus:test"],
                       {"name": n, "problem": {"reize": rz}, "loesung": {"schritte": st, "text": instructions.strip()[:600]}, **_content(instructions),
                        "version": 1, "versionen": [{"version": 1, "zeit": g.now(), "wer": who or f"ki@{instance}", "grund": reason.strip()[:300],
                                                     "belege": list(evidence_list or [])[:50]}],
                        "belege": list(evidence_list or [])[:200], "quelle": (source or reason).strip()[:300]},
                       importance=2, who=who or f"ki@{instance}", oid=oid, mode="test", reason=reason, instance=instance)
    for b in evidence_list or []:
        o.link(b, "Beleg (Lösung)")
    return o


def evolve(o: g.MemoryObject, steps, instructions: str, reason: str, evidence_list: list[str], instance: str, who: str | None = None,
                     triggers: list[str] | None = None) -> g.MemoryObject:
    """Neue Version: Schritte, die noch fehlen, kommen hinten dazu; Anleitung wird ersetzt, alte steht in der Version.
    0.20.11: Neue Reize ersetzen die alten (vorher blieben sie stehen — ein zu allgemeiner Reiz wie tool:Bash ließ sich nie mehr entfernen);
    die alten stehen in der Version."""
    st = _steps_ok(steps)
    triggers_before = list(o.data["problem"]["reize"])
    if triggers and sorted(triggers) != sorted(triggers_before):
        base = [t for t in o.hashtags if t not in triggers_before]
        o.hashtags = base + [t for t in triggers if t not in base]  # gegen die bereinigte Liste prüfen, sonst fallen bleibende Reize weg (0.20.12)
        o.data["problem"]["reize"] = list(triggers)
    present = {s["tool"] for s in o.data["loesung"]["schritte"]}
    o.data["loesung"]["schritte"] += [s for s in st if s["tool"] not in present]
    o.data["versionen"].append({"version": o.data["version"] + 1, "zeit": g.now(), "wer": who or f"ki@{instance}", "grund": reason.strip()[:300],
                                 "belege": list(evidence_list or [])[:50], "vorher_text": o.data["loesung"]["text"],
                                 **({"reize_vorher": triggers_before} if o.data["problem"]["reize"] != triggers_before else {})})
    o.data["version"] += 1
    if (instructions or "").strip():
        o.data["loesung"]["text"] = instructions.strip()[:600]
        o.text = o.data["loesung"]["text"]
        o.data.pop("inhalt", None)
        o.data.update(_content(instructions))
    o.data["belege"] = (o.data.get("belege", []) + [b for b in evidence_list or [] if b not in o.data.get("belege", [])])[:200]
    o.change(who or f"ki@{instance}", f"Version {o.data['version']}", reason)
    g.save(o)
    for b in evidence_list or []:
        o.link(b, "Beleg (Lösung)")
    return o


def fusion(a_id: str, b_id: str, name: str, reason: str, instance: str) -> g.MemoryObject:
    a, b = g.load(a_id), g.load(b_id)
    for x, xid in ((a, a_id), (b, b_id)):
        if not x or x.kind != "skill":
            raise ValueError(f"{xid} ist kein Skill")
        if x.mode == "aufgegangen":
            raise ValueError(f"{xid} ist bereits aufgegangen in {x.data.get('aufgegangen_in')}")
        if x.mode == "quarantaene":
            raise ValueError(f"{xid} liegt in der Quarantäne")
    if a.id == b.id:
        raise ValueError("ein Skill kann nicht mit sich selbst zusammengeführt werden")
    triggers = sorted(set(a.data["problem"]["reize"]) | set(b.data["problem"]["reize"]))
    steps = list(a.data["loesung"]["schritte"]) + [s for s in b.data["loesung"]["schritte"] if s["tool"] not in {x["tool"] for x in a.data["loesung"]["schritte"]}]
    instructions = f"{a.data['loesung']['text']} — {b.data['loesung']['text']}"[:600]
    evidence_list = sorted(set(a.data.get("belege", [])) | set(b.data.get("belege", [])))
    new_o = new(name, triggers, steps, instructions, f"Fusion aus {a.id} und {b.id}: {reason}", evidence_list, instance,
                source=f"Fusion {a.id} + {b.id}")
    new_o.data["fusion_aus"] = [a.id, b.id]
    if "herkunft:p2p" in a.hashtags or "herkunft:p2p" in b.hashtags:  # die Herkunft überlebt die Fusion
        new_o.hashtags = sorted(set(new_o.hashtags) | {"herkunft:p2p"})
    g.save(new_o)
    for x in (a, b):
        x.mode = "aufgegangen"
        x.data["aufgegangen_in"] = new_o.id
        x.hashtags = [t for t in x.hashtags if not t.startswith(("modus:", "fusion:"))] + ["modus:aufgegangen"]
        x.change(f"ki@{instance}", f"aufgegangen in {new_o.id}", reason)
        g.save(x)
        new_o.link(x.id, "hervorgegangen aus")
    return new_o


def line(o: g.MemoryObject) -> str:
    from . import bandit
    steps = " → ".join(s["tool"] for s in o.data["loesung"]["schritte"][:6])
    return (f"Skill „{o.data['name']}“ v{o.data['version']} ({o.mode}, von {o.instance}, {bandit.line(o)}): {o.text[:200]}"
            f" — Schritte: {steps}")


# ── Schlaf-Schritte ───────────────────────────────────────────────────────────

def from_recovery(since: str) -> dict:
    """4c: Erfolg nach Fehlern desselben Werkzeugs im selben Gespräch → Skill (test) oder neue Version."""
    new_n = evolved_n = 0
    with g.lock:
        recovered = g.db().execute(
            "SELECT o.id FROM objekt o JOIN tag t ON t.objekt_id = o.id AND t.tag = 'ueberraschung:erholt' "
            "WHERE o.art = 'erfahrung' AND o.zeit > ? AND o.gespraech IS NOT NULL ORDER BY o.zeit", (since,)).fetchall()
    for (eid,) in recovered:
        e = g.load(eid)
        tool = next((t[5:] for t in e.hashtags if t.startswith("tool:")), None)
        if not tool or not e.conversation:
            continue
        with g.lock:
            rows = g.db().execute("SELECT id FROM objekt WHERE art = 'erfahrung' AND gespraech = ? AND zeit < ? ORDER BY zeit", (e.conversation, e.ts)).fetchall()
        episode = [g.load(r[0]) for r in rows]
        error_idx = [i for i, x in enumerate(episode) if x and f"tool:{tool}" in x.hashtags and "ok:nein" in x.hashtags]
        if not error_idx:
            continue
        remove = [x for x in episode[error_idx[0]:] if x] + [e]
        steps = []
        for x in remove:
            t = next((tg[5:] for tg in x.hashtags if tg.startswith("tool:")), None)
            if t and (not steps or steps[-1] != t):
                steps.append(t)
        sig = next((tg for tg in episode[error_idx[0]].hashtags if tg.startswith("fehler:")), None)
        triggers = sorted({tg for x in remove for tg in x.hashtags if tg.startswith(("host:", "thema:"))} | {f"tool:{tool}", f"skill:{tool.split('_')[0]}"} | ({sig} if sig else set()))
        if not _has_content(tool, steps):
            continue  # „Bash scheiterte und gelang danach“ ohne weiteren Schritt ist kein Wissen, nur der Normalfall
        name = f"auto-{g.hash_value(tool, sig or '', 'erholung')[:12]}"
        instructions = (f"{tool} scheiterte ({sig[7:] if sig else 'Fehler'}) und gelang danach im selben Gespräch — Lösungsweg: "
                     + " → ".join(steps))
        before = g.load(f"skill:{name}")
        o = new(name, triggers, steps, instructions, f"Schlaf: Erholung in Gespräch {e.conversation}", [x.id for x in remove], g.SERVER_INSTANCE,
                source=f"Schlaf: Erfahrungen {remove[0].id} … {e.id}", who="vi")
        if before is None:
            new_n += 1
        else:
            evolved_n += 1
        o.link(e.id, "Erholung (Schlaf)")
    return {"neu": new_n, "weiterentwickelt": evolved_n}


def _has_content(tool: str, steps) -> bool:
    """Ein Erholungsweg sagt etwas, wenn zwischen Fehler und Erfolg ein anderer Schritt lag. Bash zählt dabei nur, wenn nicht Bash selbst gescheitert ist
    (dann wurde am System etwas getan); Lesen, Schreiben, Rückfragen kommen in fast jedem Gespräch vor."""
    general = GENERAL_TOOLS - ({"Bash"} if tool != "Bash" else set())
    return bool(set(steps) - general - {tool})


def content_empty(o: g.MemoryObject) -> bool:
    """Ein automatischer Erholungs-Skill ohne aussagekräftigen Schritt."""
    if not o.data.get("name", "").startswith("auto-"):
        return False
    tool = next((r[5:] for r in (o.data.get("problem") or {}).get("reize", []) if r.startswith("tool:")), "")
    return not _has_content(tool, [s.get("tool") for s in (o.data.get("loesung") or {}).get("schritte", [])])


def rate() -> dict:
    """Skills, die wiederholt scheitern und nie nützen → strittig (benannt), nicht gelöscht. Inhaltsleere automatische Skills → widerlegt."""
    from . import bandit
    disputed = 0
    for _, o, _g in g.recall("art:skill (modus:test OR modus:aktiv OR modus:strittig)", limit=500, viewer=None):
        if content_empty(o):
            o.mode = "widerlegt"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:widerlegt"]
            o.change("vi", "widerlegt", "Schlaf: Lösungsweg besteht nur aus allgemeinen Werkzeugen; „genützt“ zählte nur, dass das Werkzeug ohnehin meist gelingt")
            g.save(o)
    for _, o, _g in g.recall("art:skill (modus:test OR modus:aktiv)", limit=500, viewer=None):
        yes, no = bandit.counter(o)
        if bandit.shown(o) >= BAD_FROM and bandit.expectation(o) < BAD_RATIO and o.mode != "strittig":
            o.mode = "strittig"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:strittig"]
            o.change("vi", "strittig", f"Schlaf: genützt {yes}, nicht genützt {no} — Lösungsweg prüfen oder widerlegen")
            g.save(o)
            disputed += 1
    return {"strittig": disputed}


def fusion_proposals() -> dict:
    """Gleicher Problem-Schlüssel (tool + Fehlersignatur) bei zwei Skills → fusion:vorschlag + Kante. Entscheidet eine Instanz."""
    skills = [o for _, o, _g in g.recall("art:skill !modus:aufgegangen", limit=500, viewer=None)]
    by_key: dict[tuple, list[g.MemoryObject]] = {}
    for o in skills:
        tools = tuple(sorted(t for t in o.data["problem"]["reize"] if t.startswith("tool:")))
        error = tuple(sorted(t for t in o.data["problem"]["reize"] if t.startswith("fehler:")))
        if tools:
            by_key.setdefault((tools, error), []).append(o)
    n = 0
    for group in by_key.values():
        if len(group) < 2:
            continue
        for o in group:
            others = [x.id for x in group if x.id != o.id]
            if "fusion:vorschlag" not in o.hashtags:
                o.hashtags = o.hashtags + ["fusion:vorschlag"]
                o.change("vi", "fusion:vorschlag", f"Schlaf: gleiches Problem wie {', '.join(others)} — vi_skill_fusion entscheidet eine Instanz")
                g.save(o)
                n += 1
            for a in others:
                o.link(a, "gleiches Problem (Fusionsvorschlag)")
    return {"vorschlaege": n}
