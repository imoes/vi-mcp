"""0.7.0: vectors — embedding during sleep, proximity edges, duplicates, semantic search (no network: fake embedding)."""
import math

import pytest

from vi_mcp import sleep_cycle, vector, tools
from vi_mcp import memory as g

WORDS = ["timeout", "disk", "voll", "proxy", "netz"]
SYNONYMS = {"haengt": "timeout", "verbindung": "timeout"}


def fake_embed(texts):
    """Deterministic bag-of-words embedding; 'haengt' and 'verbindung' count as 'timeout' (synonyms)."""
    outputs = []
    for t in texts:
        t = t.lower()
        v = [0.0] * len(WORDS)
        for i, w in enumerate(WORDS):
            if w in t or any(syn in t for syn, target in SYNONYMS.items() if target == w):
                v[i] = 1.0
        outputs.append(v)
    return outputs


@pytest.fixture()
def fake(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", fake_embed)
    monkeypatch.setattr(vector, "config", {"modell": "fake"})
    yield
    monkeypatch.setattr(vector, "embed_fn", None)


def test_without_service_skipped_and_named(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", None)
    monkeypatch.setattr(vector, "config", None)
    b = sleep_cycle.run("Test")
    assert b.data["schritte"]["7_vektoren"]["zustand"] == "uebersprungen" and b.data["schritte"]["7b_naehe"]["zustand"] == "uebersprungen"
    with pytest.raises(tools.Rejected, match="no embedding service"):
        tools.call_tool("vi_erinnere", {"filter": "timeout", "semantisch": True}, "a", True)


def test_vectors_in_sleep_and_proximity_edges(fake):
    a = g.new_object("erkenntnis", "graylog Timeout auf cue1", ["host:cue1"], {"quelle": "x"}, reason="T", instance="a")
    b = g.new_object("erkenntnis", "Verbindung zu cue1 haengt", ["host:cue1"], {"quelle": "y"}, reason="T", instance="b")
    c = g.new_object("erkenntnis", "Disk voll auf web1", ["host:web1"], {"quelle": "z"}, reason="T")
    report = sleep_cycle.run("Test")
    s7 = report.data["schritte"]["7_vektoren"]
    assert s7["zustand"] == "fertig" and s7["neu"] == 3 and vector.load(a.id) is not None
    assert math.isclose(vector.cosine(vector.load(a.id), vector.load(b.id)), 1.0, abs_tol=1e-6)  # synonyms → identical vector
    s7b = report.data["schritte"]["7b_naehe"]
    assert s7b["kanten_neu"] == 1 and s7b["dubletten_moeglich"] == 1
    assert any("semantisch ähnlich" in gr for _, gr in g.load(a.id).edges())
    assert "dublette:moeglich" in g.load(a.id).hashtags and "dublette:moeglich" in g.load(b.id).hashtags
    assert "dublette:moeglich" not in g.load(c.id).hashtags
    assert sleep_cycle.run("Test 2").data["schritte"]["7_vektoren"]["neu"] == 0  # idempotent


def test_semantic_search(fake):
    a = g.new_object("erkenntnis", "graylog Timeout auf cue1", ["host:cue1"], {"quelle": "x"}, reason="T")
    g.new_object("erkenntnis", "Disk voll auf web1", ["host:web1"], {"quelle": "z"}, reason="T")
    sleep_cycle.run("Test")
    r = tools.call_tool("vi_erinnere", {"filter": "Verbindung haengt", "semantisch": True}, "a", True)
    assert r.splitlines()[1].strip().startswith(f"[{a.id}]") and "semantic hybrid (embedding" in r
    assert "nothing in memory" in tools.call_tool("vi_erinnere", {"filter": "Verbindung haengt"}, "a", True)  # FTS does not find it
    with pytest.raises(tools.Rejected, match="free text"):
        tools.call_tool("vi_erinnere", {"filter": "host:cue1", "semantisch": True}, "a", True)


def test_catch_up_names_the_real_remainder(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector, "BATCH", 2)
    for i in range(5):
        g.new_object("erkenntnis", f"Wissen Nummer {i} zum Einbetten", ["thema:a"], {"quelle": "x"}, reason="T")
    r = vector.catch_up(max_s=0)  # time already up: nothing embedded, everything pending
    assert r == {"zustand": "fertig", "neu": 0, "offen": 5, "pause_s": 0.0}
    r = vector.catch_up()
    assert r["neu"] == 5 and r["offen"] == 0


def test_semantic_search_checks_all_vectors_not_only_newest(fake):
    """0.19.2: candidates were the 200 most recently used objects — older docs were never compared (measured against the AIKB)."""
    old = g.new_object("erkenntnis", "Proxy-Doku: Verbindung über den Proxy", ["doku:x"], {"quelle": "alt"}, reason="T")
    g.db().execute("UPDATE objekt SET zuletzt = '2020-01-01T00:00:00+00:00', zeit = '2020-01-01T00:00:00+00:00' WHERE id = ?", (old.id,))
    for i in range(260):
        g.new_object("erkenntnis", f"Disk voll auf web{i}", [f"host:web{i}"], {"quelle": "neu"}, reason="T")
    vector.catch_up(max_s=600)
    r = tools.call_tool("vi_erinnere", {"filter": "proxy netz", "semantisch": True, "limit": 3}, "a", True)
    assert r.splitlines()[1].strip().startswith(f"[{old.id}]"), r
    assert "261 of 261 candidates with a vector" in r


def test_semantic_search_names_objects_without_vector(fake):
    g.new_object("erkenntnis", "proxy timeout", ["host:a"], {"quelle": "x"}, reason="T")
    vector.catch_up(max_s=600)
    g.new_object("erkenntnis", "proxy disk", ["host:b"], {"quelle": "y"}, reason="T")  # no vector yet
    r = tools.call_tool("vi_erinnere", {"filter": "proxy", "semantisch": True}, "a", True)
    assert "1 of 2 candidates with a vector" in r


def test_hybrid_search_finds_fresh_learning_without_vector(fake):
    """0.19.5: new items have no vector until the next sleep. Meaning search alone did not find them (learning test 09.11.: 1 of 8 before and after)."""
    for i in range(30):
        g.new_object("erkenntnis", f"Disk voll auf web{i}", [f"host:web{i}"], {"quelle": "alt"}, reason="T")
    vector.catch_up(max_s=600)
    new = g.new_object("erkenntnis", "ipa-client-install scheitert mit TypeError IPACertificate, Ursache pip-cryptography", ["thema:ipa-client-install"],
                         {"quelle": "neu"}, reason="T")
    r = tools.call_tool("vi_erinnere", {"filter": "ipa-client-install TypeError IPACertificate", "semantisch": True, "limit": 3}, "a", True)
    assert new.id in r and "via full text only" in r, r


def test_fulltext_falls_back_to_or_and_says_so(gd):
    """0.19.2: FTS5 joins words with AND — a filler word of the question ("anzuhalten") gave 0 hits."""
    a = g.new_object("erkenntnis", "vzdump im Modus snapshot sichert laufende VMs", ["skill:proxmox"], {"quelle": "x"}, reason="T")
    b = g.new_object("erkenntnis", "vzdump sichert VMs", ["skill:proxmox"], {"quelle": "y"}, reason="T")
    r = tools.call_tool("vi_erinnere", {"filter": "vzdump snapshot laufende anzuhalten"}, "a", True)
    assert "OR search" in r and r.splitlines()[1].strip().startswith(f"[{a.id}]") and b.id in r
    full = tools.call_tool("vi_erinnere", {"filter": "vzdump snapshot"}, "a", True)  # all words present, enough hits at limit 1
    assert "OR search" not in tools.call_tool("vi_erinnere", {"filter": "vzdump sichert", "limit": 1}, "a", True) and a.id in full
    # internal callers keep AND
    assert g.recall("vzdump snapshot anzuhalten") == [] and g.word_search.get() == "und"


def test_fulltext_with_hashtag_filter_searches_only_filtered(gd):
    """FTS used to run globally with LIMIT 500 and was filtered only afterwards: matching objects behind 500 foreign hits were missing."""
    for i in range(520):
        g.new_object("erkenntnis", f"timeout auf web{i}", [f"host:web{i}"], {"quelle": "x"}, reason="T")
    target = g.new_object("erkenntnis", "timeout auf cue1", ["host:cue1"], {"quelle": "x"}, reason="T")
    assert [o.id for _, o, _g in g.recall("host:cue1 timeout")] == [target.id]
