"""0.70.3: an index searched only when named (vi_index.explicit) — a large external corpus (an imported Q&A site) lives in the memory
without appearing in searches without an index, in hints, in the sleep's embedding or in its LLM labelling."""
import pytest

from vi_mcp import indexes, intuition, vector
from vi_mcp import memory as g


def _corpus_page(text, tags, idx="se-test"):
    return g.new_object("insight", text, tags, {"source": "test 19.11.2026"}, instance="importer", index=idx)


def _ids(filter_text):
    return {o.id for _, o, _g in g.recall(filter_text, limit=50)}


def test_an_explicit_index_is_found_only_when_named(gd):
    page = _corpus_page("rsync over ssh drops the connection after a minute", ["topic:rsync", "host:web1.example"])
    normal = g.new_object("insight", "rsync needs the trailing slash to copy the content", ["topic:rsync"], {"source": "t"}, instance="a")
    assert page.id in _ids("topic:rsync")  # an ordinary project index is searched by default (unchanged behaviour)
    indexes.describe("se-test", explicit=True)
    found = _ids("topic:rsync")
    assert page.id not in found and normal.id in found
    assert page.id in _ids("index:se-test topic:rsync")  # named in the filter
    token = g.search_index.set("se-test")  # vi_recall(index=…)
    try:
        assert _ids("topic:rsync") == {page.id}
    finally:
        g.search_index.reset(token)
    indexes.describe("se-test", explicit=False)  # and back
    assert page.id in _ids("topic:rsync")


def test_an_explicit_index_never_becomes_a_hint(gd):
    page = _corpus_page("web1 answers ssh only with BatchMode and the key file", ["host:web1.example", "tool:Bash"])
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "a", False)
    assert page.id in v["zugriff"]["shown"]  # control: the same object is a hint while its index is normal
    indexes.describe("se-test", explicit=True)
    v = intuition.before("Bash", {"command": "ssh web1.example uptime"}, "b", False)
    assert page.id not in v["zugriff"]["shown"]


def test_an_explicit_index_is_not_embedded_in_sleep(gd, monkeypatch):
    page = _corpus_page("a corpus page that must not be embedded", ["topic:corpus"])
    normal = g.new_object("insight", "a normal insight that is embedded", ["topic:corpus"], {"source": "t"}, instance="a")
    indexes.describe("se-test", explicit=True)
    monkeypatch.setattr(vector, "available", lambda: True)
    monkeypatch.setattr(vector, "embed_texts", lambda texts, timeout=None: [[1.0, 0.0, 0.0]] * len(texts))
    vector.catch_up(max_s=30)
    assert vector.load(normal.id) is not None and vector.load(page.id) is None


def test_global_cannot_be_made_explicit(gd):
    with pytest.raises(ValueError):
        indexes.describe("global", explicit=True)
    assert "explicit" in indexes.registry()["global"] and indexes.registry()["global"]["explicit"] is False
