"""Weight audit (0.29.0) — fixed rules that read the router weights after training and name what looks wrong.

The router is taught through labels (scorer verdicts, direct feedback), never by writing weights. This audit only reads: it never
changes a weight, a mode or a hint. Every finding names its class, the feature or hint and the numbers that triggered it, so a session
can follow it up with vi_why / vi_object and, if the hint is wrong, vi_refute. Fixed rules instead of a language model: the classes are
checkable arithmetic, and a model reading the weights could be steered by the hint texts it would also see (AGENTS.md: language-model
verdicts only tighten).

Classes (exhaustive; "ok" when none applies):
  dominant      one feature carries the model: |w| ≥ DOMINANT_FACTOR × the DOMINANT_RANK-th largest |w| and ≥ DOMINANT_MIN
  contradicts   the model's view of a hint and the hint's measured usefulness (bandit, ≥ CONTRA_MIN_N shown) point in opposite
                directions; since 0.30.0 also a meaning-group weight (content:<c>) against the pooled measured usefulness of the group's
                hints. 0.70.1: the model's view of a hint is NOT its own weight hint:<id> alone but what the router computes for it —
                the logit difference with vs without the hint (learning.why: hint:<id> + content group + kind + age + rules +
                hint_n), averaged over the showings the measurement counts. Seen live 18.11.2026: "weight +1.94, but measured −8
                points" — the hint's own weight +1.41 offset its group (−0.98) and age:new (−1.20); the model's view was −0.49, in
                line with the measurement. Comparing one summand with the whole is an invalid derivation.
  network       a hint from the network (origin:p2p) with a strong positive weight and no confirmation by another instance
  hour          an hour feature (hour:HH) is among the strongest weights — time of day as a cause is post hoc
"""
from __future__ import annotations

import json

from . import memory as g

DOMINANT_FACTOR = 3.0
DOMINANT_RANK = 5
DOMINANT_MIN = 1.0
STRONG = 0.5
CONTRA_MIN_N = 20
CONTRA_MIN_LIFT = 0.05
HOUR_TOP = 3
#: the newest showings of a hint that the model's view is averaged over (each costs one learning.why)
SHOWINGS_MAX = 200
CLASSES = ("dominant", "contradicts", "network", "hour")


def model_view(m, hid: str) -> tuple[float, int]:
    """(mean logit difference with vs without the hint, showings it is averaged over) — the router's own arithmetic (learning.why)
    for each stored showing (experience data.before: triggers, time). Without a stored showing: the hint's features now, no situation
    (0 showings named)."""
    from . import learning
    with g.lock:
        rows = g.db().execute("SELECT ts, data FROM object WHERE kind = 'experience' AND mode = 'active' AND data LIKE ? "
                              "ORDER BY ts DESC LIMIT ?", (f'%"{hid}"%', SHOWINGS_MAX)).fetchall()
    vals = []
    for ts, data in rows:
        v = (json.loads(data) or {}).get("before") or {}
        if hid in (v.get("shown") or []):
            w = learning.why(m, hid, v.get("triggers") or [], ts)
            vals.append(w["distinguishing_sum"] + w["same_for_all"])
    if vals:
        return sum(vals) / len(vals), len(vals)
    w = learning.why(m, hid, [], None)
    return w["distinguishing_sum"] + w["same_for_all"], 0


def audit(m: g.MemoryObject | None = None) -> dict:
    """{"zustand": "ok" | "befunde" | "kein_modell", "befunde": [{"klasse", "merkmal", "grund"}], "je_klasse": {klasse: n}}."""
    from . import bandit, learning
    m = m or learning.model()
    if m is None or not m.data.get("gewichte"):
        return {"zustand": "kein_modell", "grund": "no trained router weights yet", "befunde": [], "je_klasse": {}}
    w = m.data["gewichte"]
    ranked = sorted(w.items(), key=lambda kv: -abs(kv[1]))
    findings = []
    if len(ranked) >= DOMINANT_RANK:
        (top, tw), ref = ranked[0], abs(ranked[DOMINANT_RANK - 1][1])
        if abs(tw) >= DOMINANT_MIN and abs(tw) >= DOMINANT_FACTOR * ref:
            findings.append({"klasse": "dominant", "merkmal": top,
                             "grund": f"|w| {abs(tw):.2f} ≥ {DOMINANT_FACTOR:g} × {ref:.2f} (rank {DOMINANT_RANK})"})
    for k, v in ranked:
        if not k.startswith("hint:") or abs(v) < STRONG:
            continue
        hint = g.load(k.split(":", 1)[1])
        if hint is None:
            continue
        lift = bandit.lift(hint)
        if lift is not None and bandit.shown(hint) >= CONTRA_MIN_N and abs(lift) >= CONTRA_MIN_LIFT:
            view, n_view = model_view(m, hint.id)
            if abs(view) >= STRONG and (lift > 0) != (view > 0):
                where = f"over its {n_view} newest showings" if n_view else "now, no stored showing"
                findings.append({"klasse": "contradicts", "merkmal": k,
                                 "grund": f"model view {view:+.2f} (logit with vs without, {where}; own weight {v:+.2f}), but measured "
                                          f"{lift * 100:+.0f} points over {bandit.shown(hint)} showings"})
        if v > 0 and "origin:p2p" in hint.hashtags and not hint.foreign_confirmations():
            publisher = next((t.split(":", 1)[1] for t in hint.hashtags if t.startswith("publisher:")), "?")
            findings.append({"klasse": "network", "merkmal": k,
                             "grund": f"weight {v:+.2f} for a hint from the network ({publisher}) that no other instance confirmed"})
    for k, v in ranked:  # 0.30.0: a group weight can push down hints that are measured as good (seen 10.11.2026: inhalt:21 −0.72)
        if not k.startswith("content:") or not k[len("content:"):].isdigit() or abs(v) < STRONG:
            continue
        lift, n, members = _group_lift(int(k[len("content:"):]))
        if lift is not None and n >= CONTRA_MIN_N and abs(lift) >= CONTRA_MIN_LIFT and (lift > 0) != (v > 0):
            findings.append({"klasse": "contradicts", "merkmal": k,
                             "grund": f"group weight {v:+.2f}, but its {members} rated hints measured {lift * 100:+.0f} points over {n} showings"})
    for k, v in ranked[:HOUR_TOP]:
        if k.startswith("hour:"):
            findings.append({"klasse": "hour", "merkmal": k, "grund": f"weight {v:+.2f} among the {HOUR_TOP} strongest — time of day is not a cause"})
    per = {c: sum(1 for f in findings if f["klasse"] == c) for c in CLASSES}
    return {"zustand": "befunde" if findings else "ok", "befunde": findings, "je_klasse": {c: n for c, n in per.items() if n}}


def _group_lift(c: int) -> tuple[float | None, int, int]:
    """Pooled measured usefulness of the hints in meaning group c: (Σ ok − Σ expected) / Σ shown, Σ shown, number of rated hints."""
    from . import bandit, content
    ok = expected = n = members = 0
    for hid, grp in content._progress().get("gruppe", {}).items():
        if grp != c or not hid.startswith(bandit.HINT_KINDS):
            continue
        o = g.load(hid)
        z = (o.data.get("useful") or {}) if o else {}
        if z.get("n") and "expected" in z:
            ok, expected, n, members = ok + z.get("ok", 0), expected + z["expected"], n + int(z["n"]), members + 1
    return ((ok - expected) / n if n else None), n, members


def line(r: dict) -> str:
    if r["zustand"] == "kein_modell":
        return f"Weight audit: {r['grund']}"
    if r["zustand"] == "ok":
        return f"Weight audit: ok — none of {', '.join(CLASSES)}"
    return "Weight audit: " + ", ".join(f"{c} {n}" for c, n in r["je_klasse"].items()) + " — " + "; ".join(
        f"{f['klasse']} {f['merkmal']}: {f['grund']}" for f in r["befunde"][:5])
