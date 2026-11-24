"""24.11.2026: two background costs that jammed vi-mcp under session churn — the router retrained on demand after every new
experience, and every concurrent search rebuilt an expired lexicon itself."""
import threading

from vi_mcp import learning, lexicon, on_demand


def test_on_demand_training_is_throttled_and_named(gd, monkeypatch):
    trained = []
    monkeypatch.setattr(learning, "train", lambda reason: (trained.append(reason), {"zustand": "fertig"})[1])
    monkeypatch.setattr(on_demand, "_last_learn", [float("-inf")])
    skipped = on_demand.progress["lernen_ausgelassen"]
    on_demand.run("nudged")  # the first run trains
    r = on_demand.run("nudged")  # within LEARN_MIN_S: not again, and it says so
    assert len(trained) == 1
    assert r["schritte"]["lernen"]["zustand"] == "uebersprungen" and "at most every" in r["schritte"]["lernen"]["grund"]
    assert on_demand.progress["lernen_ausgelassen"] == skipped + 1
    on_demand.run("by hand")  # a run by hand always trains
    assert len(trained) == 2
    monkeypatch.setattr(on_demand, "LEARN_MIN_S", 0)
    on_demand.run("nudged")
    assert len(trained) == 3


def test_an_expired_lexicon_is_rebuilt_once_while_the_others_use_the_previous_one(gd, monkeypatch):
    first = lexicon.lexicon()
    builds, gate = [], threading.Event()
    real = lexicon._load

    def slow():
        builds.append(1)
        gate.wait(2)
        return real()
    monkeypatch.setattr(lexicon, "_load", slow)
    lexicon._cache["at"] = 0.0  # expired
    rebuild = threading.Thread(target=lexicon.lexicon)
    rebuild.start()
    while not builds:
        pass
    got = []
    others = [threading.Thread(target=lambda: got.append(lexicon.lexicon())) for _ in range(5)]
    for t in others:
        t.start()
    for t in others:
        t.join(1)
    assert all(not t.is_alive() for t in others)  # none waited for the rebuild
    assert len(got) == 5 and all(x is first for x in got)  # they used the previous lexicon of the same database
    gate.set()
    rebuild.join(5)
    assert len(builds) == 1
