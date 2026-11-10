"""0.16.0: meaning proximity and content groups as router features; sleep never runs twice and blocks no proxy."""
import random
import threading
import time

import numpy as np
import pytest

from vi_mcp import content, intuition, learning, sleep_cycle, vector, tools
from vi_mcp import memory as g

pytest.importorskip("sklearn")


def _vec(direction: int, noise: float = 0.05, dim: int = 16, rng=random.Random(3)):
    v = np.array([rng.gauss(0, noise) for _ in range(dim)])
    v[direction] += 1.0
    return v.tolist()


@pytest.fixture()
def knowledge(gd, monkeypatch):
    monkeypatch.setattr(vector, "config", {"modell": "fake"})
    ids = {}
    for topic, direction in (("tls", 0), ("disk", 1), ("netz", 2)):
        for i in range(8):
            o = g.new_object("erkenntnis", f"Wissen {topic} Nummer {i} ausführlich", [f"thema:{topic}", "tool:Bash"], {"quelle": "Test 2.11."}, reason="T", instance="a")
            vector.save(o.id, _vec(direction), "m")
            ids.setdefault(topic, []).append(o.id)
    content.forget_cache()
    return ids


def test_compute_and_proximity(knowledge):
    r = content.compute()
    assert r["zustand"] == "fertig" and r["zentren"] == 4 and r["gruppen"] >= 2
    tls, disk = knowledge["tls"][0], knowledge["disk"][0]
    assert content.proximity(tls, ["thema:tls"]) > 0.9  # matches the content of the situation, even without itself
    assert content.proximity(disk, ["thema:tls"]) < 0.2
    assert content.proximity(tls, ["thema:unbekannt"]) is None and content.proximity("erkenntnis:gibtsnicht", ["thema:tls"]) is None
    assert len({content.group(i) for i in knowledge["tls"]}) == 1 and content.group(tls) != content.group(disk)
    assert "thema:tls" in content.group_name(content.group(tls)) and "meaning groups" in content.line()


def test_self_excluded_from_count(gd, monkeypatch):
    monkeypatch.setattr(vector, "config", {"modell": "fake"})
    a = g.new_object("erkenntnis", "Einziger Hinweis zum Thema A hier", ["thema:a"], {"quelle": "x"}, reason="T")
    vector.save(a.id, _vec(0), "m")
    for i in range(3):
        o = g.new_object("erkenntnis", f"Anderer Inhalt {i} zum Thema A", ["thema:a"], {"quelle": "x"}, reason="T")
        vector.save(o.id, _vec(5), "m")
    content.forget_cache()
    content.compute()
    assert content.proximity(a.id, ["thema:a"]) < 0.3  # without excluding it, it would be similar through itself


def test_features_and_switches(knowledge, monkeypatch):
    content.compute()
    m = learning.hint_features(knowledge["tls"][0], ["thema:tls", "stunde:3"])
    assert "naehe" in m and any(k.startswith("inhalt:") for k in m)
    monkeypatch.setattr(learning, "CONTENT", False)
    assert set(learning.hint_features(knowledge["tls"][0], ["thema:tls"])) == {f"hinweis:{knowledge['tls'][0]}", "hinweisart:erkenntnis"}


def test_model_learns_the_content(knowledge, monkeypatch):
    """Hints on TLS help, on disk they do not, and no single hint occurs often enough for its own weight: only the content can explain it."""
    content.compute()
    rng = random.Random(9)
    monkeypatch.setattr(learning, "MIN_EVENTS", 20)
    for n in range(400):
        topic = rng.choice(["tls", "disk"])
        hid = rng.choice(knowledge[topic])
        ok = rng.random() < (0.9 if topic == "tls" else 0.2)
        g.new_object("erfahrung", "Bash", ["tool:Bash", f"thema:{topic}", "ok:ja" if ok else "ok:nein"],
                       {"vorher": {"reize": ["tool:Bash", f"thema:{topic}"], "gezeigt": [hid]}, "args": {"n": n}}, reason="T", instance="a")
    b = learning.train("Test")
    w = learning.model().data["gewichte"]
    assert b["zustand"] == "aktiv", b
    gt, gd_ = content.group(knowledge["tls"][0]), content.group(knowledge["disk"][0])
    assert w.get(f"inhalt:{gt}", 0) > w.get(f"inhalt:{gd_}", 0)
    new = g.new_object("erkenntnis", "Ganz neuer Hinweis zu Zertifikaten", ["thema:tls", "tool:Bash"], {"quelle": "x"}, reason="T")
    vector.save(new.id, _vec(0), "m")
    old_disk = knowledge["disk"][0]
    content.compute()
    learning.train("Test 2")
    rank_pos = [h for h, _ in learning.ranking(learning.model(), ["tool:Bash"], [old_disk, new.id])]
    assert rank_pos[0] == new.id  # a new hint inherits the weight of its content
    assert "Bedeutungs" in learning.explanation() or "inhalt:" in learning.explanation()


def test_sleep_never_twice_and_no_proxy_abort(gd, monkeypatch):
    halt = threading.Event()
    original = sleep_cycle._run

    def slow(reason):
        halt.wait(5)
        return original(reason)
    monkeypatch.setattr(sleep_cycle, "_run", slow)
    monkeypatch.setattr(sleep_cycle, "WAIT_S", 0.3)
    t0 = time.monotonic()
    try:
        _check_sleep(halt, t0)
    finally:
        halt.set()
        for _ in range(80):
            if not sleep_cycle._running.locked():
                break
            time.sleep(0.1)
    assert sleep_cycle.last() is not None and "7c_inhalt" in sleep_cycle.last().data["schritte"]


def _check_sleep(halt, t0):
    a = tools.call_tool("vi_schlaf", {"jetzt": True}, "a", True)
    assert "still running" in a and time.monotonic() - t0 < 2
    assert "already running" in tools.call_tool("vi_schlaf", {"jetzt": True}, "a", True)
    with pytest.raises(sleep_cycle.AlreadyRunning):
        sleep_cycle.run("Loop")
