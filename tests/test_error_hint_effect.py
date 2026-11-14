"""0.63.0: what vi_after shows after a failed action is recorded and held back at random, so its effect on recovery can be measured."""
import random

from vi_mcp import intuition, metrics, session
from vi_mcp import memory as g


def _known_error():
    g.new_object("erkenntnis", "pkill -f kills its own shell (exit 144): use pgrep and kill the PID",
                 ["thema:pkill", "fehler:Exit_code_144"], {"quelle": "test", "inhalt": "pkill -f pattern matches the shell itself, exit 144"},
                 reason="T")


def _fail_then_retry(s, ok_after):
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "pkill -f worker.py"}, s.instance)
        out = intuition.after("Bash", {"command": "pkill -f worker.py"}, False, 1, "Exit code 144", None, v["vorher_id"], s.instance)
        v2 = intuition.before("Bash", {"command": "kill 4242"}, s.instance)
        intuition.after("Bash", {"command": "kill 4242"}, ok_after, 1, None if ok_after else "Exit code 1", "ok" if ok_after else None,
                        v2["vorher_id"], s.instance)
    return out


def test_error_hints_are_recorded_and_can_be_held_back(gd, monkeypatch):
    _known_error()
    monkeypatch.setattr(intuition, "HOLD_BACK", 0.0)
    shown = _fail_then_retry(session.begin("a", "t"), True)
    assert any("After this error" in h for h in shown["hinweise"])
    d = g.load(shown["erfahrung"]).data
    assert d["fehler_hinweise"] and d["fehler_zurueckgehalten"] is False
    monkeypatch.setattr(intuition, "HOLD_BACK", 1.0)
    held = _fail_then_retry(session.begin("a", "t2"), True)
    assert not any("After this error" in h for h in held["hinweise"])
    assert g.load(held["erfahrung"]).data["fehler_zurueckgehalten"] is True


def test_recovery_is_compared_between_shown_and_held_back(gd, monkeypatch):
    _known_error()
    rnd = random.Random(5)
    monkeypatch.setattr(intuition, "HOLD_BACK", 0.0)
    for i in range(40):
        _fail_then_retry(session.begin("a", f"s{i}"), rnd.random() < 0.9)
    monkeypatch.setattr(intuition, "HOLD_BACK", 1.0)
    for i in range(10):
        _fail_then_retry(session.begin("a", f"h{i}"), rnd.random() < 0.4)
    few = metrics.error_hint_effect()
    assert few["zustand"] == "zu_wenig" and few["zurueckgehalten"] == 10 and "at least 30" in few["urteil"]
    for i in range(30):
        _fail_then_retry(session.begin("a", f"k{i}"), rnd.random() < 0.4)
    r = metrics.error_hint_effect()
    assert r["zustand"] == "gemessen" and r["zurueckgehalten"] == 40 and r["differenz"] > 0.2 and "raise recovery" in r["urteil"]
