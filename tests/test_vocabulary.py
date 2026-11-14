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


def test_a_search_that_excludes_the_only_matches_is_named_not_a_search_problem(gd):
    """0.62.5, found on production: CentralStation's host lookups exclude its own experiences; when only those carry the host, the
    empty answer is right, and it was counted as "known words, not together (a search problem)"."""
    g.new_object("erfahrung", "Bash on web9", ["host:web9.example", "tool:Bash", "ok:ja"], {}, instance="centralstation")
    g.new_object("erkenntnis", "db1 backup", ["host:db1.example"], {"quelle": "t"})
    assert vocabulary.empty_reason("(host:web9.example) !instanz:centralstation !art:erfahrung", None)[0] == "ausgeschlossen"
    assert vocabulary.empty_reason("host:web9.example host:db1.example", None)[0] == "verfehlt"  # both known, never together
    out = tools.call_tool("vi_recall", {"filter": "(host:web9.example) !instanz:centralstation !art:erfahrung", "semantic": False},
                          "centralstation", False)
    assert "occur only in what your exclusions" in out


def test_an_unknown_kind_gets_the_same_value_under_the_kind_that_exists(gd):
    """0.62.5, found on production: `quelle:confluence` answered "not in memory" without a suggestion; the tag is quelle_art:confluence."""
    for i in range(3):
        g.new_object("erkenntnis", f"KB page {i}", ["quelle_art:confluence", "thema:linux"], {"quelle": "t"})
    g.new_object("erkenntnis", "secret page", ["herkunft_x:confluence"], {"quelle": "t"}, instance="b", visibility="privat")
    out = tools.call_tool("vi_recall", {"filter": "quelle:confluence", "semantic": False}, "a", False)
    assert "did you mean quelle_art:confluence" in out
    assert "herkunft_x" not in out  # nothing the viewer may not see


def test_an_empty_search_names_the_live_network_search(gd, monkeypatch):
    """0.63.0, found on production: an agent of a local VI read vi_net_status instead of asking the other server live."""
    from vi_mcp import p2p
    out = tools.call_tool("vi_recall", {"filter": "zzqqxx", "semantic": False}, "a", False)
    assert "vi_net_search" not in out  # no network service has reported: nothing to suggest
    p2p.record_state("standard", {"modus": "peer"})
    out = tools.call_tool("vi_recall", {"filter": "zzqqxx", "semantic": False}, "a", False)
    assert "vi_net_search(network=…, query=…) asks the members of standard live" in out and "only through a company network" in out
    monkeypatch.setattr(p2p, "networks", lambda: {"standard": {"kind": "open"}, "firma": {"kind": "company"}})
    p2p.record_state("firma", {"modus": "peer"})
    out = tools.call_tool("vi_recall", {"filter": "zzqqxx", "semantic": False}, "a", False)
    assert "firma, standard live (internal knowledge only in firma)" in out
