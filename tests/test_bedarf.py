"""0.20.0: training on demand instead of only at night; proximity edges incremental."""
import time

import pytest

from vi_mcp import on_demand, intuition, vector, tools
from vi_mcp import memory as g

from test_vektor import fake_embed


@pytest.fixture()
def fake(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", fake_embed)
    monkeypatch.setattr(vector, "config", {"modell": "fake"})
    on_demand.progress.update({"laeufe": 0, "angestossen": 0, "vektoren_seit_kmeans": 0})
    yield
    monkeypatch.setattr(vector, "embed_fn", None)


def test_experience_and_knowledge_trigger_training(fake):
    prev_hash = on_demand.progress["angestossen"]
    v = intuition.before("Bash", {"command": "ls"}, "a")
    intuition.after("Bash", {"command": "ls"}, True, 5, None, "ok", v["vorher_id"], "a")
    tools.call_tool("vi_lerne", {"text": "Proxy-Timeout auf web1 nach 30 s", "hashtags": ["host:web1"], "quelle": "Beobachtung 9.11."}, "a", True)
    assert on_demand.progress["angestossen"] == prev_hash + 2


def test_run_embeds_and_trains_with_duration(fake):
    a = g.new_object("erkenntnis", "Proxy timeout auf web1", ["host:web1"], {"quelle": "x"}, reason="T")
    r = on_demand.run("Test")
    assert set(r["schritte"]) >= {"vektoren", "naehe", "hinweise", "lernen"}
    assert all("ms" in s for s in r["schritte"].values())
    assert vector.load(a.id) is not None and r["vektoren_offen"] == 0
    assert "Training on demand: 1 runs" in on_demand.line()
    assert "Training on demand" in tools.call_tool("vi_status", {}, "a", True)


def test_proximity_edges_compare_only_new(fake):
    a = g.new_object("erkenntnis", "Proxy timeout auf web1", ["host:web1"], {"quelle": "x"}, reason="T", instance="a")
    g.new_object("erkenntnis", "Disk voll auf web2", ["host:web2"], {"quelle": "y"}, reason="T")
    vector.catch_up(max_s=60)
    assert vector.proximity_edges()["neu_verglichen"] == 2
    assert vector.proximity_edges()["neu_verglichen"] == 0  # nothing new: no comparison
    b = g.new_object("erkenntnis", "Verbindung haengt am Proxy", ["host:web3"], {"quelle": "z"}, reason="T", instance="b")
    vector.catch_up(max_s=60)
    r = vector.proximity_edges()
    assert r["neu_verglichen"] == 1 and r["kanten_neu"] == 1
    assert any(x == b.id for x, _gr in g.load(a.id).edges())


def test_background_thread_runs_after_nudge(fake, monkeypatch):
    monkeypatch.setattr(on_demand, "INTERVAL_S", 0)
    th = on_demand.launch()
    try:
        on_demand.nudge("Test")
        end = time.time() + 10
        while on_demand.progress["laeufe"] == 0 and time.time() < end:
            time.sleep(0.05)
        assert on_demand.progress["laeufe"] >= 1 and "Test" in on_demand.progress["grund"]
    finally:
        on_demand.stop_background()
        th.join(timeout=10)


def test_embedding_pauses_between_batches(fake, monkeypatch):
    """0.20.5: for shared embedding services: after each batch a pause as long as the batch took (pause_anteil 1.0); default unthrottled."""
    assert vector.PAUSE_SHARE == 0
    def slow(texts):
        time.sleep(0.05)
        return fake_embed(texts)
    monkeypatch.setattr(vector, "embed_fn", slow)
    monkeypatch.setattr(vector, "BATCH", 1)
    monkeypatch.setattr(vector, "config", {"modell": "fake", "pause_anteil": 1.0})
    for i in range(3):
        g.new_object("erkenntnis", f"Proxy timeout Nummer {i} auf web{i}", [f"host:web{i}"], {"quelle": "x"}, reason="T")
    t0 = time.monotonic()
    r = vector.catch_up(max_s=60)
    assert r["neu"] == 3 and r["pause_s"] >= 0.09  # two pauses (none after the last batch)
    assert time.monotonic() - t0 >= 0.24
    monkeypatch.setattr(vector, "config", {"modell": "fake", "pause_anteil": 0})
    g.new_object("erkenntnis", "Disk voll auf web9", ["host:web9"], {"quelle": "y"}, reason="T")
    assert vector.catch_up(max_s=60)["pause_s"] == 0


def test_sleep_does_not_stop_the_loop(gd, monkeypatch):
    """0.20.5: the sleep ran synchronously in the loop (measured 429–530 s) and stalled the loop and on-demand training."""
    from vi_mcp import sleep_cycle, main_loop
    import threading
    started, free = threading.Event(), threading.Event()

    def run(reason):
        with sleep_cycle._running:
            started.set()
            free.wait(5)
        return g.new_object("schlaf", "Testschlaf", ["zustand:fertig"], {}, reason="T")
    monkeypatch.setattr(sleep_cycle, "due", lambda: "Test")
    monkeypatch.setattr(sleep_cycle, "run", run)
    t0 = time.monotonic()
    main_loop.step()
    assert started.wait(2) and time.monotonic() - t0 < 1.5
    calls = []
    monkeypatch.setattr(sleep_cycle, "due", lambda: calls.append(1) or "Test")
    main_loop.step()  # still running: no second sleep, faellig is not even asked
    assert calls == [] and sleep_cycle.running()
    free.set()


def test_semantic_edges_have_an_upper_bound(fake, monkeypatch):
    """0.20.6: nearly identical template pages all linked to each other (2.24 M edges, up to 1,316 per object)."""
    monkeypatch.setattr(vector, "embed_fn", lambda texts: [[1.0, 0.0] for _ in texts])  # all identical: cos 1.0
    monkeypatch.setattr(vector, "PROXIMITY_MAX", 3)
    objs = [g.new_object("erkenntnis", f"Vorlage Server {i}: Hier können Notizen stehen", [f"seite:{i}"], {"quelle": "x"}, reason="T")
            for i in range(12)]
    vector.catch_up(max_s=60)
    vector.proximity_edges()
    sem = lambda o: [b for b, gr in g.load(o.id).edges() if gr.startswith("semantisch")]
    assert max(len(sem(o)) for o in objs) <= 3  # mutual nearest neighbours: strictly bounded
    evidenced = objs[0]
    evidenced.link(objs[11].id, "Beleg (Test)")
    # legacy data without a limit (as before 0.20.6): link all pairs by hand, then cap
    for a in objs:
        for b in objs:
            if a.id < b.id:
                a.link(b.id, "semantisch ähnlich (cos 1.00)")
    before = sum(len(sem(o)) for o in objs)
    remove = vector.cap(3)
    assert remove > 0 and sum(len(sem(o)) for o in objs) == before - remove
    assert max(len(sem(o)) for o in objs) <= 3
    assert any(b == objs[11].id and gr.startswith("Beleg") for b, gr in g.load(evidenced.id).edges())  # Beleg edge stays
    assert vector.cap(3) == 0  # already bounded
