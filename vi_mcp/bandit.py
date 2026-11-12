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

from . import memory as g

HINT_KINDS = ("erkenntnis:", "regel:", "suche:", "skill:", "bild:", "seite:")


BASE_DAYS = 90
BASE_MIN = 10
METHOD_ID = "vorteil-v1"
_reason: dict = {"zeit": 0.0, "je": {}, "alle": 0.5}


def counter(o: g.MemoryObject) -> tuple[float, float]:
    n = o.data.get("nuetzlich") or {}
    return round(float(n.get("ja", 0)), 3), round(float(n.get("nein", 0)), 3)


def shown(o: g.MemoryObject) -> int:
    return int((o.data.get("nuetzlich") or {}).get("n", 0))


def _observations(since: str | None = None):
    """(tool, ok, shown, per-hint labels) per rated action — the label is scorer.label (0.55.0: the same as the router's: direct feedback,
    conversation grade, code stage, ok tag); actions answered from memory do not count. per-hint: {hint: (y, weight)}."""
    from . import scorer
    grades = scorer.grade_details()
    with g.lock:
        lines = g.db().execute("SELECT o.daten, o.gespraech, (SELECT group_concat(tag, ' ') FROM tag t WHERE t.objekt_id = o.id AND (t.tag LIKE 'tool:%' OR t.tag LIKE 'ok:%')) "
                                "FROM objekt o WHERE o.art = 'erfahrung' AND o.modus = 'aktiv'" + (" AND o.zeit >= ?" if since else ""), (since,) if since else ()).fetchall()
    for data, serial, tags in lines:
        tags = (tags or "").split()
        d = json.loads(data)
        v = d.get("vorher") or {}
        if v.get("aus_gedaechtnis"):
            continue
        ok_tag = True if "ok:ja" in tags else False if "ok:nein" in tags else None
        lab = scorer.label(d, ok_tag, serial, grades)
        tool = next((t[5:] for t in tags if t.startswith("tool:")), None)
        if lab is None or not tool:
            continue
        shown = [h for h in v.get("gezeigt", []) if h.startswith(HINT_KINDS)]
        per = {h: scorer.label(d, ok_tag, serial, grades, hint=h)[:2] for h in shown}
        yield tool, bool(lab[0]), shown, per


def _base_rates() -> tuple[dict[str, float], float]:
    """Success rate per tool from actions without a shown hint; too few → all actions of the tool; none → over everything. Laplace-smoothed."""
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - BASE_DAYS * 86400))
    without, all_ = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for tool, ok, shown_flag, _per in _observations(since):
        for d in ((all_,) if shown_flag else (all_, without)):
            d[tool][0] += ok
            d[tool][1] += 1
    per_tool_rate = {t: (z[0] + 1) / (z[1] + 2) for t, z in all_.items()}
    per_tool_rate.update({t: (z[0] + 1) / (z[1] + 2) for t, z in without.items() if z[1] >= BASE_MIN})
    total = [sum(z[0] for z in all_.values()), sum(z[1] for z in all_.values())]
    return per_tool_rate, (total[0] + 1) / (total[1] + 2)


def base_rate(tool: str) -> float:
    if time.time() - _reason["zeit"] > 300:
        per_tool_rate, all_ = _base_rates()
        _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_)
    return _reason["je"].get(tool, _reason["alle"])


def recompute() -> dict:
    """Sleep: all hint counters from the experiences. Hints without a rated action lose old counters."""
    per_tool_rate, all_ = _base_rates()
    _reason.update(zeit=time.time(), je=per_tool_rate, alle=all_)
    sum_total: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0, 0, 0.0])  # yes, no, shown, succeeded, expected
    for tool, _ok, shown_flag, per in _observations():
        p = per_tool_rate.get(tool, all_)
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
        old = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE json_extract(daten, '$.nuetzlich') IS NOT NULL")]
        for i in old:
            if i not in sum_total:
                g.update_data(i, lambda d: d.pop("nuetzlich", None))
        for h, (a, b, n, k, e) in sum_total.items():
            g.update_data(h, lambda d, v={"ja": round(a, 4), "nein": round(b, 4), "n": n, "ok": k, "erwartet": round(e, 4), "verfahren": METHOD_ID}: d.__setitem__("nuetzlich", v))
        g.db().commit()
    return {"hinweise": len(sum_total), "zurueckgesetzt": len([i for i in old if i not in sum_total]), "grundraten": {t: round(p, 3) for t, p in sorted(per_tool_rate.items(), key=lambda x: -x[1])[:8]}}


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


def book_entry(shown: list[str], ok: bool | None, tool: str | None = None) -> int:
    """After the action: advantage over the base rate per shown hint. ok None (no result reported) does not count. Atomic in the DB."""
    if ok is None:
        return 0
    p = base_rate(tool) if tool else _reason["alle"]
    field_name, value = ("ja", 1 - p) if ok else ("nein", p)
    n = 0
    plus_ok = 1 if ok else 0
    with g.lock:
        for oid in shown:
            if not oid.startswith(HINT_KINDS):
                continue
            # increase the JSON counters in daten in place under the lock — not via the object class (no lost counter)
            # zuletzt_gezeigt counts as use for housekeeping but does not change recency (no Matthew effect)
            def add(d, now=g.now()):
                c = d.get("nuetzlich")
                if not isinstance(c, dict):
                    c = d["nuetzlich"] = {}
                c[field_name] = (c.get(field_name) or 0) + value
                c["n"] = (c.get("n") or 0) + 1
                c["ok"] = (c.get("ok") or 0) + plus_ok
                c["erwartet"] = (c.get("erwartet") or 0) + p
                d["zuletzt_gezeigt"] = now
            n += g.update_data(oid, add)
        g.db().commit()
    return n


def rebook(shown: list[str], tool: str | None = None) -> int:
    """The scorer finds afterwards that an action counted as successful failed: the credit (1 − p) is reverted, p is added as no."""
    p = base_rate(tool) if tool else _reason["alle"]
    n = 0
    with g.lock:
        for oid in shown:
            if oid.startswith(HINT_KINDS):
                def back(d):
                    c = d.get("nuetzlich")
                    if not isinstance(c, dict):
                        c = d["nuetzlich"] = {}
                    c["ja"] = max((c.get("ja") or 0) - (1 - p), 0)
                    c["nein"] = (c.get("nein") or 0) + p
                n += g.update_data(oid, back)
        g.db().commit()
    return n


def lift(o: g.MemoryObject) -> float | None:
    """Success rate after showing minus the expected rate of the tool, as a fraction; None without data."""
    z = o.data.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    return (z.get("ok", 0) - z.get("erwartet", 0)) / n if n and "erwartet" in z else None


def mark(o: g.MemoryObject) -> str:
    """0.57.0: the compact marker on every hint line — what the VI has measured about this hint, so the reading AI can weigh it:
    "measured +12 pts/40×" (success after showing over the tool's base rate, N showings) or "unmeasured". Pure apart from the object."""
    z = o.data.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    if not n or "erwartet" not in z:
        return "unmeasured"
    return f"measured {lift(o) * 100:+.0f} pts/{n}×"


def line(o: g.MemoryObject) -> str:
    z = o.data.get("nuetzlich") or {}
    n = int(z.get("n", 0))
    if not n:
        return "never rated after being shown"
    if "erwartet" not in z:
        return f"{n}× shown, effect not computed yet"
    return f"{n}× shown, success afterwards {z['ok'] / n * 100:.0f} % instead of expected {z['erwartet'] / n * 100:.0f} % ({lift(o) * 100:+.0f} points)"
