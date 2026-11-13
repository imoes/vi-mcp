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


def first(o, index: str | None) -> bool:
    """Does object o come first in this project? Its index, unless an index comparison found it good only at its origin (0.62.0,
    daten.vorrang_aus — it stays visible as general knowledge)."""
    return index is not None and o.idx == index and not (o.data or {}).get("vorrang_aus")


def index_for(explicit: str | None, project: str | None, cfg: dict | None = None) -> str:
    """An explicit index wins; otherwise the project's; otherwise global."""
    return normalize(explicit) or from_project(project, cfg)


# ── administration (vi-mcp index …, vi_indexes) ────────────────────────────

KINDS = ("global", "projekt", "spezial")


def registry() -> dict[str, dict]:
    """The rows of vi_index: name (primary key) → kind, description, tags, created, origin."""
    import json
    from . import memory as g
    with g.lock:
        rows = g.db().execute("SELECT name, art, beschreibung, tags, erstellt, quelle FROM vi_index").fetchall()
    return {r[0]: {"art": r[1], "beschreibung": r[2], "tags": json.loads(r[3] or "[]"), "erstellt": r[4], "quelle": r[5]} for r in rows}


def describe(name: str, description: str | None = None, tags: list[str] | None = None, kind: str | None = None) -> str:
    """Give an index a description, tags and its kind (projekt / spezial). Creates the row if the index has no objects yet."""
    import json
    from . import memory as g
    n = normalize(name)
    if not n:
        raise ValueError("an index name is required")
    if kind is not None and kind not in KINDS[1:]:
        raise ValueError(f"kind must be one of {', '.join(KINDS[1:])}")
    if n == GLOBAL and kind is not None:
        raise ValueError("global stays global")
    clean = None
    if tags is not None:
        clean = sorted({str(t).strip().lower() for t in tags if str(t).strip()})
        bad = [t for t in clean if not re.match(r"^[a-z0-9][a-z0-9:._-]{0,60}$", t)]
        if bad:
            raise ValueError(f"tags: a-z, 0-9, ':', '.', '-', '_' only — {', '.join(bad[:3])}")
    with g.lock:
        g.db().execute("INSERT OR IGNORE INTO vi_index (name, art, erstellt, quelle) VALUES (?, ?, ?, 'beschrieben')",
                       (n, kind or "projekt", g.now()))
        if description is not None:
            g.db().execute("UPDATE vi_index SET beschreibung = ? WHERE name = ?", (description.strip()[:2000], n))
        if clean is not None:
            g.db().execute("UPDATE vi_index SET tags = ? WHERE name = ?", (json.dumps(clean), n))
        if kind is not None:
            g.db().execute("UPDATE vi_index SET art = ? WHERE name = ?", (kind, n))
        g.db().commit()
    g._known_indexes.add(n)
    r = registry()[n]
    return f"index {n} ({r['art']}): {r['beschreibung'] or '—'}" + (f" · tags {', '.join(r['tags'])}" if r["tags"] else "")

def summary() -> list[dict]:
    """Every index: objects, experiences, knowledge, its own model's state. global first, then by size."""
    from . import learning
    from . import memory as g
    with g.lock:
        rows = g.db().execute("SELECT idx, art, COUNT(*) FROM objekt WHERE modus NOT IN ('widerlegt', 'aufgegangen') GROUP BY idx, art").fetchall()
    reg = registry()
    per: dict[str, dict] = {name: {"index": name, "objekte": 0, "erfahrungen": 0, "wissen": 0, "code": 0} for name in reg}
    with g.lock:
        code = dict(g.db().execute("SELECT o.idx, COUNT(*) FROM objekt o JOIN tag t ON t.objekt_id = o.id WHERE t.tag = 'art_wissen:code' "
                                   "AND o.modus = 'aktiv' GROUP BY o.idx").fetchall())
    for idx, art, n in rows:
        e = per.setdefault(idx, {"index": idx, "objekte": 0, "erfahrungen": 0, "wissen": 0, "code": 0})
        e["objekte"] += n
        if art == "erfahrung":
            e["erfahrungen"] += n
        elif art in ("erkenntnis", "regel", "skill", "bild", "seite"):
            e["wissen"] += n
    for idx, e in per.items():
        r = reg.get(idx) or {}
        e.update(art=r.get("art", "?"), beschreibung=r.get("beschreibung", ""), tags=r.get("tags", []), code=code.get(idx, 0))
        m = g.load(learning.model_id(idx)) if idx != GLOBAL else learning.model()
        e["modell"] = "—" if m is None else f"{m.mode}" + (f", AUC {m.data.get('auc_holdout')}" if m.data.get("auc_holdout") is not None else "")
        if m is not None and idx != GLOBAL:
            e["modell_urteil"] = str(m.data.get("urteil") or "")[:200]
    return sorted(per.values(), key=lambda e: (e["index"] != GLOBAL, -e["objekte"]))


def lines() -> list[str]:
    out = []
    for e in summary():
        out.append(f"  {e['index']:24} ({e['art']}) {e['objekte']:7} objects · {e['erfahrungen']:7} experiences · {e['wissen']:6} knowledge"
                   f" (code pieces {e['code']}) · model {e['modell']}")
        if e.get("beschreibung") or e.get("tags"):
            out.append(f"    {e.get('beschreibung') or ''}" + (f" [tags: {', '.join(e['tags'])}]" if e.get("tags") else ""))
        if e.get("modell_urteil"):
            out.append(f"    {e['modell_urteil']}")
        from . import index_transfer
        out += index_transfer.lines(e["index"])  # 0.62.0
    return out or ["  — no objects"]


def move(oid: str, index: str, who: str, reason: str) -> str:
    from . import memory as g
    new = normalize(index) or GLOBAL
    o = g.load(oid)
    if o is None:
        raise ValueError(f"{oid}: unknown")
    if o.idx == new:
        return f"{oid} is already in {new}"
    o.change(who, f"index {o.idx} → {new}", reason)
    old, o.idx = o.idx, new
    g.save(o)
    return f"{oid}: index {old} → {new}"


def rename(old: str, new: str, who: str, reason: str) -> str:
    """Rename or (if `new` exists) merge an index. The own model of `old` is set to test — it was trained on another set — and is
    retrained in the next sleep under the new name. Counted, never silent."""
    from . import learning
    from . import memory as g
    a, b = normalize(old), normalize(new)
    if not a or not b or a == GLOBAL or a == b:
        raise ValueError("give two different indexes; global cannot be renamed")
    if not (reason or "").strip():
        raise ValueError("a reason is required")
    with g.lock:
        n = g.db().execute("UPDATE objekt SET idx = ? WHERE idx = ? AND id <> ?", (b, a, learning.model_id(a))).rowcount
        # the row of vi_index: renamed if b is new (description and tags go along), dropped if a was merged into an existing b
        if g.db().execute("SELECT 1 FROM vi_index WHERE name = ?", (b,)).fetchone():
            if g.db().execute("SELECT COUNT(*) FROM objekt WHERE idx = ?", (a,)).fetchone()[0] == 0:
                g.db().execute("DELETE FROM vi_index WHERE name = ?", (a,))
        else:
            g.db().execute("UPDATE vi_index SET name = ? WHERE name = ?", (b, a))
        g.db().commit()
    g._known_indexes.discard(a)
    m = g.load(learning.model_id(a))
    if m is not None and m.mode != "test":
        m.mode = "test"
        m.change(who, f"index {a} → {b}: model set to test, retrained under {b} in the next sleep", reason)
        g.save(m)
    return f"{n} object(s) moved from index {a} to {b}" + (f"; model {m.id} set to test" if m is not None else "")


def backfill(apply: bool = False) -> dict:
    """Give existing experiences and knowledge the index of the project their conversation came from (the hook recorded it on the
    conversation object since 0.24.0). Without apply only counts, per index. Objects not in global are left alone."""
    from . import memory as g
    cfg = _config()
    with g.lock:
        projects = {s: p for s, p in g.db().execute(
            "SELECT json_extract(daten, '$.serial'), json_extract(daten, '$.project') FROM objekt WHERE art = 'gespraech' "
            "AND json_extract(daten, '$.project') IS NOT NULL").fetchall() if s}
        rows = g.db().execute("SELECT id, gespraech, art FROM objekt WHERE idx = 'global' AND gespraech IS NOT NULL "
                              "AND art IN ('erfahrung', 'erkenntnis', 'bild')").fetchall()
    per: dict[str, dict[str, int]] = {}
    moves: list[tuple[str, str]] = []
    for oid, serial, art in rows:
        p = projects.get(serial)
        idx = from_project(p, cfg) if p else GLOBAL
        if idx == GLOBAL:
            continue
        per.setdefault(idx, {}).setdefault(art, 0)
        per[idx][art] += 1
        moves.append((idx, oid))
    if apply and moves:
        with g.lock:
            for i in range(0, len(moves), 500):
                g.db().executemany("UPDATE objekt SET idx = ? WHERE id = ?", moves[i:i + 500])
            g.db().commit()
    return {"angewendet": bool(apply), "objekte": len(moves), "je_index": dict(sorted(per.items(), key=lambda kv: -sum(kv[1].values())))}


def main(argv: list[str]) -> int:
    import argparse
    import json
    if argv[:1] == ["import-code"]:  # runs where the repository is and talks MCP to the server — no local database
        from . import code_import
        return code_import.main(argv[1:])
    a = argparse.ArgumentParser(prog="vi-mcp index", description="indexes of the memory: projects and special VIs")
    u = a.add_subparsers(dest="cmd", required=True)
    u.add_parser("list", help="every index with its objects, experiences, knowledge and own model")
    mv = u.add_parser("move", help="move one object to another index")
    mv.add_argument("id")
    mv.add_argument("index")
    mv.add_argument("--reason", required=True)
    rn = u.add_parser("rename", help="rename an index, or merge it into an existing one")
    rn.add_argument("old")
    rn.add_argument("new")
    rn.add_argument("--reason", required=True)
    ds = u.add_parser("describe", help="give an index a description, tags (comma separated) and its kind")
    ds.add_argument("index")
    ds.add_argument("--text")
    ds.add_argument("--tags")
    ds.add_argument("--kind", choices=KINDS[1:])
    bf = u.add_parser("backfill", help="existing experiences and knowledge into their conversation's project index (counts without --apply)")
    bf.add_argument("--apply", action="store_true")
    u.add_parser("import-code", help="put the code of a git repository into an index (vi-mcp index import-code REPO --index X)", add_help=False)
    tr = u.add_parser("train", help="train the own model of one index now (otherwise sleep step 8d does it)")
    tr.add_argument("index")
    ex = u.add_parser("export", help="the knowledge of one index into a signed, internal file, with this server's measurements (0.62.0)")
    ex.add_argument("index")
    ex.add_argument("file")
    im = u.add_parser("import", help="import an index file of another server into an index: quarantine and reviewer like the network")
    im.add_argument("file")
    im.add_argument("--as", dest="as_index", required=True, metavar="INDEX")
    cp = u.add_parser("compare", help="per content: this server's measurement against the exporters' (sleep step 8e does it daily)")
    cp.add_argument("index")
    cp.add_argument("--dry-run", action="store_true", help="only report, do not switch the project priority")
    o = a.parse_args(argv)
    from . import config
    from . import memory as g
    g.open_db(config.load().db)
    try:
        if o.cmd == "list":
            print("\n".join(lines()))
        elif o.cmd == "move":
            print(move(o.id, o.index, "admin", o.reason))
        elif o.cmd == "rename":
            print(rename(o.old, o.new, "admin", o.reason))
        elif o.cmd == "describe":
            print(describe(o.index, o.text, o.tags.split(",") if o.tags is not None else None, o.kind))
        elif o.cmd == "backfill":
            print(json.dumps(backfill(o.apply), indent=2, ensure_ascii=False))
        elif o.cmd in ("export", "import", "compare"):
            from . import index_transfer
            return index_transfer.main(o.cmd, o)
        else:
            from . import learning
            r = learning.train_index(normalize(o.index) or GLOBAL, "admin")
            print(json.dumps({k: r.get(k) for k in ("index", "zustand", "n", "auc_holdout", "urteil", "gegen_gemeinsam")}, indent=2, ensure_ascii=False))
    except ValueError as e:
        print(f"vi-mcp index {o.cmd}: {e}")
        return 1
    finally:
        g.close_db()
    return 0
