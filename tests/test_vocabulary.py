"""0.62.0: the vocabulary — what can be searched — and why a search found nothing."""
from vi_mcp import memory as g
from vi_mcp import tools, usage_stats, vocabulary


def _seed():
    g.new_object("erkenntnis", "nginx reload on web1", ["host:web1.example", "tool:nginx", "thema:reload"], {"quelle": "t"}, instance="a")
    g.new_object("erkenntnis", "nginx config test on web2", ["host:web2.example", "tool:nginx"], {"quelle": "t"}, instance="a")
    g.new_object("erkenntnis", "backup of db1", ["host:db1.example", "thema:backup"], {"quelle": "t"}, instance="a", visibility="intern")
    g.new_object("erkenntnis", "private: secret host", ["host:geheim.example"], {"quelle": "t"}, instance="b", visibility="privat")


def test_kinds_values_and_completion_count_only_what_the_viewer_may_see(gd):
    _seed()
    ks = {k: (nv, no) for k, nv, no in vocabulary.kinds("a")}
    assert ks["host"] == (3, 3) and ks["tool"] == (1, 2) and "instanz" not in ks  # bookkeeping kinds are not vocabulary
    assert [t for t, _n in vocabulary.values("host", "", "a")] == ["host:db1.example", "host:web1.example", "host:web2.example"]
    assert vocabulary.values("host", "web", "a") == [("host:web1.example", 1), ("host:web2.example", 1)]
    assert "host:geheim.example" not in {t for t, _n in vocabulary.values("host", "", "a")}  # someone else's private object
    assert "host:geheim.example" in {t for t, _n in vocabulary.values("host", "", "b")}  # its owner sees it
    assert "host:db1.example" not in {t for t, _n in vocabulary.values("host", "", "offen")}  # internal needs a token
    assert vocabulary.complete("host:we", "a")[0][0].startswith("host:web")
    comp = dict(vocabulary.complete("ngi", "a"))
    assert comp == {"tool:nginx": 2}
    assert ("host:", 3) in vocabulary.complete("ho", "a")
    assert vocabulary.values("instanz", "", "a") == []


def test_empty_search_names_unknown_words_with_suggestions_or_known_words_that_do_not_meet(gd):
    _seed()
    reason, unknown = vocabulary.empty_reason("host:web3.example", "a")
    assert reason == "unbekannt" and unknown == [("host:web3.example", ["host:web1.example", "host:web2.example"])]
    assert vocabulary.empty_reason("host:db1.example tool:nginx", "a") == ("verfehlt", [])
    assert vocabulary.empty_reason("quasselstrippe", "a")[0] == "unbekannt"
    out = tools.call_tool("vi_recall", {"filter": "host:web3.example", "semantic": False}, "a", False)
    assert "unknown words: host:web3.example is not in memory (did you mean host:web1.example, host:web2.example?)" in out
    out = tools.call_tool("vi_recall", {"filter": "host:db1.example tool:nginx", "semantic": False}, "a", False)
    assert "known words, but no object carries them together" in out


def test_vi_vocabulary_tool_and_statistics_split(gd):
    _seed()
    assert "host:  (3 values, 3 objects)" in tools.call_tool("vi_vocabulary", {}, "a", False)
    assert "host:web1.example  (1)" in tools.call_tool("vi_vocabulary", {"word_kind": "host", "prefix": "web"}, "a", False)
    assert "tool:nginx  (2)" in tools.call_tool("vi_vocabulary", {"prefix": "ngi"}, "a", False)
    for f in ("host:web3.example", "host:db1.example tool:nginx", "host:web1.example"):
        text = tools.call_tool("vi_recall", {"filter": f, "semantic": False}, "a", False)
        usage_stats.record("a", "test", "vi_recall", "ok", 5, text)
    s = usage_stats.data(1)["suche"]
    assert s["ohne_treffer"] == 2 and s["leer_grund"] == {"unbekannt": 1, "verfehlt": 1}
    rep = usage_stats.report(1)
    assert "word unknown in memory (nothing known: the right answer) 1" in rep and "words known, not together (a search problem) 1" in rep
