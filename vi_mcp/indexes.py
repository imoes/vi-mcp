"""Indexes (0.61.0): every object belongs to exactly one index — `global` or a project / special VI such as `cue-print` or `ansible`.

The user (12.11.2026): "Es muss die Möglichkeit geben, dass man unterschiedliche Indexe anlegen kann. Z. B. um eine Spezial-VI zu trainieren
oder für Projekte … so dass man gezielt nach Projekten suchen kann." Stored as the column objekt.idx (with an SQL index), like an
OpenSearch index: one object, one index; not a hashtag, so it never leaves the server with an export.

- Which index: an explicit one wins; otherwise the project of the session (the working directory the hook sends), unless the project is
  on the ignore list; otherwise `global` (index_for).
- In a project its index comes first in search and hints, general knowledge stays visible (Vorrang, kein Ausschluss).
- An index with enough experiences gets its own router model, used only if it beats the shared one (learning.train_index).
"""
from __future__ import annotations

import re

GLOBAL = "global"
#: index names: lower case, digits, dot, dash, underscore — what server.project_name leaves of a directory name, lower-cased
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
#: project names that are no project: a home directory, the root, temporary directories
IGNORE_ALWAYS = frozenset({"", "/", "~", "tmp", "temp", "home", "root"})


def normalize(name: str | None) -> str | None:
    """A valid index name or None. Raises for a name that cannot be one (to name the reason, not to guess)."""
    if name is None:
        return None
    n = str(name).strip().lower()
    if not n:
        return None
    if not NAME.match(n):
        raise ValueError(f"index {name!r}: allowed are a-z, 0-9, '.', '-', '_' (at most 48, starting with a letter or digit)")
    return n


_CFG: dict = {"t": -1e9, "v": {}}
CFG_TTL_S = 60


def _config() -> dict:
    """config.json → indexes ({map, ignore}); read at most once a minute (session.on_behalf asks per request)."""
    import time
    if time.monotonic() - _CFG["t"] < CFG_TTL_S:
        return _CFG["v"]
    try:
        from . import config
        v = config.read_raw(config.fpath()).get("indexes") or {}
    except Exception:  # noqa: BLE001 — no configuration: no mapping
        v = {}
    _CFG.update(t=time.monotonic(), v=v)
    return v


def from_project(project: str | None, cfg: dict | None = None) -> str:
    """The index of a project name (server.project_name of the working directory): mapped (config indexes.map), ignored (indexes.ignore,
    the home directory, the root …) → global."""
    cfg = _config() if cfg is None else cfg
    if not project:
        return GLOBAL
    p = str(project).strip()
    mapped = (cfg.get("map") or {}).get(p) or (cfg.get("map") or {}).get(p.lower())
    if mapped:
        return normalize(mapped) or GLOBAL
    low = p.lower()
    import getpass
    try:
        user = getpass.getuser().lower()
    except Exception:  # noqa: BLE001
        user = ""
    ignore = {str(x).lower() for x in (cfg.get("ignore") or [])} | IGNORE_ALWAYS | ({user} if user else set())
    if low in ignore or low.startswith("."):
        return GLOBAL
    try:
        return normalize(low) or GLOBAL
    except ValueError:  # a directory name that is no valid index name: global, never a guess
        return GLOBAL


def index_for(explicit: str | None, project: str | None, cfg: dict | None = None) -> str:
    """An explicit index wins; otherwise the project's; otherwise global."""
    return normalize(explicit) or from_project(project, cfg)
