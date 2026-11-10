"""0.23.0: recurring findings — vi_learn(key) updates one object per key; merge_by_key cleans up existing repetitions."""
import re

import pytest

from vi_mcp import memory as g
from vi_mcp import tools


def _learn(instance, text, key=None, tags=("host:web1", "thema:sinkhole"), **kw):
    args = {"text": text, "hashtags": list(tags), "source": "log monitoring 10.11.", **({"key": key} if key else {}), **kw}
    return tools.call_tool("vi_learn", args, instance, False)


def test_same_key_updates_one_object(gd):
    first = _learn("cs", "Known error (relevance 3, 10 repeats): web1 asks bad.example 3×", key="host:web1 threat:bad.example")
    oid = first.split()[1]
    second = _learn("cs", "Known error (relevance 3, 12 repeats): web1 asks bad.example 5×, series goes on", key="host:web1 threat:bad.example",
                    tags=("host:web1", "thema:dns"))
    assert second.startswith(f"updated {oid}") and "2×" in second
    o = g.load(oid)
    assert o.text.endswith("5×, series goes on") and o.data["repeats"] == 2 and o.data["key"] == "host:web1 threat:bad.example"
    assert [h["text"] for h in o.data["history"]] == ["Known error (relevance 3, 10 repeats): web1 asks bad.example 3×"]
    assert {"thema:sinkhole", "thema:dns", "host:web1"} <= set(o.hashtags)  # hashtags are united
    hits = [x for _, x, _g in g.recall("host:web1", viewer=None)]
    assert [x.id for x in hits] == [oid]  # one object, not two
    assert any("repeated (2×)" in c["was"] for c in o.changes)


def test_key_is_per_instance_and_without_key_nothing_changes(gd):
    a = _learn("cs", "web1 asks bad.example 3× (instance cs)", key="k-1").split()[1]
    b = _learn("other", "web1 asks bad.example 3× (instance other)", key="k-1").split()[1]
    c = _learn("cs", "web1 asks bad.example 3× without a key").split()[1]
    d = _learn("cs", "web1 asks bad.example 4× without a key").split()[1]
    assert len({a, b, c, d}) == 4 and "repeats" not in g.load(c).data


def test_refuted_object_is_not_continued(gd):
    oid = _learn("cs", "web1 asks bad.example 3× — first state", key="k-2").split()[1]
    o = g.load(oid)
    o.refute("ki@x", "wrong", "x")
    assert g.load(oid).mode == "strittig" and _learn("cs", "web1 asks bad.example 4× — while disputed", key="k-2").startswith(f"updated {oid}")
    o = g.load(oid)
    o.mode = "widerlegt"
    g.save(o)
    new = _learn("cs", "web1 asks bad.example 4× — after refutation", key="k-2").split()[1]
    assert new != oid and g.load(new).data["repeats"] == 1


def test_visibility_of_a_recurring_finding_does_not_change(gd):
    _learn("cs", "web1 asks bad.example 3× internally", key="k-3", visibility="internal")
    with pytest.raises(tools.Rejected, match="visibility"):
        _learn("cs", "web1 asks bad.example 4× shared now", key="k-3", visibility="shared")
    assert _learn("cs", "web1 asks bad.example 5× without visibility", key="k-3").startswith("updated")


def test_key_must_not_be_trivial(gd):
    with pytest.raises(tools.Rejected, match="at least 3 characters"):
        _learn("cs", "web1 asks bad.example 3× with a short key", key="k")


def test_merge_by_key_merges_repetitions_and_keeps_every_state(gd):
    texts = ["Known error (relevance 3, 32 repeats): www2: traversal — Filter: host:www2 threat:rce",
             "Known error (relevance 2, 9 repeats): smtp01: NTP unreachable — Filter: host:smtp01 rule:2903",
             "Known error (relevance 3, 42 repeats): www2: exploit series — Filter: host:www2 threat:rce",
             "Known error (relevance 3, 85 repeats): www2: ssh brute force — Filter: host:www2 threat:rce"]
    ids = [g.new_object("erkenntnis", t, ["host:www2" if "www2" in t else "host:smtp01"], {"quelle": f"cs {i}"}, instance="cs").id
           for i, t in enumerate(texts)]
    foreign = g.new_object("erkenntnis", texts[0], ["host:www2"], {"quelle": "x"}, instance="other").id
    key_of = lambda t: (m.group(1).strip() if (m := re.search(r"— Filter:\s*(.+)$", t)) else None)
    dry = g.merge_by_key("cs", key_of, who="admin", reason="test")
    assert dry == {"objects": 4, "with_key": 4, "keys": 2, "keys_repeated": 1, "merged": 2, "applied": False}
    assert g.load(ids[2]).mode == "aktiv"  # a dry run changes nothing
    r = g.merge_by_key("cs", key_of, who="admin", reason="test", apply=True)
    assert r["merged"] == 2 and r["applied"]
    main = g.load(ids[0])
    assert main.text == texts[3] and main.data["repeats"] == 3 and main.data["key"] == "host:www2 threat:rce"
    assert [h["text"] for h in main.data["history"]] == [texts[0], texts[2]] and main.data["quelle"] == "cs 3"
    for x in (ids[2], ids[3]):
        o = g.load(x)
        assert o.mode == g.MERGED and o.data["merged_into"] == ids[0] and "modus:aufgegangen" in o.hashtags  # nothing deleted
    assert g.load(ids[1]).mode == "aktiv" and g.load(foreign).mode == "aktiv"  # other key, other instance untouched
    assert {x.id for _, x, _g in g.recall("host:www2", viewer=None)} == {ids[0], foreign}
    # afterwards the key continues the main object
    assert _learn("cs", "Known error (relevance 3, 90 repeats): www2: new series", key="host:www2 threat:rce", tags=("host:www2",)).startswith(f"updated {ids[0]}")
