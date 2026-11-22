"""Z7: which shown hint does the agent use? — a per-hint use rate from the agents' own declarations, tested against the bandit per
conversation.

The label: an action whose agent DECLARED which shown hints it used (`data.declared`, written by `intuition.declare_used` from
`vi_after(used=[…])` and the feedback hook's `vi_feedback(before_id, used=[…])`) with at least two shown hints, at least one used and
one not — one labeller, one moment, both classes. Not the implicit `data.used` (`genutzt`, `intuition.adopted`, a token-reuse
heuristic): its placebo check failed — hints held back at random, which the agent never saw, were "adopted" as often as shown ones
(risk ratio 0.79, 95 % CI 0.62–1.03, production copy 22.11.2026, docs/PREREG_Z7B_WITHIN_ACTION.md). On that heuristic label a per-hint
rate ranked at 0.84 — it ranks how common a hint's tokens are, not whether it is used. So the within-action design of that test is kept,
the label is not, and this ranking has no offline evidence of its own yet: it waits for declared labels.

Score of a hint: Beta posterior mean (m·S + used) / (S + shown), S = PRIOR_S, m = the declared use rate of the hint's kind, the overall
rate without a kind.

The ranking replaces the bandit only in conversations of the arm "use_rate" (SHARE of the conversations, a stable hash per
conversation; 0 = off, the default) and only while no learned router model is active. Propensities, the ε slot and the random
hold-back stay as they are, so the arms remain comparable. Every decision logs the arm and the scores of the candidates
(before.use_rate_arm, before.use_rate_scores) — also in the bandit arm, as a shadow."""
from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict

from . import memory as g, names

METHOD_ID = "use-rate-v1"
#: prior strength of the Beta posterior — s = 5 had the lowest log loss on the inner validation of PREREG_Z7B (heuristic label; to be
#: re-chosen once declared labels exist)
PRIOR_S = 5.0
#: share of conversations in the arm "use_rate" (config use_rate_share, at most 0.5; 0 = off)
SHARE = 0.0
#: how long the kind rates are cached (s)
CACHE_S = 300
_kinds: dict = {"t": 0.0, "db": None, "rates": {}, "all": 0.5}


def kind_of(hint_id: str) -> str:
    """The hint's kind in English — the same mapping as learning.hint_features (old German ids included)."""
    return names.english(names.KINDS, hint_id.split(":")[0])


def observations(since: str | None = None):
    """(shown hints, used set) per labelled action: data.declared (the agent's own declaration), ≥ 2 shown hints, at least one used
    and one not. Never data.used — the implicit adoption heuristic failed its placebo check (module docstring)."""
    from .bandit import HINT_KINDS
    with g.lock:
        rows = g.db().execute("SELECT data FROM object WHERE kind = 'experience' AND mode = 'active'" + (" AND ts >= ?" if since else ""),
                              (since,) if since else ()).fetchall()
    for (data,) in rows:
        d = json.loads(data)
        dec = d.get("declared")
        used = dec.get("used") if isinstance(dec, dict) else None
        if not isinstance(used, list):
            continue
        shown = [h for h in (d.get("before") or {}).get("shown", []) if h.startswith(HINT_KINDS)]
        if len(shown) < 2:
            continue
        u = {h for h in shown if h in used}
        if 0 < len(u) < len(shown):
            yield shown, u


def recompute() -> dict:
    """Sleep / on demand: the use counters of every hint from the experiences (data.use_rate = {used, shown, method}); hints that lost
    all labelled actions lose their counters (counted, not silent)."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    actions = 0
    for shown, used in observations():
        actions += 1
        for h in shown:
            counts[h][0] += h in used
            counts[h][1] += 1
    with g.lock:
        old = [r[0] for r in g.db().execute("SELECT id FROM object WHERE json_extract(data, '$.use_rate') IS NOT NULL")]
        dropped = [i for i in old if i not in counts]
        for i in dropped:
            g.update_data(i, lambda d: d.pop("use_rate", None))
        for h, (k, n) in counts.items():
            g.update_data(h, lambda d, v={"used": k, "shown": n, "method": METHOD_ID}: d.__setitem__("use_rate", v))
        g.db().commit()
    _kinds["t"] = 0.0  # the kind rates follow at once
    return {"actions": actions, "hints": len(counts), "dropped": len(dropped), "method": METHOD_ID}


def counter(o: g.MemoryObject) -> tuple[int, int]:
    c = o.data.get("use_rate") or {}
    return int(c.get("used", 0)), int(c.get("shown", 0))


def kind_rates() -> tuple[dict[str, float], float]:
    """Use rate per hint kind and overall, Laplace-smoothed, from the stored counters; cached CACHE_S (another database: read again)."""
    if time.time() - _kinds["t"] > CACHE_S or _kinds["db"] is not g.db():
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        with g.lock:
            # the object is read whole and parsed here: a JSON object out of json_extract is not portable SQL (AGENTS.md, PostgreSQL)
            rows = g.db().execute("SELECT id, data FROM object WHERE json_extract(data, '$.use_rate') IS NOT NULL").fetchall()
        for oid, data in rows:
            c = json.loads(data).get("use_rate") or {}
            per[kind_of(oid)][0] += int(c.get("used", 0))
            per[kind_of(oid)][1] += int(c.get("shown", 0))
        total = [sum(v[0] for v in per.values()), sum(v[1] for v in per.values())]
        _kinds.update(t=time.time(), db=g.db(), rates={k: (v[0] + 1) / (v[1] + 2) for k, v in per.items()},
                      all=(total[0] + 1) / (total[1] + 2))
    return _kinds["rates"], _kinds["all"]


def score(o: g.MemoryObject, rates: tuple[dict[str, float], float] | None = None) -> float:
    per_kind, overall = rates or kind_rates()
    m = per_kind.get(kind_of(o.id), overall)
    k, n = counter(o)
    return (m * PRIOR_S + k) / (PRIOR_S + n)


def scores(candidates: list[g.MemoryObject]) -> dict[str, float]:
    rates = kind_rates()
    return {o.id: round(score(o, rates), 4) for o in candidates}


def arrange(candidates: list[g.MemoryObject]) -> list[g.MemoryObject]:
    """Highest use rate first; stable on ties (the heuristic order). Deterministic — the propensities stay those of the ε slot."""
    s = scores(candidates)
    return sorted(candidates, key=lambda o: -s[o.id])


def arm(conversation: str | None) -> str | None:
    """"use_rate" / "bandit" for a conversation; None without one or while the test is off. Stable within a conversation."""
    if not conversation or SHARE <= 0:
        return None
    x = int(hashlib.sha256(f"use_rate|{conversation}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "use_rate" if x < SHARE else "bandit"
