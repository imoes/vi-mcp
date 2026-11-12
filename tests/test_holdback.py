"""0.61.0: the total effect of hints — on a random share of actions with hints the hints are held back, and metrics.holdback_effect
compares those actions with the others (Mantel-Haenszel within instance and tool). The trigger: the matched lift (−1 point, 12.11.2026)
cannot separate the effect of hints from the difficulty of the actions they appear on."""
import json
import random

from vi_mcp import config, intuition, metrics
from vi_mcp import memory as g


def _hint():
    return g.new_object("erkenntnis", "rsync needs --partial to resume interrupted transfers", ["tool:rsync"], {"quelle": "t"}, instance="x")


def test_hints_are_held_back_on_the_coin_flip_and_recorded(gd, monkeypatch):
    h = _hint()
    monkeypatch.setattr(intuition, "HOLD_BACK", 0.05)
    monkeypatch.setattr(random, "random", lambda: 0.01)  # < HOLD_BACK: held back
    r = intuition.before("rsync", {"src": "a"}, "a", False)
    z = r["zugriff"]
    assert z["gezeigt"] == [] and z["zurueckgehalten"] == [h.id] and z["haltewahrscheinlichkeit"] == 0.05
    assert not any(h.id in line for line in r["hinweise"] if line.startswith(("Learned", "Rule")))  # nothing of it reaches the agent
    assert not any("vi_feedback" in line for line in r["hinweise"])  # no feedback request for hints it did not see
    monkeypatch.setattr(random, "random", lambda: 0.9)  # the regular case: shown, and the action is eligible for the comparison
    z = intuition.before("rsync", {"src": "b"}, "a", False)["zugriff"]
    assert z["gezeigt"] == [h.id] and z["zurueckgehalten"] == [] and z["haltewahrscheinlichkeit"] == 0.05


def test_off_and_without_hints_nothing_is_recorded(gd, monkeypatch):
    _hint()
    monkeypatch.setattr(intuition, "HOLD_BACK", 0.0)
    monkeypatch.setattr(random, "random", lambda: 0.0)
    z = intuition.before("rsync", {"src": "a"}, "a", False)["zugriff"]
    assert z["gezeigt"] and z["zurueckgehalten"] == []  # off: never held back
    assert "haltewahrscheinlichkeit" not in intuition.before("curl", {"url": "x"}, "a", False)["zugriff"]  # no hint: not eligible


def test_holdback_effect_recovers_a_known_effect(gd):
    rng = random.Random(7)
    for i in range(1200):
        held = i % 10 == 0  # 120 held back, 1080 shown
        ok = rng.random() < (0.70 if held else 0.90)  # a true effect of +20 points
        v = {"gezeigt": [] if held else ["erkenntnis:h"], "zurueckgehalten": ["erkenntnis:h"] if held else [], "haltewahrscheinlichkeit": 0.1}
        g.new_object("erfahrung", f"rsync {i}", ["tool:rsync", f"ok:{'ja' if ok else 'nein'}"], {"vorher": v}, instance="a")
    metrics._GRADES["db"] = None
    e = metrics.holdback_effect()
    assert e["zustand"] == "gemessen" and e["zurueckgehalten"] == 120 and e["gezeigt"] == 1080
    assert abs(e["differenz"] - 0.20) < 2.5 * e["standardfehler"] and "hints raise the success" in e["urteil"]


def test_too_few_held_back_says_so(gd):
    for i in range(20):
        v = {"gezeigt": [] if i < 5 else ["erkenntnis:h"], "zurueckgehalten": ["erkenntnis:h"] if i < 5 else [], "haltewahrscheinlichkeit": 0.05}
        g.new_object("erfahrung", f"rsync {i}", ["tool:rsync", "ok:ja"], {"vorher": v}, instance="a")
    metrics._GRADES["db"] = None
    e = metrics.holdback_effect()
    assert e["zustand"] == "zu_wenig" and "at least 30" in e["urteil"]


def test_config_bounds_the_share(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    for raw, want in ((0.05, 0.05), (0.9, 0.25), (-1, 0.0), ("x", 0.05)):
        p.write_text(json.dumps({"hold_back": raw}))
        assert config.load(p).hold_back == want
    p.write_text("{}")
    assert config.load(p).hold_back == 0.05
