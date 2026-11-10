"""0.38.0: the memory index — what a MEMORY.md is for a single assistant, pushed to every session.

A file memory works because nobody has to decide to look into it: its index is in the context from the first message, one line per
entry, and the entry itself is read when a line fits. The VI had only the pull side (vi_recall) — and was consulted before 63 % of
changing actions (vi_stats, 7 days to 10.11.2026). So `initialize` now sends a short index with the instructions, built per instance:

  Requirements   objects tagged thema:vorgabe (rule 6: what the user decided or requires beyond one session), newest first
  Proven         knowledge confirmed by an independent line, then the most used (accesses) — imports excluded
  Learned here   what this instance learned itself, newest first — imports excluded

Bounded by MAX_CHARS (Claude Code is reported to cut server instructions at 2,048 characters in some versions; the rules come first, the
index after them). Visibility as everywhere: what the instance may read; without a token only shared objects. Only active objects —
nothing disputed, refuted, archived or in quarantine.
"""
from __future__ import annotations

from . import memory as g

MAX_CHARS = 2000
LINE_CHARS = 110
KINDS = ("erkenntnis", "regel", "skill", "bild")
PER_SECTION = {"vorgaben": 8, "bewaehrt": 6, "hier": 6}
#: bulk imports (manuals, Confluence, Stibo, findings of the log monitor, the network) fill the store but are no index entries
IMPORT_PREFIXES = ("quelle_art:", "art_wissen:", "doku:")
IMPORT_TAGS = {"herkunft:skills-ordner", "herkunft:p2p", "herkunft:offen", "herkunft:schlaf-llm", "herkunft:log-ueberwachung", "herkunft:schlaf"}


def _imported(o) -> bool:
    return any(t.startswith(IMPORT_PREFIXES) or t in IMPORT_TAGS for t in o.hashtags)


def _ids(sql: str, params: tuple) -> list[str]:
    with g.lock:
        return [r[0] for r in g.db().execute(sql, params)]


def _pick(ids: list[str], instance: str, n: int, taken: set[str], imports_ok: bool = False, keep=None) -> list:
    out = []
    objs = g.load_many(ids)
    for oid in ids:
        o = objs.get(oid)
        if (not o or oid in taken or o.mode != "aktiv" or not g.visible_to(o, instance) or (not imports_ok and _imported(o))
                or (keep and not keep(o))):
            continue
        out.append(o)
        taken.add(oid)
        if len(out) >= n:
            break
    return out


def sections(instance: str) -> dict[str, list]:
    kinds = ",".join("?" * len(KINDS))
    taken: set[str] = set()
    req = _pick(_ids(f"SELECT o.id FROM objekt o JOIN tag t ON t.objekt_id = o.id AND t.tag = 'thema:vorgabe' "
                     f"WHERE o.art IN ({kinds}) AND o.modus = 'aktiv' ORDER BY o.zeit DESC LIMIT 60", KINDS), instance, PER_SECTION["vorgaben"], taken,
                imports_ok=True)
    proven = _pick(_ids(f"SELECT id FROM objekt WHERE art IN ({kinds}) AND modus = 'aktiv' AND (bestaetigt > 0 OR zugriffe > 0) "
                        "ORDER BY bestaetigt DESC, zugriffe DESC LIMIT 200", KINDS), instance, PER_SECTION["bewaehrt"], taken)
    here = _pick(_ids(f"SELECT id FROM objekt WHERE art IN ({kinds}) AND modus = 'aktiv' AND instanz = ? ORDER BY zeit DESC LIMIT 200",
                      (*KINDS, instance)), instance, PER_SECTION["hier"], taken)
    return {"vorgaben": req, "bewaehrt": proven, "hier": here}


def _line(o) -> str:
    text = " ".join(o.text.split())
    text = text if len(text) <= LINE_CHARS else text[:LINE_CHARS - 1] + "…"
    return f"- [{o.id}] {'image: ' if o.kind == 'bild' else ''}{text}"


def text(instance: str) -> str:
    """The index as it goes into the instructions; '' if there is nothing to list."""
    try:
        sec = sections(instance)
    except Exception:  # noqa: BLE001 — an index must never break initialize
        return ""
    titles = {"vorgaben": "Requirements and decisions (thema:vorgabe)", "bewaehrt": "Proven or most used", "hier": f"Learned by {instance} recently"}
    head = (f"[Index] Memory index for instance {instance}, like a MEMORY.md: one line per entry — vi_object <id> reads it whole, "
            "vi_recall searches everything else.")
    out, size = [head], len(head)
    for key, objs in sec.items():
        if not objs:
            continue
        lines = [f"{titles[key]}:"] + [_line(o) for o in objs]
        for i, ln in enumerate(lines):
            # a title needs room for at least one entry after it; the cut is named, not silent
            if size + len(ln) + 1 + (len(lines[1]) + 1 if i == 0 else 0) > MAX_CHARS:
                if out[-1].endswith(":"):
                    out.pop()
                out.append("(index cut at its size limit — vi_recall finds the rest)")
                return "\n".join(out)
            out.append(ln)
            size += len(ln) + 1
    return "\n".join(out) if len(out) > 1 else ""
