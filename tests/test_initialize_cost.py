"""24.11.2026: under session churn (~15 new sessions a minute, no DELETE) every initialize rebuilt the memory index under the global
database lock (0.35 s of 0.67 s on a production copy), and on a cache miss every concurrent initialize built the skill table itself.
The index is now cached per instance and budget, built once at a time, and new knowledge still shows at once."""
import threading

from vi_mcp import capabilities, index
from vi_mcp import memory as g


def _count_index_builds(monkeypatch):
    n = []
    real = index.sections
    monkeypatch.setattr(index, "sections", lambda inst: (n.append(inst), real(inst))[1])
    return n


def test_the_index_is_built_once_and_new_knowledge_shows_at_once(gd, monkeypatch):
    g.new_object("insight", "Backups run at 02:00 on the backup host", ["topic:backup"], {}, instance="a")
    builds = _count_index_builds(monkeypatch)
    first = index.text("a")
    assert index.text("a") == first and len(builds) == 1  # the second initialize reads the cache
    g.new_object("experience", "graylog_search → ok", ["tool:graylog_search"], {}, instance="a")
    assert index.text("a") == first and len(builds) == 1  # an experience (every vi_after) does not clear it
    g.new_object("insight", "Restores need the second key from the safe", ["topic:backup"], {}, instance="a")
    assert "second key" in index.text("a") and len(builds) == 2  # learned knowledge is listed at once
    assert index.text("a", max_chars=900) and len(builds) == 3  # another budget is another entry


def test_the_cache_expires(gd, monkeypatch):
    g.new_object("insight", "Backups run at 02:00 on the backup host", ["topic:backup"], {}, instance="a")
    builds = _count_index_builds(monkeypatch)
    index.text("a")
    monkeypatch.setattr(index, "CACHE_S", 0.0)
    index.text("a")
    assert len(builds) == 2


def test_concurrent_initializes_wait_for_one_build(gd, monkeypatch):
    g.new_object("insight", "Backups run at 02:00 on the backup host", ["topic:backup"], {}, instance="a")
    gate, builds = threading.Event(), []
    real = index._text

    def slow(inst, n):
        builds.append(inst)
        gate.wait(2)
        return real(inst, n)
    monkeypatch.setattr(index, "_text", slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(index.text("a"))) for _ in range(5)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join(10)
    assert builds == ["a"] and len(out) == 5 and len(set(out)) == 1


def test_the_skill_table_is_built_once_under_concurrency(gd, monkeypatch):
    gate, builds = threading.Event(), []
    real = capabilities._table_now

    def slow(inst):
        builds.append(inst)
        gate.wait(2)
        return real(inst)
    monkeypatch.setattr(capabilities, "_table_now", slow)
    ts = [threading.Thread(target=capabilities.table, args=("a",)) for _ in range(5)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join(10)
    assert builds == ["a"]


def test_memory_knows_the_index_kinds():
    assert g._INDEX_KINDS == frozenset(index.KINDS)  # memory.save clears the index cache for exactly these kinds
