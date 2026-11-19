"""Skills in the server (0.69.4): what an AI can do here and how — knowledge of the kind `knowledge_kind:skill`, extensible, inherited.

The user (17.11.2026): "Solche Informationen müssen vererbt werden", "die Skills sollen im MCP-Server stehen und erweiterbar sein. Clingo
ist nur einer der initialen Skills" and "warum manual und nicht knowledge_kind?". Until 0.69.3 skills came in once by hand (08.11.2026,
30 from a skills folder, tagged knowledge_kind:overview); every skill written later was missing, and the shipped ones were reachable only
by a tool action nobody knew to call.

A skill is one knowledge object with the hashtags `knowledge_kind:skill` and `docs:<name>`, the whole text in `content`, and
`data.key = "skill:<name>"`. There is one way in for everyone, and it is the ordinary one:
- an AI adds or updates a skill with vi_learn(text, content, hashtags=[knowledge_kind:skill, docs:<name>, …], key="skill:<name>",
  source=…) — the key makes a later vi_learn of the same instance an update with history, not a second object; the fixed rules and the
  quarantine of vi_learn apply as to any knowledge;
- `vi-mcp skill import DIR --instance NAME` brings a whole skills folder in (<dir>/<name>/SKILL.md with a front matter
  name/description, files next to it appended) — through the same vi_learn call, as that instance;
- the initial skills of the package (INITIAL: clingo, finetune, philosophy) are written by the server at every start (`ensure`,
  instance `vi`, origin:builtin, id insight:skill-<name>) and refreshed when the package's text changed. Their names are reserved: a
  vi_learn with docs:<initial name> is refused, so nobody shadows them.
Reading: vi_capabilities lists every skill (the hook puts that table into the first prompt of every session), vi_object reads one whole,
vi_recall knowledge_kind:skill finds them. Older skills tagged knowledge_kind:overview (08.11.2026) are still listed.
Initial skills are never exported to a network — every server has them from its own package.

Not to be confused with kind:skill (vi_skills / vi_skill): procedures the VI learned from experiences in sleep.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import __version__
from . import memory as g

TAG = "knowledge_kind:skill"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,47}")
SUMMARY_MAX = 300
MAX_TOOLS = 12


def _clingo() -> str:
    from . import clingo_skill
    return clingo_skill.skill()


def _finetune() -> str:
    from . import finetune_skill
    return finetune_skill.skill()


def _vi_rules() -> str:
    from . import tools
    return tools.RULES_FULL


def _philosophy() -> str:
    from clingo_object import philosophy as ph
    return ph.GUIDE


#: the initial skills, shipped with the package: name → (summary, tools, text source)
INITIAL = {
    "clingo": ("Logic programs with vi_logic: notation, workflow, the six answers, norms, soft rules, rules over memory objects, "
               "measured mistakes", ["vi_logic"], _clingo),
    "finetune": ("Fine-tune any open model with the knowledge of a VI or a philosophy seed, step by step, for small models too",
                 ["vi_finetune", "vi_incubator"], _finetune),
    # 0.70.6: the complete rules; the instructions carry only the core (Claude Code cuts them at 4,096 characters)
    "vi-rules": ("The complete rules for working with the VI: when to search and learn, code, wiki, images, logic, philosophy, "
                 "fine-tuning, what never to learn", ["vi_recall", "vi_learn", "vi_object"], _vi_rules),
    "philosophy": ("Equip an AI with a philosophy: a checked clingo-object seed with test worlds, install, bind, train, measure",
                   ["vi_philosophy", "vi_logic"], _philosophy),
}


def object_id(name: str) -> str:
    """The id of an initial skill (skills an AI adds get an ordinary id; their identity is the key skill:<name>)."""
    return f"insight:skill-{name}"


def key_statement(name: str, summary: str) -> str:
    return f"Skill, docs:{name}. {summary.strip().rstrip('.')}."  # vi_capabilities shows what follows "docs:<name>."


def check_learn(tags: list[str], key: str, instance: str) -> None:
    """vi_learn of a skill: a docs:<name> hashtag and the key skill:<name>; the initial names belong to the package."""
    if TAG not in tags:
        return
    names = [t[5:] for t in tags if t.startswith("docs:")]
    if len(names) != 1 or not NAME.fullmatch(names[0]):
        raise ValueError("a skill needs exactly one hashtag docs:<name> (lower case, digits, -), e.g. docs:backup-check")
    if key != f"skill:{names[0]}":
        raise ValueError(f'a skill needs key="skill:{names[0]}" — then your next vi_learn of it updates it with history')
    if names[0] in INITIAL and instance != g.SERVER_INSTANCE:
        raise ValueError(f"{names[0]} is an initial skill of the package — it is updated with vi-mcp; add yours under another name")


def ensure() -> dict:
    """At server start: the initial skills into this memory, refreshed when the package's text changed. {name: state or error}."""
    out = {}
    for name, (summary, tools, src) in INITIAL.items():
        try:
            text = src()
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            tags = [TAG, f"docs:{name}", "origin:builtin", "topic:skill"]
            data = {"source": f"vi-mcp {__version__}, initial skill of the package", "content": text, "summary": summary,
                    "tools": tools, "content_sha256": sha, "key": f"skill:{name}", "builtin": {"name": name, "version": __version__}}
            o = g.load(object_id(name))
            if o is None:
                g.new_object("insight", key_statement(name, summary), tags, data, importance=2, who="vi",
                             reason=f"initial skill of vi-mcp {__version__}", oid=object_id(name), instance=g.SERVER_INSTANCE,
                             visibility="shared", link=False)
                out[name] = "created"
                continue
            if o.data.get("content_sha256") == sha and o.mode == "active" and o.text == key_statement(name, summary):
                out[name] = "current"
                continue
            o.text, o.mode = key_statement(name, summary), "active"
            o.hashtags = sorted(set(o.hashtags) | set(tags))
            o.data.update(data)
            o.change("vi", f"skill updated to vi-mcp {__version__}", "the package is the source of its initial skills")
            g.save(o)
            out[name] = "updated"
        except Exception as e:  # noqa: BLE001 — a skill that cannot be built must not stop the server; it is reported
            out[name] = f"error: {type(e).__name__}: {str(e)[:120]}"
    return out


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() and v.strip():
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def import_dir(path: Path, instance: str, dry_run: bool = False) -> dict:
    """A skills folder into the server, one skill per <name>/SKILL.md, through vi_learn as `instance` (the same way an AI adds one).
    Files next to SKILL.md (references/*.md …) are appended in full, under their file name."""
    from . import tools
    out: dict = {"learned": [], "updated": [], "refused": {}}
    for skill_md in sorted(Path(path).glob("*/SKILL.md")):
        meta, body = _front_matter(skill_md.read_text(encoding="utf-8", errors="replace"))
        name = (meta.get("name") or skill_md.parent.name).strip().lower()
        summary = (meta.get("description") or f"Skill {name}").split(". ")[0][:SUMMARY_MAX]
        extra = [f"\n\n## File {p.relative_to(skill_md.parent)}\n\n" + p.read_text(encoding="utf-8", errors="replace")
                 for p in sorted(skill_md.parent.rglob("*.md")) if p != skill_md]
        args = {"text": key_statement(name, summary), "content": body + "".join(extra), "hashtags": [TAG, f"docs:{name}", "topic:skill"],
                "key": f"skill:{name}", "source": f"skills folder: {skill_md.parent.name}/SKILL.md", "importance": 2}
        try:
            if dry_run:
                check_learn(args["hashtags"], args["key"], instance)
                out["learned"].append(name)
                continue
            r = tools.call_tool("vi_learn", args, instance, False)
            out["updated" if r.startswith("updated") else "learned"].append(name)
        except (ValueError, tools.Rejected) as e:
            out["refused"][name] = str(e)[:200]
    return out


def main(argv: list[str]) -> int:
    """vi-mcp skill list | show NAME | import DIR --instance NAME [--dry-run]"""
    import json
    from . import capabilities, config
    cmd = argv[0] if argv else "list"
    g.open_db(config.load().db)
    if cmd == "list":
        print(capabilities.text(None) or "no skills")
        return 0
    if cmd == "show" and len(argv) >= 2:
        row = next((r for r in capabilities.table(None) if r["skill"] == argv[1]), None)
        print((g.load(row["id"]).data.get("content") or "") if row else f"no skill {argv[1]}")
        return 0 if row else 1
    if cmd == "import" and len(argv) >= 2 and "--instance" in argv:
        print(json.dumps(import_dir(Path(argv[1]), argv[argv.index("--instance") + 1], dry_run="--dry-run" in argv), indent=2,
                         ensure_ascii=False))
        return 0
    print(main.__doc__)
    return 2
