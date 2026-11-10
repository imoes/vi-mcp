"""Observation points — how to tell whether the VI is useful.

Hint lift: success rate of actions before which the memory showed something (insight, rule, learned
search), compared with actions without a hint. If it does not rise, the assumption "hints help" is wrong
(docs/ARCHITECTURE.md, "Reinforcement happens on success"). Calls answered from memory do not count
(they had no action). Below AT_LEAST cases per side the result is "too little data" — named, no limbo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import memory as g

AT_LEAST = 10


def _with_hint(o: g.MemoryObject) -> bool:
    v = o.data.get("vorher") or {}
    return any(not oid.startswith("antwort:") for oid in v.get("gefunden", []))


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
        s = o.data.get("score")  # the scorer's verdict beats "tool without error"
        ok = s["note"] >= 0.5 if s else "ok:ja" in o.hashtags
        for target in (total, per_tool.setdefault(t, {"mit": {"n": 0, "ok": 0}, "ohne": {"n": 0, "ok": 0}})):
            target[page]["n"] += 1
            target[page]["ok"] += 1 if ok else 0
    return {**total, **_rate(total), "je_tool": {t: {**d, **_rate(d)} for t, d in per_tool.items()}, "stunden": hours}


def _rate(d: dict) -> dict:
    qm = d["mit"]["ok"] / d["mit"]["n"] if d["mit"]["n"] else None
    qo = d["ohne"]["ok"] / d["ohne"]["n"] if d["ohne"]["n"] else None
    if d["mit"]["n"] < AT_LEAST or d["ohne"]["n"] < AT_LEAST:
        verdict = f"too little data (at least {AT_LEAST} per side)"
    elif qm > qo + 0.05:
        verdict = "hints help"
    elif qm < qo - 0.05:
        verdict = "hints hurt — assumption refuted, check weighting"
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
        s = o.data.get("score")
        ok = (s["note"] >= 0.5) if s else "ok:ja" in o.hashtags
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
