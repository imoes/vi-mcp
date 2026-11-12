"""Observation points — how to tell whether the VI is useful.

Hint lift: success rate of actions before which the memory showed something (insight, rule, learned
search), compared with actions without a hint. If it does not rise, the assumption "hints help" is wrong
(docs/ARCHITECTURE.md, "Reinforcement happens on success"). Calls answered from memory do not count
(they had no action). Below AT_LEAST cases per side the result is "too little data" — named, no limbo.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import memory as g

AT_LEAST = 10


def _with_hint(o: g.MemoryObject) -> bool:
    v = o.data.get("vorher") or {}
    return any(not oid.startswith("antwort:") for oid in v.get("gefunden", []))


_GRADES: dict = {"t": 0.0, "v": {}, "db": None}


def _ok(o) -> bool:
    """The action's label (scorer.label without a hint), conversation grades cached for a minute."""
    import time
    from . import scorer
    if time.time() - _GRADES["t"] > 60 or _GRADES["db"] is not g.db():  # another database (tests, migration): read again
        _GRADES.update(t=time.time(), v=scorer.grade_details(), db=g.db())
    lab = scorer.label(o.data, "ok:ja" in o.hashtags, o.conversation, _GRADES["v"])
    return bool(lab and lab[0])


def hint_lift(hours: float = 24, tool: str | None = None, viewer: str | None = None) -> dict:
    """{'mit': {'n', 'ok'}, 'ohne': {'n', 'ok'}, 'quote_mit', 'quote_ohne', 'lift', 'urteil', 'je_tool': {...}}"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    filt = "art:erfahrung (ok:ja OR ok:nein)" + (f" tool:{tool}" if tool else "")
    per_tool: dict[str, dict] = {}
    total = {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}}
    for _, o, _g in g.recall(filt, limit=5000, viewer=viewer):
        if o.ts < since or (o.data.get("vorher") or {}).get("aus_gedaechtnis"):
            continue
        t = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        page = "mit" if _with_hint(o) else "ohne"
        ok = _ok(o)  # 0.55.0: scorer.label — the same label as router and bandit
        for target in (total, per_tool.setdefault(t, {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}})):
            target[page]["n"] += 1
            target[page]["ok"] += 1 if ok else 0
    return {**total, **_rate(total), "je_tool": {t: {**d, **_rate(d)} for t, d in per_tool.items()}, "stunden": hours}


def hint_lift_matched(hours: float = 24, viewer: str | None = None) -> dict:
    """0.49.0: hint lift within the same instance and tool (Mantel-Haenszel risk difference). The raw comparison mixes populations:
    measured on production (7 days to 11.11.2026) it said −20 points, while claude-code alone showed −1 (97 % vs 98 %) and the other
    instances, mostly centralstation's `analyse` with a 39 % base rate and nearly always a hint, about +9 — Simpson's paradox."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    strata: dict[tuple[str, str], dict] = {}
    for _, o, _g in g.recall("art:erfahrung (ok:ja OR ok:nein)", limit=20000, viewer=viewer):
        if o.ts < since or (o.data.get("vorher") or {}).get("aus_gedaechtnis"):
            continue
        t = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        d = strata.setdefault((o.instance or "?", t), {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}})
        ok = _ok(o)  # 0.55.0: scorer.label — the same label as router and bandit
        side = d["mit" if _with_hint(o) else "ohne"]
        side["n"] += 1
        side["ok"] += 1 if ok else 0
    num = den = 0.0
    used = {"mit": 0, "ohne": 0}
    total_with = sum(d["mit"]["n"] for d in strata.values())
    for d in strata.values():
        a, b = d["mit"], d["ohne"]
        if not a["n"] or not b["n"]:
            continue
        w = a["n"] * b["n"] / (a["n"] + b["n"])
        num += w * (a["ok"] / a["n"] - b["ok"] / b["n"])
        den += w
        used["mit"] += a["n"]
        used["ohne"] += b["n"]
    lift = num / den if den else None
    if used["mit"] < AT_LEAST or used["ohne"] < AT_LEAST or lift is None:
        verdict = f"too little data in comparable strata (at least {AT_LEAST} per side)"
    elif lift > 0.05:
        verdict = "hints help"
    elif lift < -0.05:
        verdict = "hints hurt — check weighting"
    else:
        verdict = "no measurable difference"
    return {"lift": lift, "urteil": verdict, "schichten": sum(1 for d in strata.values() if d["mit"]["n"] and d["ohne"]["n"]),
            "mit_vergleichbar": used["mit"], "mit_gesamt": total_with, "ohne_vergleichbar": used["ohne"], "stunden": hours}


def matched_line(m: dict) -> str:
    return (f"matched within instance and tool (Mantel-Haenszel): " + (f"lift {m['lift'] * 100:+.0f} points" if m["lift"] is not None else "—")
            + f" over {m['schichten']} stratum/strata, {m['mit_vergleichbar']} of {m['mit_gesamt']} actions with a hint comparable → {m['urteil']}")


def _rate(d: dict) -> dict:
    qm = d["mit"]["ok"] / d["mit"]["n"] if d["mit"]["n"] else None
    qo = d["ohne"]["ok"] / d["ohne"]["n"] if d["ohne"]["n"] else None
    if d["mit"]["n"] < AT_LEAST or d["ohne"]["n"] < AT_LEAST:
        verdict = f"too little data (at least {AT_LEAST} per side)"
    elif qm > qo + 0.05:
        verdict = "higher with hints — raw, not a verdict (see the matched and randomized lines)"
    elif qm < qo - 0.05:
        # 0.57.1: the raw comparison mixes populations (Simpson) — it is no verdict on the hints; the matched and the randomized lines are
        verdict = "lower with hints — raw, mixes instances and tools, not a verdict (see the matched and randomized lines)"
    else:
        verdict = "no measurable difference"
    return {"quote_mit": qm, "quote_ohne": qo, "lift": (qm - qo) if qm is not None and qo is not None else None, "urteil": verdict}


def line(l: dict) -> str:
    f = lambda q: "—" if q is None else f"{q * 100:.0f} %"
    return (f"Hint lift {l['stunden']:g} h: with hint {l['mit']['ok']}/{l['mit']['n']} ok ({f(l['quote_mit'])}), "
            f"without {l['ohne']['ok']}/{l['ohne']['n']} ok ({f(l['quote_ohne'])})"
            + (f", lift {l['lift'] * 100:+.0f} points" if l["lift"] is not None else "") + f" → {l['urteil']}")


NEW_DAYS = 7


def lift_by_age(hours: float = 24 * 7, viewer: str | None = None, new_days: float = NEW_DAYS) -> dict:
    """0.29.0: cold-start observation point — is a hint weaker while it is new? Per shown hint (pair): success minus the base rate of
    the tool (bandit.base_rate: success without a hint), split by the hint's age at the time it was shown (≤ new_days = "neu").
    The base rate removes the tool mix; what it cannot remove: new hints may come with new kinds of work (named, not hidden).
    A hint that no longer exists is counted as "unbekannt", not dropped."""
    from . import bandit
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    acc = {k: {"n": 0, "ok": 0, "vorteil": 0.0} for k in ("neu", "alt", "unbekannt")}
    born: dict[str, str | None] = {}
    for _, o, _g in g.recall("art:erfahrung (ok:ja OR ok:nein)", limit=5000, viewer=viewer):
        v = o.data.get("vorher") or {}
        if o.ts < since or v.get("aus_gedaechtnis"):
            continue
        shown = [h for h in v.get("gezeigt", []) if h.startswith(bandit.HINT_KINDS)]
        if not shown:
            continue
        tool = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        ok = _ok(o)  # 0.55.0: scorer.label — the same label as router and bandit
        p = bandit.base_rate(tool)
        for h in shown:
            if h not in born:
                hint = g.load(h)
                born[h] = hint.ts if hint else None
            if born[h] is None:
                k = "unbekannt"
            else:
                k = "neu" if (datetime.fromisoformat(o.ts) - datetime.fromisoformat(born[h])).total_seconds() <= new_days * 86400 else "alt"
            acc[k]["n"] += 1
            acc[k]["ok"] += 1 if ok else 0
            acc[k]["vorteil"] += (1 if ok else 0) - p
    for d in acc.values():
        d["vorteil"] = d["vorteil"] / d["n"] if d["n"] else None
    a, b = acc["neu"], acc["alt"]
    if a["n"] < AT_LEAST or b["n"] < AT_LEAST:
        verdict = f"too little data (at least {AT_LEAST} shown hints per age group)"
    elif a["vorteil"] < b["vorteil"] - 0.05:
        verdict = "new hints weaker — cold start is a real gap"
    elif a["vorteil"] > b["vorteil"] + 0.05:
        verdict = "new hints stronger"
    else:
        verdict = "no measurable cold-start gap"
    return {**acc, "urteil": verdict, "stunden": hours, "neu_tage": new_days}


def age_line(l: dict) -> str:
    f = lambda d: "—" if d["vorteil"] is None else f"{d['vorteil'] * 100:+.0f} points"
    return (f"Hints by age {l['stunden'] / 24:g} d: new (≤ {l['neu_tage']:g} d) {l['neu']['n']} shown, advantage over the tool's base rate "
            f"{f(l['neu'])}; older {l['alt']['n']} shown, {f(l['alt'])}"
            + (f"; {l['unbekannt']['n']} of hints that no longer exist" if l["unbekannt"]["n"] else "") + f" → {l['urteil']}")


def _randomized(hours: float, viewer: str | None):
    """Actions in which the ε-exploration could have happened (a candidate further back existed), with their label. Pure apart from reading."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    for _, o, _g in g.recall("art:erfahrung (ok:ja OR ok:nein)", limit=50000, viewer=viewer):
        v = o.data.get("vorher") or {}
        if o.ts < since or v.get("aus_gedaechtnis") or not v.get("rest_n") or not v.get("gezeigt"):
            continue
        yield o, v, _ok(o)


def exploration_effect(hours: float = 168, viewer: str | None = None) -> dict:
    """0.57.0: the one randomized experiment the VI runs — with probability ε the last hint slot goes to a random candidate from further
    back. Success of actions with exploration minus without, Mantel-Haenszel within (instance, tool, router), with its standard error.
    Negative = the ranked hint beats a random one (the ranking helps); about 0 = the ranking adds nothing over chance. Causal, because
    whether an action explores is a coin flip (Li et al. 2010, arXiv:1003.0146)."""
    strata: dict[tuple, dict] = {}
    for o, v, ok in _randomized(hours, viewer):
        t = next((x[5:] for x in o.hashtags if x.startswith("tool:")), "?")
        c = strata.setdefault((o.instance or "?", t, v.get("router")), {True: [0, 0], False: [0, 0]})[bool(v.get("exploration"))]
        c[0] += ok
        c[1] += 1
    num = den = var = 0.0
    n_e = n_r = used = 0
    for c in strata.values():
        (a, n1), (b, n0) = c[True], c[False]
        if not n1 or not n0:
            continue
        w = n1 * n0 / (n1 + n0)
        p1, p0 = a / n1, b / n0
        num += w * (p1 - p0)
        den += w
        var += w * w * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
        n_e, n_r, used = n_e + n1, n_r + n0, used + 1
    if not den or n_e < 30:
        return {"zustand": "zu_wenig", "explorationen": n_e, "urteil": f"{n_e} exploration actions in comparable strata — at least 30 needed"}
    d, se = num / den, math.sqrt(var) / den
    verdict = ("the ranked hint beats a random candidate" if d < -2 * se else "a random candidate beats the ranked hint" if d > 2 * se
               else "no difference beyond 2 standard errors")
    return {"zustand": "gemessen", "differenz": round(d, 4), "standardfehler": round(se, 4), "explorationen": n_e, "regulaer": n_r,
            "schichten": used, "urteil": f"exploration − regular {d * 100:+.1f} ± {se * 100:.1f} points ({n_e} vs {n_r} actions, {used} strata): {verdict}"}


def ips_lift(hours: float = 24 * 30, viewer: str | None = None, min_shown: int = 5) -> dict[str, dict]:
    """0.57.0: per hint, the effect of showing it, from the logged propensities (self-normalised inverse propensity scoring,
    Swaminathan & Joachims 2015): over the actions where it was offered with 0 < p < 1, the weighted success when shown (weight 1/p)
    minus when not shown (weight 1/(1 − p)). Only the randomized offers count — a hint that was always shown has no counterfactual."""
    acc: dict[str, list[float]] = {}
    for _o, v, ok in _randomized(hours, viewer):
        shown = set(v.get("gezeigt") or [])
        for h, p in (v.get("angebot") or {}).items():
            if not 0.0 < p < 1.0:
                continue
            a = acc.setdefault(h, [0.0, 0.0, 0.0, 0.0, 0])  # yes-weighted shown, weight shown, yes-weighted not shown, weight not, n shown
            if h in shown:
                a[0] += ok / p
                a[1] += 1 / p
                a[4] += 1
            else:
                a[2] += ok / (1 - p)
                a[3] += 1 / (1 - p)
    out = {}
    for h, (ys, ws, yn, wn, n) in acc.items():
        if n >= min_shown and ws and wn:
            out[h] = {"lift": round(ys / ws - yn / wn, 4), "gezeigt": n}
    return out
