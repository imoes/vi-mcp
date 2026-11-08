"""Reflexe — Python-Code, den die VI sich selbst ins Gedächtnis schreibt.

Drei Arten (erschöpfend):
  werkzeug  `TOOL = {description, inputSchema}` + `def run(args) -> str`      → MCP-Werkzeug `vi_reflex_<name>`
  vorher    `def run(tool, args) -> None | {"hinweis": str} | {"args": dict}` → läuft in `vi_vorher` (Hook)
  nachher   `def run(tool, args, ergebnis) -> None | str`                     → läuft in `vi_nachher` (Hook)

Modi: `test` (nur Hinweis, Start), `aktiv` (wirkt), `aus`, `defekt` (nach REFLEX_FEHLER_AB Fehlern, benannt).
Schutz: AST-Prüfung (Import-Whitelist, kein exec/eval/open/…) als erste Schranke; seit 0.9.0 läuft jeder Lauf in
einem eigenen Prozess (sandbox.py: Landlock + seccomp, Ressourcengrenzen, kein Netz, keine Dateien, keine Kindprozesse)
als zweite; ist die Sandbox nicht herstellbar, läuft der Code nicht. Lernen/schalten dürfen weiter nur Instanzen mit `reflexe: true`.
"""
from __future__ import annotations

import ast
import json
import threading

from . import gedaechtnis as g
from . import pruefung, sandbox
from .protokoll import log

REFLEX_ARTEN = ("werkzeug", "vorher", "nachher")
REFLEX_FEHLER_AB = 3
REFLEX_ZEIT_S = 10
REFLEX_MODULE = frozenset({"json", "re", "math", "statistics", "collections", "itertools", "datetime", "urllib.parse",
                           "textwrap", "functools", "operator", "string", "difflib", "hashlib", "base64"})
_VERBOTEN_NAMEN = ("exec", "eval", "open", "__import__", "compile", "globals", "locals", "vars", "getattr", "setattr",
                   "delattr", "breakpoint", "input")
_VERBOTEN_ATTR = ("system", "popen", "spawn", "fork", "remove", "unlink", "rmtree")

geladen: dict[str, dict] = {}
_sperre = threading.Lock()


def pruefe(code: str, art: str) -> str:
    """Leerer String = in Ordnung, sonst der Grund der Ablehnung."""
    if art not in REFLEX_ARTEN:
        return f"art muss {', '.join(REFLEX_ARTEN)} sein"
    try:
        baum = ast.parse(code)
    except SyntaxError as e:
        return f"Syntaxfehler Zeile {e.lineno}: {e.msg}"
    erlaubt = {m.split(".")[0] for m in REFLEX_MODULE}
    for k in ast.walk(baum):
        if isinstance(k, (ast.Import, ast.ImportFrom)):
            namen = [a.name for a in k.names] if isinstance(k, ast.Import) else [k.module or ""]
            fremd = [n for n in namen if n.split(".")[0] not in erlaubt]
            if fremd:
                return f"Import {', '.join(fremd)} nicht erlaubt (erlaubt: {', '.join(sorted(REFLEX_MODULE))})"
        if isinstance(k, ast.Name) and k.id in _VERBOTEN_NAMEN:
            return f"{k.id} ist in Reflexen nicht erlaubt"
        if isinstance(k, ast.Attribute) and (k.attr in _VERBOTEN_ATTR or k.attr.startswith("__")):
            return f".{k.attr} ist in Reflexen nicht erlaubt"
    if not any(isinstance(k, ast.FunctionDef) and k.name == "run" for k in baum.body):
        return "Reflex braucht eine Funktion run(...) auf oberster Ebene"
    if art == "werkzeug" and not any(isinstance(k, ast.Assign) and any(getattr(t, "id", "") == "TOOL" for t in k.targets)
                                     for k in baum.body):
        return "art werkzeug braucht TOOL = {description, inputSchema} auf oberster Ebene"
    return ""


def lade_alle() -> dict[str, dict]:
    """Alle Reflexe im Modus aktiv/test registrieren. Das TOOL-Schema eines Werkzeug-Reflexes wird in der Sandbox
    ermittelt — kein Code läuft im Server."""
    neu: dict[str, dict] = {}
    for _, o, _g in g.erinnere("(modus:aktiv OR modus:test)", limit=500, arten=("reflex",)):
        if o.modus not in ("aktiv", "test"):
            continue
        schema = None
        if o.daten["art"] == "werkzeug":
            erg = sandbox.lauf(o.daten["code"], [], nur_schema=True)
            if "fehler" in erg:
                log(f"Reflex {o.daten['name']} lädt nicht ({erg['isolation']}): {erg['fehler']}")
                continue
            schema = erg.get("schema")
        neu[o.daten["name"]] = {"objekt": o, "name": o.daten["name"], "art": o.daten["art"], "modus": o.modus, "code": o.daten["code"],
                                "schema": schema}
    with _sperre:
        geladen.clear()
        geladen.update(neu)
    return dict(neu)


def werkzeug_schemas() -> list[dict]:
    with _sperre:
        rs = list(geladen.values())
    return [{"name": f"vi_reflex_{r['name']}", "description": f"[Reflex, {r['modus']}] " + str(r["schema"].get("description") or r["objekt"].text),
             "inputSchema": r["schema"].get("inputSchema") or {"type": "object", "properties": {}}}
            for r in rs if r["art"] == "werkzeug" and isinstance(r["schema"], dict)]


def lauf(r: dict, *args) -> dict:
    erg = sandbox.lauf(r["code"], list(args), wanduhr_s=REFLEX_ZEIT_S + 2)
    o = g.lade(r["objekt"].id) or r["objekt"]
    o.daten["laeufe"] = o.daten.get("laeufe", 0) + 1
    o.daten["isolation"] = erg.get("isolation")
    if erg.get("isolation") == "keine":  # Umgebung, nicht der Reflex: benannt, aber kein Fehlerpunkt gegen ihn
        o.daten["letzter_fehler"] = erg.get("fehler", "")[:300]
    elif "fehler" in erg:
        o.daten["fehler"] = o.daten.get("fehler", 0) + 1
        o.daten["letzter_fehler"] = erg["fehler"][:300]
        if o.daten["fehler"] >= REFLEX_FEHLER_AB:
            o.modus = r["modus"] = "defekt"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:defekt"]
            o.aendere("vi", "defekt", f"{o.daten['fehler']} Fehler: {erg['fehler'][:120]}")
            log(f"Reflex {r['name']} defekt: {erg['fehler']}")
            with _sperre:
                geladen.pop(r["name"], None)
    g.speichere(o)
    return erg


def als_werkzeug(name: str, args: dict) -> str:
    with _sperre:
        r = geladen.get(name[len("vi_reflex_"):])
    if not r:
        raise ValueError(f"Reflex {name} nicht geladen")
    erg = lauf(r, args)
    if "fehler" in erg:
        raise RuntimeError(f"Reflex {r['name']}: {erg['fehler']}")
    kopf = "" if r["modus"] == "aktiv" else f"[Reflex {r['name']} im Testmodus — vi_reflex_schalte(name, 'aktiv') schaltet scharf]\n"
    return kopf + (erg["wert"] if isinstance(erg["wert"], str) else json.dumps(erg["wert"], ensure_ascii=False, indent=2))


def vorher(tool: str, args: dict) -> tuple[dict, list[str]]:
    hinweise = []
    with _sperre:
        rs = [r for r in geladen.values() if r["art"] == "vorher"]
    for r in rs:
        erg = lauf(r, tool, dict(args))
        if "fehler" in erg:
            hinweise.append(f"Reflex {r['name']} (vorher) scheiterte: {erg['fehler']}")
            continue
        w = erg.get("wert")
        if not isinstance(w, dict):
            continue
        fremd = "herkunft:p2p" in r["objekt"].hashtags
        if w.get("hinweis"):
            if fremd and pruefung.anweisungen(str(w["hinweis"])):  # importierter Code darf zur Laufzeit keine Anweisungen ausgeben
                hinweise.append(f"Reflex {r['name']}: Hinweis enthielt ein Anweisungsmuster und wurde verworfen")
            else:
                hinweise.append(f"Reflex {r['name']} ({r['modus']}): {w['hinweis']}")
        if isinstance(w.get("args"), dict) and fremd:
            hinweise.append(f"Reflex {r['name']}: importierter Reflex darf keine Argumente ändern, verworfen")
        elif isinstance(w.get("args"), dict):
            if r["modus"] == "aktiv":
                args = w["args"]
            else:
                hinweise.append(f"Reflex {r['name']} (test) hätte Argumente geändert: {json.dumps(w['args'], ensure_ascii=False)[:200]}")
    return args, hinweise


def nachher(tool: str, args: dict, ergebnis: str) -> list[str]:
    hinweise = []
    with _sperre:
        rs = [r for r in geladen.values() if r["art"] == "nachher"]
    for r in rs:
        erg = lauf(r, tool, dict(args), ergebnis)
        if "fehler" in erg:
            hinweise.append(f"Reflex {r['name']} (nachher) scheiterte: {erg['fehler']}")
        elif isinstance(erg.get("wert"), str) and erg["wert"].strip():
            hinweise.append(f"Reflex {r['name']} ({r['modus']}): {erg['wert'].strip()[:600]}")
    return hinweise
