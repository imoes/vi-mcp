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
                hint_n), averaged over the showings the measurement counts. Comparing one summand with the whole is an invalid
                derivation.
                0.70.2: the measurement side is matched, too. The bandit's lift compares a hint's showings with the instance's
                rate for the tool; a hint keyed to a failing host (CentralStation "Bekannter Fehler … Filter: host:X") is shown exactly
                while X fails, so its lift measures the host, not the hint. Seen 18.11.2026: five "contradicts" findings with −7 … −34
                points against the tool's rate measured −4 … +16 points against actions of the same instance and tool on the same
                host within ±24 h without the hint (production copy of 16.11.2026). A contradiction is named only when that matched
                lift (matched_lift) points against the model's view, with at least CONTRA_MIN_N matched showings and
                |lift| ≥ CONTRA_SE standard errors; every candidate held back is counted with its reason (held_back).
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
#: 0.70.2 matched measurement: controls are actions of the same instance and tool, sharing a host (or, without a host, any), within
#: ±MATCH_HOURS of the showing, the hint not shown; a showing counts with at least MATCH_MIN_CONTROLS controls
MATCH_HOURS = 24
MATCH_MIN_CONTROLS = 3
CONTRA_SE = 2.0
CLASSES = ("dominant", "contradicts", "network", "hour")
#: why a hint whose bandit lift opposes the model's view is not named (exhaustive)
HELD_BACK = ("situation", "too_few_matched", "not_significant")


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


def matched_lift(hid: str) -> tuple[float | None, float, int]:
    """0.70.2: (lift, standard error, matched showings) of a hint against the same situation without it — for each of its newest
    SHOWINGS_MAX labelled showings, the success rate of the controls (same instance, same tool trigger, a shared host trigger if the
    showing names one, ±MATCH_HOURS, the hint not shown, labelled, not answered from memory) is that showing's expectation.
    lift = mean(ok − expected); SE from the binomial variance of each expectation plus the controls' own sampling error."""
    from datetime import datetime, timedelta
    with g.lock:
        rows = g.db().execute("SELECT o.id, o.ts, o.instance, o.data FROM object o WHERE o.kind = 'experience' AND o.mode = 'active' "
                              "AND o.data LIKE ? ORDER BY o.ts DESC LIMIT ?", (f'%"{hid}"%', SHOWINGS_MAX)).fetchall()
    diffs, var = [], 0.0
    for oid, ts, inst, data in rows:
        v = (json.loads(data) or {}).get("before") or {}
        if hid not in (v.get("shown") or []) or v.get("from_memory"):
            continue
        trig = v.get("triggers") or []
        tool = next((t for t in trig if t.startswith("tool:")), None)
        hosts = [t for t in trig if t.startswith("host:")]
        y = _label(oid)
        if tool is None or y is None:
            continue
        t0 = datetime.fromisoformat(ts)
        lo, hi = (t0 - timedelta(hours=MATCH_HOURS)).isoformat(), (t0 + timedelta(hours=MATCH_HOURS)).isoformat()
        need = hosts or [tool]
        with g.lock:
            cands = g.db().execute(
                "SELECT DISTINCT o.id, o.data FROM object o JOIN tag t ON t.object_id = o.id WHERE o.kind = 'experience' AND o.mode = 'active' "
                f"AND o.instance = ? AND o.ts >= ? AND o.ts <= ? AND o.id != ? AND t.tag IN ({','.join('?' * len(need))})",
                (inst, lo, hi, oid, *need)).fetchall()
        ctl = []
        for cid, cdata in cands:
            cv = (json.loads(cdata) or {}).get("before") or {}
            if hid in (cv.get("shown") or []) or cv.get("from_memory") or tool not in (cv.get("triggers") or []):
                continue
            if (cy := _label(cid)) is not None:
                ctl.append(cy)
        if len(ctl) < MATCH_MIN_CONTROLS:
            continue
        e = sum(ctl) / len(ctl)
        diffs.append(y - e)
        var += e * (1 - e) * (1 + 1 / len(ctl))
    if not diffs:
        return None, 0.0, 0
    return sum(diffs) / len(diffs), var ** 0.5 / len(diffs), len(diffs)


def _label(oid: str) -> int | None:
    with g.lock:
        tags = {r[0] for r in g.db().execute("SELECT tag FROM tag WHERE object_id = ? AND tag IN ('ok:yes', 'ok:no')", (oid,))}
    return 1 if "ok:yes" in tags else 0 if "ok:no" in tags else None


def audit(m: g.MemoryObject | None = None) -> dict:
    """{"zustand": "ok" | "befunde" | "kein_modell", "befunde": [{"klasse", "merkmal", "grund"}], "je_klasse": {klasse: n}}."""
    from . import bandit, learning
    m = m or learning.model()
    if m is None or not m.data.get("gewichte"):
        return {"zustand": "kein_modell", "grund": "no trained router weights yet", "befunde": [], "je_klasse": {}}
    w = m.data["gewichte"]
    ranked = sorted(w.items(), key=lambda kv: -abs(kv[1]))
    findings, held_back = [], {}
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
                ml, se, n_m = matched_lift(hint.id)  # 0.70.2: against the same situation, not the tool's rate
                why_not = ("too_few_matched" if ml is None or n_m < CONTRA_MIN_N else
                           "situation" if (ml > 0) == (view > 0) or abs(ml) < CONTRA_MIN_LIFT else
                           "not_significant" if abs(ml) < CONTRA_SE * se else None)
                if why_not:
                    held_back[why_not] = held_back.get(why_not, 0) + 1
                else:
                    findings.append({"klasse": "contradicts", "merkmal": k,
                                     "grund": f"model view {view:+.2f} (logit with vs without, over its {n_view} newest showings; own weight {v:+.2f}), but measured "
                                              f"{lift * 100:+.0f} points over {bandit.shown(hint)} showings; against the same situation "
                                              f"without it {ml * 100:+.0f} ± {se * 100:.0f} points over {n_m} matched showings"})
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
    return {"zustand": "befunde" if findings else "ok", "befunde": findings, "je_klasse": {c: n for c, n in per.items() if n},
            "held_back": {c: held_back[c] for c in HELD_BACK if c in held_back}}


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
    hb = r.get("held_back") or {}
    held = (" · not named as contradicts (the bandit's lift opposed the model, the matched measurement did not confirm it): "
            + ", ".join(f"{c} {n}" for c, n in hb.items())) if hb else ""
    if r["zustand"] == "ok":
        return f"Weight audit: ok — none of {', '.join(CLASSES)}" + held
    return "Weight audit: " + ", ".join(f"{c} {n}" for c, n in r["je_klasse"].items()) + " — " + "; ".join(
        f"{f['klasse']} {f['merkmal']}: {f['grund']}" for f in r["befunde"][:5]) + held
