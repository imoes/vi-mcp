"""Bandit — Thompson sampling per hint (stage 2, docs/TRAINING.md 4b), measured by the advantage over the tool without a hint.

Every hint keeps `daten.nuetzlich = {"ja": a, "nein": b, "n": shown}`. Not every success after showing is credited, only what goes beyond
the expected: p = success rate of the tool without a hint (base rate); success → a += 1 − p, failure → b += p.
An ineffective hint thus stays at a ≈ b in expectation, i.e. at 50 %; before, it rose with the tool's success rate (proximity is not
causation: measured 08.11.2026, a skill without content shown before Bash "helped 226 times"). When ordering, the router draws one sample per hint from
Beta(1 + a, 1 + b) — rarely shown hints have wide distributions and come up again by themselves (Russo et al. 2017, arXiv 1707.02038).
The counters are derived: sleep recomputes them from the stored experiences (`recompute`), live they are only updated incrementally.

Router ranking (exhaustive, named in `zugriff.router`):
  modell     — the learned model is active (stage 1, lift)
  bandit     — no active model, but at least one candidate already has counters
  heuristik  — neither: recency + importance + bonus
"""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict

from . import memory as g, names

HINT_KINDS = names.id_prefixes("insight", "rule", "search", "skill", "image", "page")  # ids of 0.66 (German) and later (English)


BASE_DAYS = 90
BASE_MIN = 10
#: v2 (0.70.1): the expected rate is the instance's own rate for the tool (≥ BASE_MIN actions without a hint), else the tool's, else
#: all — the strata metrics.hint_lift_matched uses (one definition of "expected"). Measured on a production copy (16.11.2026, 15,506
#: rated actions): it predicts newer actions without a hint better than the pooled tool rate (log loss 0.0967 vs 0.1017 on 3,962); no
#: hint shown ≥ 20× changed the sign of its lift. Rejected on the same copy: tool+host strata (0.0975, too thin) and the router's own
#: P(ok | no hint) (0.1245 vs 0.1006 — class-balanced scores are not calibrated probabilities).
METHOD_ID = "vorteil-v2"
_reason: dict = {"zeit": 0.0, "je": {}, "je_instanz": {}, "alle": 0.5}


def counter(o: g.MemoryObject) -> tuple[float, float]:
    n = o.data.get("useful") or {}
    return round(float(n.get("yes", 0)), 3), round(float(n.get("no", 0)), 3)


def shown(o: g.MemoryObject) -> int:
    return int((o.data.get("useful") or {}).get("n", 0))


def _observations(since: str | None = None):
    """(tool, ok, shown, per-hint labels) per rated action — _observations_of without the instance."""
    for _inst, tool, ok, shown, per in _observations_of(since):
        yield tool, ok, shown, per


def _observations_of(since: str | None = None):
    """(instance, tool, ok, shown, per-hint labels) per rated action — the label is scorer.label (0.55.0: the same as the router's: direct feedback,
    conversation grade, code stage, ok tag); actions answered from memory do not count. per-hint: {hint: (y, weight)}."""
    from . import scorer
    grades = scorer.grade_details()
    with g.lock:
        lines = g.db().execute("SELECT o.data, o.conversation, o.instance, (SELECT group_concat(tag, ' ') FROM tag t WHERE t.object_id = o.id AND (t.tag LIKE 'tool:%' OR t.tag LIKE 'ok:%')) "
                                "FROM object o WHERE o.kind = 'experience' AND o.mode = 'active'" + (" AND o.ts >= ?" if since else ""), (since,) if since else ()).fetchall()
    for data, serial, inst, tags in lines:
        tags = (tags or "").split()
        d = json.loads(data)
        v = d.get("before") or {}
        if v.get("from_memory"):
            continue
        ok_tag = True if "ok:yes" in tags else False if "ok:no" in tags else None
        lab = scorer.label(d, ok_tag, serial, grades)
        tool = next((t[5:] for t in tags if t.startswith("tool:")), None)
        if lab is None or not tool:
            continue
        shown = [h for h in v.get("shown", []) if h.startswith(HINT_KINDS)]
        # 17.11.2026: prompt and error hints count only where they got explicit feedback (vi_feedback) — no guessed labels
        fb = d.get("feedback") or {}
        shown += [h for h in (d.get("prompt_shown") or []) + (d.get("error_hints") or []) if h in fb and h not in shown and h.startswith(HINT_KINDS)]
        per = {h: scorer.label(d, ok_tag, serial, grades, hint=h)[:2] for h in shown}
        yield inst or "?", tool, bool(lab[0]), shown, per


def _base_rates() -> tuple[dict[str, float], float, dict[tuple[str, str], float]]:
    """Success rate per tool from actions without a shown hint; too few → all actions of the tool; none → over everything. Laplace-smoothed.
    v2: also per (instance, tool) from actions without a hint, only with ≥ BASE_MIN of them (thinner strata fall back to the tool)."""
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - BASE_DAYS * 86400))
    without, all_ = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    without_inst: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for inst, tool, ok, shown_flag, _per in _observations_of(since):
        for d in ((all_,) if shown_flag else (all_, without)):
            d[tool][0] += ok
            d[tool][1] += 1
        if not shown_flag:
            without_inst[(inst, tool)][0] += ok
            without_inst[(inst, tool)][1] += 1
    per_tool_rate = {t: (z[0] + 1) / (z[1] + 2) for t, z in all_.items()}
    per_tool_rate.update({t: (z[0] + 1) / (z[1] + 2) for t, z in without.items() if z[1] >= BASE_MIN})
    per_inst = {k: (z[0] + 1) / (z[1] + 2) for k, z in without_inst.items() if z[1] >= BASE_MIN}
    total = [sum(z[0] for z in all_.values()), sum(z[1] for z in all_.values())]
    return per_tool_rate, (total[0] + 1) / (total[1] + 2), per_inst


def _rate(per_tool_rate: dict, all_: float, per_inst: dict, tool: str | None, instance: str | None) -> float:
    """The expected rate of one action: its instance's own rate for the tool, else the tool's, else all (v2)."""
    if tool is None:
        return all_
    if instance is not None and (instance, tool) in per_inst:
        return per_inst[(instance, tool)]
    return per_tool_rate.get(tool, all_)


def base_rate(tool: str | None, instance: str | None = None) -> float:
    if time.time() - _reason["zeit"] > 300:
        per_tool_rate, all_, per_inst = _base_rates()
        _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_, je_instanz=per_inst)
    return _rate(_reason["je"], _reason["alle"], _reason["je_instanz"], tool, instance)


def recompute() -> dict:
    """Sleep: all hint counters from the experiences. Hints without a rated action lose old counters."""
    per_tool_rate, all_, per_inst = _base_rates()
    _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_, je_instanz=per_inst)
    sum_total: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0, 0, 0.0])  # yes, no, shown, succeeded, expected
    for inst, tool, _ok, shown_flag, per in _observations_of():
        p = _rate(per_tool_rate, all_, per_inst, tool, inst)
        for h in shown_flag:
            z = sum_total[h]
            y, w = per[h]  # 0.55.0: the hint's own label and its weight (direct feedback counts twice)
            if y:
                z[0] += w * (1 - p)
            else:
                z[1] += w * p
            z[2] += 1
            z[3] += y
            z[4] += p
    with g.lock:
        old = [r[0] for r in g.db().execute("SELECT id FROM object WHERE json_extract(data, '$.useful') IS NOT NULL")]
        for i in old:
            if i not in sum_total:
                g.update_data(i, lambda d: d.pop("useful", None))
        for h, (a, b, n, k, e) in sum_total.items():
            g.update_data(h, lambda d, v={"yes": round(a, 4), "no": round(b, 4), "n": n, "ok": k, "expected": round(e, 4), "method": METHOD_ID}: d.__setitem__("useful", v))
        g.db().commit()
    return {"hinweise": len(sum_total), "zurueckgesetzt": len([i for i in old if i not in sum_total]), "grundraten": {t: round(p, 3) for t, p in sorted(per_tool_rate.items(), key=lambda x: -x[1])[:8]},
            "methode": METHOD_ID, "grundraten_instanz": len(per_inst)}


def random_sample(o: g.MemoryObject, rnd: random.Random | None = None) -> float:
    yes, no = counter(o)
    return (rnd or random).betavariate(1 + yes, 1 + no)


def expectation(o: g.MemoryObject) -> float:
    yes, no = counter(o)
    return (1 + yes) / (2 + yes + no)


def has_counter(candidates: list[g.MemoryObject]) -> bool:
    return any(sum(counter(o)) > 0 for o in candidates)


def arrange(candidates: list[g.MemoryObject], rnd: random.Random | None = None) -> list[g.MemoryObject]:
    """Thompson sampling: one sample per candidate, descending. Stable on ties (heuristic order)."""
    samples = {o.id: random_sample(o, rnd) for o in candidates}
    return sorted(candidates, key=lambda o: -samples[o.id])


def book_entry(shown: list[str], ok: bool | None, tool: str | None = None, instance: str | None = None) -> int:
    """After the action: advantage over the base rate per shown hint. ok None (no result reported) does not count. Atomic in the DB."""
    if ok is None:
        return 0
    p = base_rate(tool, instance)
    field_name, value = ("yes", 1 - p) if ok else ("no", p)
    n = 0
    plus_ok = 1 if ok else 0
    with g.lock:
        for oid in shown:
            if not oid.startswith(HINT_KINDS):
                continue
            # increase the JSON counters in daten in place under the lock — not via the object class (no lost counter)
            # last_shown counts as use for housekeeping but does not change recency (no Matthew effect)
            def add(d, now=g.now()):
                c = d.get("useful")
                if not isinstance(c, dict):
                    c = d["useful"] = {}
                c[field_name] = (c.get(field_name) or 0) + value
                c["n"] = (c.get("n") or 0) + 1
                c["ok"] = (c.get("ok") or 0) + plus_ok
                c["expected"] = (c.get("expected") or 0) + p
                d["last_shown"] = now
            n += g.update_data(oid, add)
        g.db().commit()
    return n


def rebook(shown: list[str], tool: str | None = None, instance: str | None = None) -> int:
    """The scorer finds afterwards that an action counted as successful failed: the credit (1 − p) is reverted, p is added as no."""
    p = base_rate(tool, instance)
    n = 0
    with g.lock:
        for oid in shown:
            if oid.startswith(HINT_KINDS):
                def back(d):
                    c = d.get("useful")
                    if not isinstance(c, dict):
                        c = d["useful"] = {}
                    c["yes"] = max((c.get("yes") or 0) - (1 - p), 0)
                    c["no"] = (c.get("no") or 0) + p
                n += g.update_data(oid, back)
        g.db().commit()
    return n


def lift(o: g.MemoryObject) -> float | None:
    """Success rate after showing minus the expected rate of the tool, as a fraction; None without data."""
    z = o.data.get("useful") or {}
    n = int(z.get("n", 0))
    return (z.get("ok", 0) - z.get("expected", 0)) / n if n and "expected" in z else None


def mark(o: g.MemoryObject) -> str:
    """0.57.0: the compact marker on every hint line — what the VI has measured about this hint, so the reading AI can weigh it:
    "measured +12 pts/40×" (success after showing over the tool's base rate, N showings) or "unmeasured". Pure apart from the object."""
    z = o.data.get("useful") or {}
    n = int(z.get("n", 0))
    if not n or "expected" not in z:
        return "unmeasured"
    return f"measured {lift(o) * 100:+.0f} pts/{n}×"


def line(o: g.MemoryObject) -> str:
    z = o.data.get("useful") or {}
    n = int(z.get("n", 0))
    if not n:
        return "never rated after being shown"
    if "expected" not in z:
        return f"{n}× shown, effect not computed yet"
    return f"{n}× shown, success afterwards {z['ok'] / n * 100:.0f} % instead of expected {z['expected'] / n * 100:.0f} % ({lift(o) * 100:+.0f} points)"
