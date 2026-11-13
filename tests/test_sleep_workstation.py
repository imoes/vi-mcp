"""0.62.0: a server on a workstation is not up 24 h — sleep is caught up in a quiet moment and does not run while someone works."""
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import memory as g
from vi_mcp import sleep_cycle as sc

NOON = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clock(gd, monkeypatch):
    state = {"idle": 0.0, "up": 3600.0, "cfg": {"workstation": False, "idle_min": 10.0}}
    monkeypatch.setattr(sc, "idle_s", lambda: state["idle"])
    monkeypatch.setattr(sc, "uptime_s", lambda: state["up"])
    monkeypatch.setattr(sc, "_cfg", lambda: state["cfg"])
    return state


def _slept(hours_ago):
    o = g.new_object("schlaf", "sleep", ["art:schlaf"], {"quelle": "t"})
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE id = ?", ((NOON - timedelta(hours=hours_ago)).isoformat(timespec="seconds"), o.id))
        g.db().commit()


def _experiences(total):
    for i in range(total // 3):
        g.new_object("erfahrung", f"Bash ok {i}", ["tool:Bash"], {"quelle": "t"}, importance=3)


def test_a_missed_night_is_caught_up_in_a_quiet_moment_not_while_someone_works(clock):
    _slept(30)  # the machine was off at 03:00
    clock["idle"] = 11 * 60
    assert sc.due(NOON) is None  # nothing new since: nothing to catch up
    clock["idle"] = 0.0
    _experiences(3)
    assert sc.due(NOON) is None  # busy: an AI is working right now
    clock["idle"] = 11 * 60
    clock["up"] = 60
    assert sc.due(NOON) is None  # just started: the grace period
    clock["up"] = 3600
    r = sc.due(NOON)
    assert r.startswith("catch-up: last sleep 30 h ago") and "quiet for 11 min" in r


def test_workstation_importance_waits_for_quiet_and_a_server_does_not(clock):
    _slept(3)
    _experiences(90)
    assert sc.due(NOON).startswith("importance of new experiences")  # a server sleeps under load as before
    clock["cfg"] = {"workstation": True, "idle_min": 10.0}
    assert sc.due(NOON) is None  # a workstation waits
    clock["idle"] = 15 * 60
    assert sc.due(NOON).endswith("workstation quiet")


def test_touch_resets_the_idle_clock():
    sc.touch()
    assert sc.idle_s() < 1
