"""Reflexe — Python-Code, den die VI sich selbst ins Gedächtnis schreibt.

Drei Arten (erschöpfend):
  werkzeug  `TOOL = {description, inputSchema}` + `def run(args) -> str`      → MCP-Werkzeug `vi_reflex_<name>`
  vorher    `def run(tool, args) -> None | {"hinweis": str} | {"args": dict}` → läuft in `vi_before` (Hook)
  nachher   `def run(tool, args, ergebnis) -> None | str`                     → läuft in `vi_after` (Hook)

Modi: `test` (nur Hinweis, Start), `aktiv` (wirkt), `aus`, `defekt` (nach REFLEX_FEHLER_AB Fehlern, benannt).
Schutz: AST-Prüfung (Import-Whitelist, kein exec/eval/open/…) als erste Schranke; seit 0.9.0 läuft jeder Lauf in
einem eigenen Prozess (sandbox.py: Landlock + seccomp, Ressourcengrenzen, kein Netz, keine Dateien, keine Kindprozesse)
als zweite; ist die Sandbox nicht herstellbar, läuft der Code nicht. Lernen/schalten dürfen weiter nur Instanzen mit `reflexe: true`.
"""
from __future__ import annotations

import ast
import json
import threading

from . import memory as g
from . import checks, sandbox
from .log_output import log

REFLEX_KINDS = ("werkzeug", "vorher", "nachher")
REFLEX_ERRORS_MIN = 3
REFLEX_TIME_S = 10
REFLEX_MODULE = frozenset({"json", "re", "math", "statistics", "collections", "itertools", "datetime", "urllib.parse",
                           "textwrap", "functools", "operator", "string", "difflib", "hashlib", "base64"})
_FORBIDDEN_NAMES = ("exec", "eval", "open", "__import__", "compile", "globals", "locals", "vars", "getattr", "setattr",
                   "delattr", "breakpoint", "input")
_FORBIDDEN_ATTR = ("system", "popen", "spawn", "fork", "remove", "unlink", "rmtree")

loaded: dict[str, dict] = {}
_lock = threading.Lock()


def check(code: str, kind: str) -> str:
    """Leerer String = in Ordnung, sonst der Grund der Ablehnung."""
    if kind not in REFLEX_KINDS:
        return f"art muss {', '.join(REFLEX_KINDS)} sein"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntaxfehler Zeile {e.lineno}: {e.msg}"
    allowed = {m.split(".")[0] for m in REFLEX_MODULE}
    for k in ast.walk(tree):
        if isinstance(k, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in k.names] if isinstance(k, ast.Import) else [k.module or ""]
            foreign = [n for n in names if n.split(".")[0] not in allowed]
            if foreign:
                return f"Import {', '.join(foreign)} nicht erlaubt (erlaubt: {', '.join(sorted(REFLEX_MODULE))})"
        if isinstance(k, ast.Name) and k.id in _FORBIDDEN_NAMES:
            return f"{k.id} ist in Reflexen nicht erlaubt"
        if isinstance(k, ast.Attribute) and (k.attr in _FORBIDDEN_ATTR or k.attr.startswith("__")):
            return f".{k.attr} ist in Reflexen nicht erlaubt"
    if not any(isinstance(k, ast.FunctionDef) and k.name == "run" for k in tree.body):
        return "Reflex braucht eine Funktion run(...) auf oberster Ebene"
    if kind == "werkzeug" and not any(isinstance(k, ast.Assign) and any(getattr(t, "id", "") == "TOOL" for t in k.targets)
                                     for k in tree.body):
        return "art werkzeug braucht TOOL = {description, inputSchema} auf oberster Ebene"
    return ""


def load_all() -> dict[str, dict]:
    """Alle Reflexe im Modus aktiv/test registrieren. Das TOOL-Schema eines Werkzeug-Reflexes wird in der Sandbox
    ermittelt — kein Code läuft im Server."""
    new: dict[str, dict] = {}
    for _, o, _g in g.recall("(modus:aktiv OR modus:test)", limit=500, kinds=("reflex",)):
        if o.mode not in ("aktiv", "test"):
            continue
        schema = None
        if o.data["art"] == "werkzeug":
            res = sandbox.run(o.data["code"], [], schema_only=True)
            if "fehler" in res:
                log(f"Reflex {o.data['name']} lädt nicht ({res['isolation']}): {res['fehler']}")
                continue
            schema = res.get("schema")
        new[o.data["name"]] = {"objekt": o, "name": o.data["name"], "art": o.data["art"], "modus": o.mode, "code": o.data["code"],
                                "schema": schema}
    with _lock:
        loaded.clear()
        loaded.update(new)
    return dict(new)


def tool_schemas() -> list[dict]:
    with _lock:
        rs = list(loaded.values())
    return [{"name": f"vi_reflex_{r['name']}", "description": f"[Reflex, {r['modus']}] " + str(r["schema"].get("description") or r["objekt"].text),
             "inputSchema": r["schema"].get("inputSchema") or {"type": "object", "properties": {}}}
            for r in rs if r["art"] == "werkzeug" and isinstance(r["schema"], dict)]


def run(r: dict, *args) -> dict:
    res = sandbox.run(r["code"], list(args), wallclock_s=REFLEX_TIME_S + 2)
    o = g.load(r["objekt"].id) or r["objekt"]
    o.data["laeufe"] = o.data.get("laeufe", 0) + 1
    o.data["isolation"] = res.get("isolation")
    if res.get("isolation") == "keine":  # Umgebung, nicht der Reflex: benannt, aber kein Fehlerpunkt gegen ihn
        o.data["letzter_fehler"] = res.get("fehler", "")[:300]
    elif "fehler" in res:
        o.data["fehler"] = o.data.get("fehler", 0) + 1
        o.data["letzter_fehler"] = res["fehler"][:300]
        if o.data["fehler"] >= REFLEX_ERRORS_MIN:
            o.mode = r["modus"] = "defekt"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:defekt"]
            o.change("vi", "defekt", f"{o.data['fehler']} Fehler: {res['fehler'][:120]}")
            log(f"Reflex {r['name']} defekt: {res['fehler']}")
            with _lock:
                loaded.pop(r["name"], None)
    g.save(o)
    return res


def as_tool(name: str, args: dict) -> str:
    with _lock:
        r = loaded.get(name[len("vi_reflex_"):])
    if not r:
        raise ValueError(f"Reflex {name} nicht geladen")
    res = run(r, args)
    if "fehler" in res:
        raise RuntimeError(f"Reflex {r['name']}: {res['fehler']}")
    header = "" if r["modus"] == "aktiv" else f"[Reflex {r['name']} im Testmodus — vi_reflex_switch(name, 'aktiv') schaltet scharf]\n"
    return header + (res["wert"] if isinstance(res["wert"], str) else json.dumps(res["wert"], ensure_ascii=False, indent=2))


def before(tool: str, args: dict) -> tuple[dict, list[str]]:
    hints = []
    with _lock:
        rs = [r for r in loaded.values() if r["art"] == "vorher"]
    for r in rs:
        res = run(r, tool, dict(args))
        if "fehler" in res:
            hints.append(f"Reflex {r['name']} (vorher) scheiterte: {res['fehler']}")
            continue
        w = res.get("wert")
        if not isinstance(w, dict):
            continue
        foreign = "herkunft:p2p" in r["objekt"].hashtags
        if w.get("hinweis"):
            if foreign and checks.directives(str(w["hinweis"])):  # importierter Code darf zur Laufzeit keine Anweisungen ausgeben
                hints.append(f"Reflex {r['name']}: Hinweis enthielt ein Anweisungsmuster und wurde verworfen")
            else:
                hints.append(f"Reflex {r['name']} ({r['modus']}): {w['hinweis']}")
        if isinstance(w.get("args"), dict) and foreign:
            hints.append(f"Reflex {r['name']}: importierter Reflex darf keine Argumente ändern, verworfen")
        elif isinstance(w.get("args"), dict):
            if r["modus"] == "aktiv":
                args = w["args"]
            else:
                hints.append(f"Reflex {r['name']} (test) hätte Argumente geändert: {json.dumps(w['args'], ensure_ascii=False)[:200]}")
    return args, hints


def after(tool: str, args: dict, result: str) -> list[str]:
    hints = []
    with _lock:
        rs = [r for r in loaded.values() if r["art"] == "nachher"]
    for r in rs:
        res = run(r, tool, dict(args), result)
        if "fehler" in res:
            hints.append(f"Reflex {r['name']} (nachher) scheiterte: {res['fehler']}")
        elif isinstance(res.get("wert"), str) and res["wert"].strip():
            hints.append(f"Reflex {r['name']} ({r['modus']}): {res['wert'].strip()[:600]}")
    return hints
