"""Reflexes — Python code that the VI writes into its own memory.

Three kinds (exhaustive):
  werkzeug  `TOOL = {description, inputSchema}` + `def run(args) -> str`      → MCP tool `vi_reflex_<name>`
  vorher    `def run(tool, args) -> None | {"hinweis": str} | {"args": dict}` → runs in `vi_before` (hook)
  nachher   `def run(tool, args, ergebnis) -> None | str`                     → runs in `vi_after` (hook)

Modes: `test` (hint only, start), `aktiv` (takes effect), `aus`, `defekt` (after REFLEX_ERRORS_MIN errors, named).
Protection: AST check (import whitelist, no exec/eval/open/…) as the first barrier; since 0.9.0 every run happens in
its own process (sandbox.py: Landlock + seccomp, resource limits, no network, no files, no child processes)
as the second; if the sandbox cannot be set up, the code does not run. Only instances with `reflexe: true` may learn/switch.
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
    """Empty string = in order, otherwise the reason for rejection."""
    if kind not in REFLEX_KINDS:
        return f"art must be {', '.join(REFLEX_KINDS)}"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error line {e.lineno}: {e.msg}"
    allowed = {m.split(".")[0] for m in REFLEX_MODULE}
    for k in ast.walk(tree):
        if isinstance(k, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in k.names] if isinstance(k, ast.Import) else [k.module or ""]
            foreign = [n for n in names if n.split(".")[0] not in allowed]
            if foreign:
                return f"import {', '.join(foreign)} not allowed (allowed: {', '.join(sorted(REFLEX_MODULE))})"
        if isinstance(k, ast.Name) and k.id in _FORBIDDEN_NAMES:
            return f"{k.id} is not allowed in reflexes"
        if isinstance(k, ast.Attribute) and (k.attr in _FORBIDDEN_ATTR or k.attr.startswith("__")):
            return f".{k.attr} is not allowed in reflexes"
    if not any(isinstance(k, ast.FunctionDef) and k.name == "run" for k in tree.body):
        return "a reflex needs a function run(...) at top level"
    if kind == "werkzeug" and not any(isinstance(k, ast.Assign) and any(getattr(t, "id", "") == "TOOL" for t in k.targets)
                                     for k in tree.body):
        return "art werkzeug needs TOOL = {description, inputSchema} at top level"
    return ""


def load_all() -> dict[str, dict]:
    """Register all reflexes in mode aktiv/test. The TOOL schema of a tool reflex is determined in the sandbox
    — no code runs in the server."""
    new: dict[str, dict] = {}
    for _, o, _g in g.recall("(modus:aktiv OR modus:test)", limit=500, kinds=("reflex",)):
        if o.mode not in ("aktiv", "test"):
            continue
        schema = None
        if o.data["art"] == "werkzeug":
            res = sandbox.run(o.data["code"], [], schema_only=True)
            if "fehler" in res:
                log(f"reflex {o.data['name']} does not load ({res['isolation']}): {res['fehler']}")
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
    if res.get("isolation") == "keine":  # the environment, not the reflex: named, but no error point against it
        o.data["letzter_fehler"] = res.get("fehler", "")[:300]
    elif "fehler" in res:
        o.data["fehler"] = o.data.get("fehler", 0) + 1
        o.data["letzter_fehler"] = res["fehler"][:300]
        if o.data["fehler"] >= REFLEX_ERRORS_MIN:
            o.mode = r["modus"] = "defekt"
            o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:defekt"]
            o.change("vi", "defective", f"{o.data['fehler']} errors: {res['fehler'][:120]}")
            log(f"reflex {r['name']} defective: {res['fehler']}")
            with _lock:
                loaded.pop(r["name"], None)
    g.save(o)
    return res


def as_tool(name: str, args: dict) -> str:
    with _lock:
        r = loaded.get(name[len("vi_reflex_"):])
    if not r:
        raise ValueError(f"reflex {name} not loaded")
    res = run(r, args)
    if "fehler" in res:
        raise RuntimeError(f"Reflex {r['name']}: {res['fehler']}")
    header = "" if r["modus"] == "aktiv" else f"[Reflex {r['name']} in test mode — vi_reflex_switch(name, 'aktiv') makes it live]\n"
    return header + (res["wert"] if isinstance(res["wert"], str) else json.dumps(res["wert"], ensure_ascii=False, indent=2))


def before(tool: str, args: dict) -> tuple[dict, list[str]]:
    hints = []
    with _lock:
        rs = [r for r in loaded.values() if r["art"] == "vorher"]
    for r in rs:
        res = run(r, tool, dict(args))
        if "fehler" in res:
            hints.append(f"Reflex {r['name']} (vorher) failed: {res['fehler']}")
            continue
        w = res.get("wert")
        if not isinstance(w, dict):
            continue
        foreign = "herkunft:p2p" in r["objekt"].hashtags
        if w.get("hinweis"):
            if foreign and checks.directives(str(w["hinweis"])):  # imported code must not emit instructions at runtime
                hints.append(f"Reflex {r['name']}: hint contained an instruction pattern and was discarded")
            else:
                hints.append(f"Reflex {r['name']} ({r['modus']}): {w['hinweis']}")
        if isinstance(w.get("args"), dict) and foreign:
            hints.append(f"Reflex {r['name']}: an imported reflex may not change arguments, discarded")
        elif isinstance(w.get("args"), dict):
            if r["modus"] == "aktiv":
                args = w["args"]
            else:
                hints.append(f"Reflex {r['name']} (test) would have changed arguments: {json.dumps(w['args'], ensure_ascii=False)[:200]}")
    return args, hints


def after(tool: str, args: dict, result: str) -> list[str]:
    hints = []
    with _lock:
        rs = [r for r in loaded.values() if r["art"] == "nachher"]
    for r in rs:
        res = run(r, tool, dict(args), result)
        if "fehler" in res:
            hints.append(f"Reflex {r['name']} (nachher) failed: {res['fehler']}")
        elif isinstance(res.get("wert"), str) and res["wert"].strip():
            hints.append(f"Reflex {r['name']} ({r['modus']}): {res['wert'].strip()[:600]}")
    return hints
