"""Weight audit (0.29.0) — fixed rules that read the router weights after training and name what looks wrong.

The router is taught through labels (scorer verdicts, direct feedback), never by writing weights. This audit only reads: it never
changes a weight, a mode or a hint. Every finding names its class, the feature or hint and the numbers that triggered it, so a session
can follow it up with vi_why / vi_object and, if the hint is wrong, vi_refute. Fixed rules instead of a language model: the classes are
checkable arithmetic, and a model reading the weights could be steered by the hint texts it would also see (AGENTS.md: language-model
verdicts only tighten).

Classes (exhaustive; "ok" when none applies):
  dominant      one feature carries the model: |w| ≥ DOMINANT_FACTOR × the DOMINANT_RANK-th largest |w| and ≥ DOMINANT_MIN
  contradicts   a hint weight and the hint's measured usefulness (bandit, ≥ CONTRA_MIN_N shown) point in opposite directions;
                since 0.30.0 also a meaning-group weight (inhalt:<c>) against the pooled measured usefulness of the group's hints
  network       a hint from the network (herkunft:p2p) with a strong positive weight and no confirmation by another instance
  hour          an hour feature (stunde:HH) is among the strongest weights — time of day as a cause is post hoc
"""
from __future__ import annotations

from . import memory as g

DOMINANT_FACTOR = 3.0
DOMINANT_RANK = 5
DOMINANT_MIN = 1.0
STRONG = 0.5
CONTRA_MIN_N = 20
CONTRA_MIN_LIFT = 0.05
HOUR_TOP = 3
CLASSES = ("dominant", "contradicts", "network", "hour")


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
        if not k.startswith("hinweis:") or abs(v) < STRONG:
            continue
        hint = g.load(k[8:])
        if hint is None:
            continue
        lift = bandit.lift(hint)
        if lift is not None and bandit.shown(hint) >= CONTRA_MIN_N and abs(lift) >= CONTRA_MIN_LIFT and (lift > 0) != (v > 0):
            findings.append({"klasse": "contradicts", "merkmal": k,
                             "grund": f"weight {v:+.2f}, but measured {lift * 100:+.0f} points over {bandit.shown(hint)} showings"})
        if v > 0 and "herkunft:p2p" in hint.hashtags and not hint.foreign_confirmations():
            publisher = next((t[11:] for t in hint.hashtags if t.startswith("herausgeber:")), "?")
            findings.append({"klasse": "network", "merkmal": k,
                             "grund": f"weight {v:+.2f} for a hint from the network ({publisher}) that no other instance confirmed"})
    for k, v in ranked:  # 0.30.0: a group weight can push down hints that are measured as good (seen 10.11.2026: inhalt:21 −0.72)
        if not k.startswith("inhalt:") or not k[7:].isdigit() or abs(v) < STRONG:
            continue
        lift, n, members = _group_lift(int(k[7:]))
        if lift is not None and n >= CONTRA_MIN_N and abs(lift) >= CONTRA_MIN_LIFT and (lift > 0) != (v > 0):
            findings.append({"klasse": "contradicts", "merkmal": k,
                             "grund": f"group weight {v:+.2f}, but its {members} rated hints measured {lift * 100:+.0f} points over {n} showings"})
    for k, v in ranked[:HOUR_TOP]:
        if k.startswith("stunde:"):
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
        z = (o.data.get("nuetzlich") or {}) if o else {}
        if z.get("n") and "erwartet" in z:
            ok, expected, n, members = ok + z.get("ok", 0), expected + z["erwartet"], n + int(z["n"]), members + 1
    return ((ok - expected) / n if n else None), n, members


def line(r: dict) -> str:
    if r["zustand"] == "kein_modell":
        return f"Weight audit: {r['grund']}"
    if r["zustand"] == "ok":
        return f"Weight audit: ok — none of {', '.join(CLASSES)}"
    return "Weight audit: " + ", ".join(f"{c} {n}" for c, n in r["je_klasse"].items()) + " — " + "; ".join(
        f"{f['klasse']} {f['merkmal']}: {f['grund']}" for f in r["befunde"][:5])
