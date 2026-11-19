"""0.70.4: an external index (vi_index scope "external") — a large public corpus found by every user search without naming it, but never
a hint, never embedded or labelled in sleep and without proximity edges; one scope value per index, so "named only" and "external"
cannot both hold."""
import pytest

from vi_mcp import indexes, intuition, tools, vector
from vi_mcp import memory as g


def _page(text, tags, idx="se-ext"):
    return g.new_object("insight", text, tags, {"source": "test 19.11.2026"}, instance="importer", index=idx)


def _ids(filter_text):
    return {o.id for _, o, _g in g.recall(filter_text, limit=50)}


def test_an_external_index_is_found_by_a_user_search_without_naming_it(gd):
    page = _page("rsync over ssh drops the connection after a minute", ["topic:rsync"])
    indexes.describe("se-ext", scope="external")
    assert page.id not in _ids("topic:rsync")  # an internal path (hints, prompt context) does not see it
    assert page.id in tools.call_tool("vi_recall", {"filter": "topic:rsync", "semantic": False}, "a", False)  # the user search does
    token = g.user_search.set(True)
    try:
        assert page.id in _ids("topic:rsync")
    finally:
        g.user_search.reset(token)
    assert page.id in _ids("index:se-ext topic:rsync")  # named, as before


def test_an_external_index_never_becomes_a_hint(gd):
    page = _page("web1 answers ssh only with BatchMode and the key file", ["host:web1.example", "tool:Bash"])
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "a", False)
    assert page.id in v["zugriff"]["shown"]  # control: a hint while the index is normal
    indexes.describe("se-ext", scope="external")
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "b", False)
    assert page.id not in v["zugriff"]["shown"]


def test_an_external_index_is_not_embedded_in_sleep(gd, monkeypatch):
    page = _page("a corpus page whose vector is imported, not computed", ["topic:corpus"])
    normal = g.new_object("insight", "a normal insight that is embedded", ["topic:corpus"], {"source": "t"}, instance="a")
    indexes.describe("se-ext", scope="external")
    monkeypatch.setattr(vector, "available", lambda: True)
    monkeypatch.setattr(vector, "embed_texts", lambda texts, timeout=None: [[1.0, 0.0, 0.0]] * len(texts))
    vector.catch_up(max_s=30)
    assert vector.load(normal.id) is not None and vector.load(page.id) is None


def test_an_external_index_gets_no_proximity_edges(gd):
    page = _page("an imported page close to everything", ["topic:corpus"])
    a = g.new_object("insight", "first normal insight", ["topic:x1"], {"source": "t"}, instance="a")
    b = g.new_object("insight", "second normal insight", ["topic:x2"], {"source": "t"}, instance="b")
    indexes.describe("se-ext", scope="external")
    for o in (page, a, b):
        vector.save(o.id, [1.0, 0.0, 0.0], "embed")  # identical vectors: every pair is maximally close
    r = vector.proximity_edges()
    assert r["scoped_skipped"] == 1
    with g.lock:
        rows = g.db().execute("SELECT a, b FROM edge WHERE reason LIKE 'semantisch%'").fetchall()
    touched = {x for row in rows for x in row}
    assert page.id not in touched and {a.id, b.id} <= touched
    with g.lock:
        assert g.db().execute("SELECT compared FROM vector WHERE id = ?", (page.id,)).fetchone()[0] == 1  # counted, not left open


def test_one_scope_per_index_and_global_stays_searched(gd):
    with pytest.raises(ValueError):
        indexes.describe("se-ext", explicit=True, scope="external")  # two answers to one question
    with pytest.raises(ValueError):
        indexes.describe("se-ext", scope="sometimes")
    with pytest.raises(ValueError):
        indexes.describe("global", scope="external")
    indexes.describe("se-ext", explicit=True)  # the 0.70.3 form still works and means "named"
    assert indexes.registry()["se-ext"]["scope"] == "named" and indexes.registry()["se-ext"]["explicit"] is True
    msg = indexes.describe("se-ext", scope="external")
    assert "external" in msg and indexes.registry()["se-ext"]["explicit"] is False
    assert indexes.registry()["global"]["scope"] == "all"
