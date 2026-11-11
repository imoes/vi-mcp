"""0.53.0: which skills exist, which system each one serves, which tools it has, and where its manual is — at the start of a session.

Proposed by a Claude Code session that worked a whole day next to the right manuals without opening them (11.11.2026): it looked for a
GitLab repository with a local `git grep` because nothing told it that a GitLab skill with its own tools existed. The memory knows it:
  - every imported skill manual has one overview object (tag `art-wissen:ueberblick` or `art_wissen:ueberblick`, plus `doku:<skill>`);
  - which tools belong to a skill it has measured: experiences tagged `tool:<prefix>_…` with the skill's prefix.
`table()` joins both; `text()` renders one line per skill. Visibility as everywhere: what the instance may read. The hook puts it into the
first prompt of a session (it is too long for the instructions, which some clients cut at about 2,000 characters); `vi_capabilities` returns
it at any time.
"""
from __future__ import annotations

import re
import time

from . import memory as g

OVERVIEW_TAGS = ("art-wissen:ueberblick", "art_wissen:ueberblick")
TOOLS_PER_SKILL = 5
DESCRIPTION_CHARS = 90
EXTERNAL_TAG = "art_wissen:doku-extern"
CACHE_S = 600
_cache: dict = {}


def _description(text: str, doc: str) -> str:
    """The overview text after its standard opening ("Vollständige Doku zu X: vi_erinnere doku:X."), first sentence, shortened."""
    t = " ".join((text or "").split())
    t = re.sub(r"^.*?doku:" + re.escape(doc) + r"\.\s*", "", t)
    if t.startswith("(Abschnitte:"):  # an overview without a description: its sections say what it covers
        t = "sections: " + t[len("(Abschnitte:"):].strip().rstrip(")")
    else:
        t = t.split(" (Abschnitte:")[0].strip()
    if len(t) <= DESCRIPTION_CHARS:
        return t
    cut = t[:DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0]  # at a word boundary — a sentence split breaks at "z.B."
    return cut.rstrip(",;:—-") + "…"


def _manual_tools(doc: str, prefix: str) -> list[str]:
    """Tool names written in the skill's manual (e.g. its section "MCP-Tools"): <prefix>_…, most mentioned first."""
    with g.lock:  # 0.53.2: every section of the skill's manual — imported from the skills folder they carry herkunft:skills-ordner, not
        # art_wissen:handbuch (production 11.11.2026: gitlab-api listed no tools); vendor documentation (doku-extern) is not the skill's manual
        ids = [r[0] for r in g.db().execute("SELECT t1.objekt_id FROM tag t1 WHERE t1.tag = ? AND NOT EXISTS (SELECT 1 FROM tag t2 "
                                            "WHERE t2.objekt_id = t1.objekt_id AND t2.tag = ?) LIMIT 400", (f"doku:{doc}", EXTERNAL_TAG))]
    tally: dict[str, int] = {}
    pattern = re.compile(rf"\b({re.escape(prefix)}_[a-z0-9_]{{2,40}})\b")
    for o in g.load_many(ids).values():
        for name in pattern.findall(o.text + "\n" + str(o.data.get("inhalt") or "")):
            tally[name] = tally.get(name, 0) + 1
    return [n for n, _c in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]


def _tools(prefix: str, doc: str = "") -> list[str]:
    """Tools of a skill: the ones measured in use first (tool:<prefix>_… on experiences), then the ones its manual names."""
    if not prefix or not re.fullmatch(r"[a-z0-9]+", prefix):
        return []
    with g.lock:  # substr, not LIKE: "_" is a wildcard in LIKE, and the same SQL runs on PostgreSQL
        rows = g.db().execute("SELECT tag, COUNT(*) FROM tag WHERE substr(tag, 1, ?) = ? GROUP BY tag ORDER BY COUNT(*) DESC, tag LIMIT ?",
                              (len(prefix) + 6, f"tool:{prefix}_", TOOLS_PER_SKILL * 3)).fetchall()
    used = [t[5:] for t, _n in rows]
    named = _manual_tools(doc, prefix) if doc else []
    return list(dict.fromkeys(used + named))[:TOOLS_PER_SKILL]


def table(instance: str | None) -> list[dict]:
    """One row per skill manual the instance may read: {skill, doc, description, tools, id}. Several overviews of one skill: the newest.
    Cached CACHE_S per instance — it is asked at the first prompt of every session."""
    hit = _cache.get(instance)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    rows: dict[str, dict] = {}
    with g.lock:
        ids = list(dict.fromkeys(r[0] for r in g.db().execute(  # DISTINCT with ORDER BY needs the sort column selected (PostgreSQL)
            "SELECT DISTINCT o.id, o.zeit FROM objekt o JOIN tag t ON t.objekt_id = o.id WHERE t.tag IN (?, ?) AND o.modus IN ('aktiv', 'test') "
            "ORDER BY o.zeit DESC", OVERVIEW_TAGS)))
    objs = g.load_many(ids)
    for oid in ids:
        o = objs.get(oid)
        if not o or not g.visible_to(o, instance):
            continue
        doc = next((t[5:] for t in o.hashtags if t.startswith("doku:")), None)
        if not doc or doc in rows:
            continue
        prefix = next((t[6:] for t in o.hashtags if t.startswith("skill:")), None)
        rows[doc] = {"skill": doc, "doc": f"doku:{doc}", "description": _description(o.text, doc), "tools": _tools(prefix or "", doc), "id": o.id}
    out = sorted(rows.values(), key=lambda r: r["skill"])
    _cache[instance] = (time.monotonic(), out)
    return out


def text(instance: str | None) -> str:
    rows = table(instance)
    if not rows:
        return ""
    head = (f"[Skills] {len(rows)} skill manuals in the VI — before working on one of these systems or searching for a tool, use the skill and "
            "read its manual (vi_object <id>, or vi_recall doku:<skill>). Tools are the ones measured in use. A skill tool missing "
            "(\"No such tool available\")? vi_recall the error text — the MCP server that serves it is probably not registered.")
    lines = [head]
    for r in rows:
        tools = f" · tools {', '.join(r['tools'])}" if r["tools"] else ""
        lines.append(f"- {r['skill']}: {r['description']}{tools} → [{r['id']}]")
    return "\n".join(lines)
