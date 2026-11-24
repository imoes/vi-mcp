"""0.53.0: which skills exist, which system each one serves, which tools it has, and where its manual is — at the start of a session.

Proposed by a Claude Code session that worked a whole day next to the right manuals without opening them (11.11.2026): it looked for a
GitLab repository with a local `git grep` because nothing told it that a GitLab skill with its own tools existed. The memory knows it:
  - every imported skill manual has one overview object (tag `art-wissen:ueberblick` or `knowledge_kind:overview`, plus `docs:<skill>`);
  - which tools belong to a skill it has measured: experiences tagged `tool:<prefix>_…` with the skill's prefix.
`table()` joins both; `text()` renders one line per skill. Visibility as everywhere: what the instance may read. The hook puts it into the
first prompt of a session (it is too long for the instructions, which some clients cut at about 2,000 characters); `vi_capabilities` returns
it at any time.
"""
from __future__ import annotations

import re
import threading
import time

from . import memory as g

OVERVIEW_TAGS = ("art-wissen:ueberblick", "knowledge_kind:overview", "knowledge_kind:skill")  # skill: 0.69.4 (knowledge_skills)
TOOLS_PER_SKILL = 8
DESCRIPTION_CHARS = 90
EXTERNAL_TAG = "knowledge_kind:external-docs"
CACHE_S = 600
_cache: dict = {}
#: 24.11.2026: one build at a time — on a cache miss every concurrent initialize built the table itself (84 threads at once on a
#: production copy under session churn, all queuing for the database lock)
_build = threading.Lock()


def _description(text: str, doc: str) -> str:
    """The overview text after its standard opening ("Vollständige Doku zu X: vi_erinnere docs:X."), first sentence, shortened."""
    t = " ".join((text or "").split())
    t = re.sub(r"^.*?(?:docs|doku):" + re.escape(doc) + r"\.\s*", "", t)  # 0.69.4: the German header of older imports too
    if t.startswith("(Abschnitte:"):  # an overview without a description: its sections say what it covers
        t = "sections: " + t[len("(Abschnitte:"):].strip().rstrip(")")
    else:
        t = t.split(" (Abschnitte:")[0].strip()
    if len(t) <= DESCRIPTION_CHARS:
        return t
    cut = t[:DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0]  # at a word boundary — a sentence split breaks at "z.B."
    return cut.rstrip(",;:—-") + "…"


def _manual_names(doc: str, prefix: str) -> set[str]:
    """Names of the form <prefix>_… that the skill's manual mentions. Used only to assign real tools to a skill (two skills can share a
    prefix, e.g. jira and jira-servicedesk) — never as a source of names: manual prose names REST endpoints, old names and fragments
    (0.53.2 listed proxmox_vms_list, jira_acme_, prompt_tokens …; checked against the real tool list by a Claude Code session)."""
    with g.lock:  # every section of the skill's manual (herkunft:skills-ordner), not vendor documentation
        ids = [r[0] for r in g.db().execute("SELECT t1.object_id FROM tag t1 WHERE t1.tag = ? AND NOT EXISTS (SELECT 1 FROM tag t2 "
                                            "WHERE t2.object_id = t1.object_id AND t2.tag = ?) LIMIT 400", (f"docs:{doc}", EXTERNAL_TAG))]
    pattern = re.compile(rf"\b({re.escape(prefix)}_[a-z0-9_]{{2,60}})\b")
    names: set[str] = set()
    for o in g.load_many(ids).values():
        names.update(pattern.findall(o.text + "\n" + str(o.data.get("content") or "")))
    return names


# ---- real tool names: registered from an MCP server's tools/list, or seen in use

def _tables() -> None:
    with g.lock:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS tool_register (server TEXT NOT NULL, name TEXT NOT NULL, ts TEXT NOT NULL, instance TEXT NOT NULL,
                                                          PRIMARY KEY (server, name));
        """)
        g.db().commit()


TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,80}")


def register(server: str, names: list[str], instance: str) -> dict:
    """0.53.3: the real tool list of an MCP server (its tools/list), replacing the previous one of that server. Returns what changed."""
    server = (server or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", server):
        raise ValueError("server: letters, digits, _ . - (the MCP server's name, e.g. team-skills)")
    clean = sorted({n.strip() for n in names or [] if isinstance(n, str) and TOOL_NAME.fullmatch(n.strip())})
    if not clean:
        raise ValueError("tools: the names from the server's tools/list")
    _tables()
    with g.lock:
        before = {r[0] for r in g.db().execute("SELECT name FROM tool_register WHERE server = ?", (server,))}
        g.db().execute("DELETE FROM tool_register WHERE server = ?", (server,))
        g.db().executemany("INSERT INTO tool_register (server, name, ts, instance) VALUES (?,?,?,?)", [(server, n, g.now(), instance) for n in clean])
        g.db().commit()
    _cache.clear()
    return {"server": server, "tools": len(clean), "new": sorted(set(clean) - before), "gone": sorted(before - set(clean))}


def _real_tools(prefix: str) -> list[str]:
    """Real tools with the prefix: registered ones and ones seen in use (tool:<name> on experiences), the most used first."""
    _tables()
    with g.lock:  # substr, not LIKE: "_" is a wildcard in LIKE, and the same SQL runs on PostgreSQL
        used = g.db().execute("SELECT tag, COUNT(*) FROM tag WHERE substr(tag, 1, ?) = ? GROUP BY tag",
                              (len(prefix) + 6, f"tool:{prefix}_")).fetchall()
        registered = [r[0] for r in g.db().execute("SELECT DISTINCT name FROM tool_register WHERE substr(name, 1, ?) = ?",
                                                    (len(prefix) + 1, f"{prefix}_"))]
    counts = {t[5:]: n for t, n in used}
    for n in registered:
        counts.setdefault(n, 0)
    return [n for n, _c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _tools(prefix: str, doc: str = "") -> list[str]:
    """Tools of a skill — real names only. If its manual names some of them, exactly those (that also separates skills sharing a prefix);
    if the manual names none, every real tool with the prefix."""
    if not prefix or not re.fullmatch(r"[a-z0-9]+", prefix):
        return []
    real = _real_tools(prefix)
    mentioned = _manual_names(doc, prefix) if doc else set()
    chosen = [n for n in real if n in mentioned] if mentioned & set(real) else ([] if mentioned else real)
    return chosen[:TOOLS_PER_SKILL]


def table(instance: str | None) -> list[dict]:
    """One row per skill manual the instance may read: {skill, doc, description, tools, id}. Several overviews of one skill: the newest.
    Cached CACHE_S per instance — it is asked at the first prompt of every session."""
    hit = _cache.get(instance)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    with _build:
        hit = _cache.get(instance)
        if hit and time.monotonic() - hit[0] < CACHE_S:
            return hit[1]
        return _table_now(instance)


def _table_now(instance: str | None) -> list[dict]:
    rows: dict[str, dict] = {}
    with g.lock:
        ids = list(dict.fromkeys(r[0] for r in g.db().execute(  # DISTINCT with ORDER BY needs the sort column selected (PostgreSQL)
            f"SELECT DISTINCT o.id, o.ts FROM object o JOIN tag t ON t.object_id = o.id WHERE t.tag IN ({', '.join('?' * len(OVERVIEW_TAGS))}) AND o.mode IN ('active', 'test') "
            "ORDER BY o.ts DESC", OVERVIEW_TAGS)))
    objs = g.load_many(ids)
    ids.sort(key=lambda i: "origin:builtin" not in (objs[i].hashtags if objs.get(i) else []))  # 0.69.4: an initial skill keeps its name
    for oid in ids:
        o = objs.get(oid)
        if not o or not g.visible_to(o, instance):
            continue
        doc = next((t[5:] for t in o.hashtags if t.startswith("docs:")), None)
        if not doc or doc in rows:
            continue
        prefix = next((t[6:] for t in o.hashtags if t.startswith("skill:")), None)
        tools = [str(x) for x in (o.data.get("tools") or [])][:TOOLS_PER_SKILL] or _tools(prefix or "", doc)  # 0.69.4: built-in manuals name theirs
        rows[doc] = {"skill": doc, "doc": f"docs:{doc}", "description": _description(o.text, doc), "tools": tools, "id": o.id}
    out = sorted(rows.values(), key=lambda r: r["skill"])
    _cache[instance] = (time.monotonic(), out)
    return out


def text(instance: str | None) -> str:
    rows = table(instance)
    if not rows:
        return ""
    head = (f"[Skills] {len(rows)} skill manuals in the VI — before working on one of these systems or searching for a tool, use the skill and "
            "read its manual (vi_object <id>, or vi_recall docs:<skill>). Tools are real names only — registered from the MCP server "
            "(vi_tools_register) or seen in use; none known: see the manual. A skill tool missing "
            "(\"No such tool available\")? vi_recall the error text — the MCP server that serves it is probably not registered.")
    lines = [head]
    for r in rows:
        tools = f" · tools {', '.join(r['tools'])}" if r["tools"] else " · tools: see the manual"
        lines.append(f"- {r['skill']}: {r['description']}{tools} → [{r['id']}]")
    return "\n".join(lines)
