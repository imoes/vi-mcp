"""Which philosophy fits which situation (0.69.6) — declared by the package, learned from rated use.

The user (17.11.2026): "In verschiedenen Situationen sind verschiedene Philosophien nützlich. Also muss auch trainiert werden, wann eine
Philosophie sinnvoll ist." A philosophy is a checked rule set; whether it HELPS in a situation is not a property of its rules but a
measurement — so it is kept apart from the seed (intension vs extension):
- declared: a package may name the situations it is meant for, as hashtags (manifest `situations`, e.g. topic:incident,
  task:judge-claims) — the author's intent, the starting point;
- measured: every rated use of a philosophy in a situation counts per (philosophy, situation tag): helped or not
  (`vi_philosophy(action="rate", …)`), in the table philosophy_fit;
- suggested: `vi_philosophy(action="suggest", situation=…, tags=[…])` ranks the philosophies by Thompson sampling over
  Beta(1 + helped + PRIOR_DECLARED·declared, 1 + not helped) per matching tag — what is declared starts ahead, what is measured
  decides, what is rarely tried stays in play (Russo et al. 2017, arXiv 1707.02038; the same scheme as the hint bandit, bandit.py).
Every suggestion names its reason: which tags matched, declared or measured, with the counts. No suggestion is a decision: the AI
binds or evaluates a philosophy itself (use / evaluate), and the rating afterwards is what the VI learns from.
The measured choices are also training data: finetune kits can teach a model which philosophy a situation calls for (pairs()).
"""
from __future__ import annotations

import random
import re

from . import memory as g

TAG = re.compile(r"[a-z][a-z0-9_-]*:[^\s:][^\s]{0,80}")
PRIOR_DECLARED = 2.0
REASON_MIN = 10
#: the situations the server declares for its built-in philosophies — kept OUT of their packages: a changed package would change its
#: hash and void every binding to it. English and German words, since a situation is recognised from the words of a prompt.
BUILTIN_SITUATIONS = {
    "kollektiv": ["topic:claim", "topic:evidence", "topic:beleg", "topic:confirm", "topic:refute", "topic:widerlegen", "topic:quarantine",
                  "topic:hearsay", "task:judge-claims"],
    "messung": ["topic:measurement", "topic:messung", "topic:benchmark", "topic:messwert", "topic:evaluation", "task:accept-measurement"],
    "code": ["topic:refactor", "topic:architecture", "topic:architektur", "topic:imports", "task:code-review"],
}


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS philosophy_fit (name TEXT NOT NULL, tag TEXT NOT NULL, helped REAL NOT NULL, "
                       "wrong REAL NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (name, tag))")
        g.db().commit()


def candidates(viewer: str | None) -> dict[str, list[str]]:
    """{philosophy name: declared situation tags} — built in plus installed ones the viewer may see."""
    from clingo_object import philosophy as ph
    from . import philosophy
    out = {name: list(ph.load(name).get("situations") or BUILTIN_SITUATIONS.get(name) or []) for name in ph.BUILTIN}
    for o in philosophy.installed():
        if viewer is None or g.visible_to(o, viewer):
            out[o.data["philosophy"]["name"]] = list(o.data["philosophy"].get("situations") or [])
    return out


def situation_tags(text: str, tags: list | None, declared: dict[str, list[str]]) -> list[str]:
    """The situation as tags: the ones given, plus every declared tag whose value occurs as a word in the text."""
    out = [t for t in (str(x).strip().lower() for x in tags or []) if TAG.fullmatch(t)]
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]+", (text or "").lower()))
    _table()
    with g.lock:  # measured tags too: a situation rated once is recognised from its words next time
        measured = [r[0] for r in g.db().execute("SELECT DISTINCT tag FROM philosophy_fit")]
    for t in [x for decl in declared.values() for x in decl] + measured:
        if t.split(":", 1)[1] in words and t not in out:
            out.append(t)
    return out


def context_line(text: str, instance: str | None, shown: list | None = None) -> tuple[str | None, str | None]:
    """0.69.6, the user's decision (17.11.2026, "Vorschlag im Kontext"): one line for the prompt context when the situation of a prompt
    fits a philosophy — declared for it, or measured to have helped more often than not. Returns (line, id) or (None, None). Each
    philosophy at most once per conversation (its id philosophy:<name> joins the ids the hook already showed)."""
    r = suggest(text, None, instance)
    try:  # 0.73.0: a bound philosophy is in the instructions already — the suggestion is only for unbound ones
        from . import philosophy
        bound = {b["name"] for b in philosophy.bindings(instance, g.current_index.get())}
    except Exception:  # noqa: BLE001
        bound = set()
    for x in r["ranking"]:
        if f"philosophy:{x['name']}" in (shown or []) or x["name"] in bound:
            continue
        good = [m for m in x["matched"] if m["declared"] or m["helped"] > m["not_helped"]]
        if not good:
            continue
        why = ", ".join(m["tag"] + (" (declared)" if m["declared"] else "")
                        + (f" (helped {m['helped']:g} / not {m['not_helped']:g})" if m["helped"] or m["not_helped"] else "") for m in good)
        return (f"[Philosophy] This situation fits the philosophy {x['name']} ({why}). To apply it: translate the situation into its facts "
                f"(vocabulary: vi_philosophy(action=\"show\", name=\"{x['name']}\")), get its verdict with "
                f"vi_philosophy(action=\"evaluate\", name=\"{x['name']}\", facts=…), act by it, then rate whether it helped: "
                f"vi_philosophy(action=\"rate\", name=\"{x['name']}\", tags={[m['tag'] for m in good]}, helped=…, reason=…).",
                f"philosophy:{x['name']}")
    return None, None


def _counts(names: list[str], tags: list[str]) -> dict[tuple[str, str], tuple[float, float]]:
    _table()
    if not names or not tags:
        return {}
    with g.lock:
        rows = g.db().execute(f"SELECT name, tag, helped, wrong FROM philosophy_fit WHERE name IN ({','.join('?' * len(names))}) "
                              f"AND tag IN ({','.join('?' * len(tags))})", (*names, *tags)).fetchall()
    return {(n, t): (float(h), float(w)) for n, t, h, w in rows}


def suggest(text: str, tags: list | None, viewer: str | None, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    declared = candidates(viewer)
    sit = situation_tags(text, tags, declared)
    if not sit:
        return {"situation": [], "ranking": [], "reason": "no situation tag: name tags (e.g. topic:incident) or describe the situation "
                                                          "with words a philosophy declares"}
    counts = _counts(list(declared), sit)
    ranking = []
    for name, decl in declared.items():
        per, score, evidence = [], 0.0, 0
        for t in sit:
            h, w = counts.get((name, t), (0.0, 0.0))
            prior = PRIOR_DECLARED if t in decl else 0.0
            if not (prior or h or w):
                continue
            per.append({"tag": t, "declared": bool(prior), "helped": h, "not_helped": w})
            score += rng.betavariate(1 + h + prior, 1 + w)
            evidence += 1
        if evidence:
            ranking.append({"name": name, "score": round(score / len(sit), 3), "matched": per})
    ranking.sort(key=lambda r: -r["score"])
    return {"situation": sit, "ranking": ranking,
            "reason": "" if ranking else "no philosophy is declared for or measured in this situation — rate one after you used it"}


def rate(name: str, tags: list | None, helped: bool, instance: str, reason: str) -> dict:
    """A philosophy was used in a situation; did it help? Counts per situation tag."""
    declared = candidates(instance)
    if name not in declared:
        raise ValueError(f"no philosophy {name!r} built in or installed for you")
    sit = [t for t in (str(x).strip().lower() for x in tags or []) if TAG.fullmatch(t)]
    if not sit:
        raise ValueError("tags: the situation as kind:value hashtags (e.g. topic:incident) — the same ones suggest used")
    if len((reason or "").strip()) < REASON_MIN:
        raise ValueError(f"reason needed (at least {REASON_MIN} characters): what the philosophy decided and why it helped or not")
    _table()
    with g.lock:
        for t in sit:
            g.db().execute("INSERT INTO philosophy_fit (name, tag, helped, wrong, ts) VALUES (?,?,?,?,?) ON CONFLICT (name, tag) DO UPDATE "
                           "SET helped = philosophy_fit.helped + excluded.helped, wrong = philosophy_fit.wrong + excluded.wrong, "
                           "ts = excluded.ts", (name, t, 1.0 if helped else 0.0, 0.0 if helped else 1.0, g.now()))
        g.db().commit()
    from .log_output import log
    log(f"philosophy fit: {name} in {', '.join(sit)} {'helped' if helped else 'did not help'} ({instance}: {reason.strip()[:120]})")
    return {"name": name, "tags": sit, "helped": bool(helped), "counts": {t: _counts([name], [t]).get((name, t)) for t in sit}}


def pairs(min_n: int = 3) -> list[dict]:
    """Training data for a finetune kit: per situation tag the philosophy that measurably helped most (at least min_n ratings, more
    helped than not). Never a guess: a tag without such a measurement yields nothing."""
    _table()
    with g.lock:
        rows = g.db().execute("SELECT name, tag, helped, wrong FROM philosophy_fit").fetchall()
    best: dict[str, tuple] = {}
    for n, t, h, w in rows:
        if h + w >= min_n and h > w:
            rate_ = (h + 1) / (h + w + 2)
            if t not in best or rate_ > best[t][1]:
                best[t] = (n, rate_, h, w)
    return [{"situation": t, "philosophy": n, "helped": h, "not_helped": w} for t, (n, _r, h, w) in sorted(best.items())]


def lines(r: dict) -> list[str]:
    head = f"situation: {', '.join(r['situation']) or '—'}"
    if not r["ranking"]:
        return [head, r["reason"]]
    out = [head + " — a suggestion, not a decision; rate the one you used (vi_philosophy action=rate)"]
    for x in r["ranking"]:
        why = "; ".join(f"{m['tag']}: " + ("declared" if m["declared"] else "") + (", " if m["declared"] and (m["helped"] or m["not_helped"]) else "")
                        + (f"helped {m['helped']:g} / not {m['not_helped']:g}" if m["helped"] or m["not_helped"] else "") for m in x["matched"])
        out.append(f"- {x['name']} (score {x['score']}): {why}")
    return out
