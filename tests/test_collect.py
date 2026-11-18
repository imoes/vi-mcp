"""Collect mode of vi_recall (vi_mcp/collect.py): a question about everything of one entity gets the chunks of every object about it
under a token budget. Invented hosts and pages only."""
from vi_mcp import collect, tools, vector
from vi_mcp import memory as g

PAGE = "https://wiki.example.org/pages/100/host7"


def _page(gd):
    g.new_object("insight", "Wiki: host7.example.org – Hardware: (part 1/2): board X470", ["host:host7.example.org"],
                 {"source": f"{PAGE} · version 5", "content": "## Hardware\n\n| CPU | 16 cores |\n|---|---|\n| RAM | 128 GB |\n"},
                 reason="T", visibility="shared")
    g.new_object("insight", "Wiki: host7.example.org – Disks: (part 2/2): two NVMe", ["host:host7.example.org"],
                 {"source": f"{PAGE} · version 5", "content": "## Disks\n\nTwo NVMe in a ZFS mirror, 2 TB each.\n"},
                 reason="T", visibility="shared")
    g.new_object("insight", "Cluster overview: host7 and host8 form cluster C7", ["host:host7.example.org", "host:host8.example.org"],
                 {"source": "https://wiki.example.org/pages/200/cluster", "content": "## Members\n\nhost7, host8.\n"},
                 reason="T", visibility="shared")
    g.new_object("insight", "Printer driver install on desk12", ["host:desk12.example.org"],
                 {"source": "https://wiki.example.org/pages/300/printer", "content": "## Driver\n\nInstall the driver.\n"},
                 reason="T", visibility="shared")


def test_the_router_tells_collect_questions_from_single_facts(gd):
    _page(gd)
    assert "collect intent" in collect.detect("which hardware does host7 have?")["reason"]
    assert collect.detect("what hardware does host7 have")["entities"] == ["host:host7.example.org"]
    assert "the entity" in collect.detect("host7")["reason"]
    assert collect.detect("backup failed on host7 since yesterday") is None  # a single fact about the host
    assert collect.detect("which printer driver") is None                     # intent without a known entity
    assert collect.detect("hardware of host99") is None                       # no hashtag of that name


def test_collect_gathers_both_parts_of_a_page_in_order_and_names_what_it_left_out(gd, monkeypatch):
    _page(gd)
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [5.0 if ("RAM" in d or "NVMe" in d) else 0.0 for d in docs])
    hits = g.recall("host7", limit=1)
    ctx, counts = collect.collect("hardware host7", hits, collect.detect("hardware of host7"))
    assert counts["objects_with_entity_tag"] == 3 and counts["pages"] == 2  # the host page (two parts) and the cluster page
    assert ctx.index("| RAM | 128 GB |") < ctx.index("Two NVMe in a ZFS mirror")  # part 1 before part 2, one page
    assert "parts 2 of 2 found" in ctx
    assert "Printer" not in ctx  # another entity's page is never a candidate
    line = collect.note(counts)
    assert "objects carry the entity hashtag" in line and "scored by reranker" in line


def test_a_failing_reranker_never_costs_the_answer(gd, monkeypatch):
    _page(gd)
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: (_ for _ in ()).throw(OSError("down")))
    ctx, counts = collect.collect("hardware host7", [], collect.detect("hardware of host7"))
    assert "RAM" in ctx and counts["scored_by"].startswith("word overlap (reranker failed")


def test_vi_recall_switches_by_itself_and_collect_false_switches_it_off(gd, monkeypatch):
    _page(gd)
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [1.0 for _ in docs])
    on = tools._recall({"filter": "which hardware does host7 have?", "reinforce": False}, "a", None, None)
    off = tools._recall({"filter": "which hardware does host7 have?", "reinforce": False, "collect": False}, "a", None, None)
    assert "collect mode (entity host:host7.example.org" in on and "| RAM | 128 GB |" in on
    assert "collect mode" not in off


def test_the_budget_holds_and_private_objects_of_others_stay_invisible(gd, monkeypatch):
    _page(gd)
    g.new_object("insight", "host7 secret note", ["host:host7.example.org"], {"content": "secret " * 50}, reason="T",
                 instance="other", visibility="private")
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [1.0 for _ in docs])
    token = g.current_instance.set("a")  # reset afterwards: a leaked instance broke 8 later tests of the suite
    try:
        ctx, counts = collect.collect("host7", [], collect.detect("host7"), min_tokens=10, max_tokens=60)
    finally:
        g.current_instance.reset(token)
    assert counts["tokens"] <= 60 and "secret" not in ctx


def test_the_lexicon_links_the_memorys_entity_words_and_rejects_paths(gd):
    from vi_mcp import lexicon
    lexicon.clear()
    _page(gd)
    g.new_object("insight", "Rack plan of site SITE-1", ["location:SITE-1"], {"content": "racks"}, reason="T", visibility="shared")
    g.new_object("insight", "Systemd summary check", ["service:Systemd-Service-Summary"], {}, reason="T", visibility="shared")
    g.new_object("insight", "a path", ["host:$s/handbuch.py;"], {}, reason="T", visibility="shared")
    lexicon.clear()
    tags = [e["tag"] for e in lexicon.link("which hosts are at SITE-1 and what does the systemd service summary report on host7?")]
    assert "location:SITE-1" in tags and "service:Systemd-Service-Summary" in tags and "host:host7.example.org" in tags
    assert lexicon.lexicon()["rejected"]["host"] == 1  # the path is not a host name
    assert "location (1)" in lexicon.describe() and "not names, left out: 1 host" in lexicon.describe()


def test_a_site_is_an_entity_of_the_collect_mode_too(gd, monkeypatch):
    from vi_mcp import lexicon
    _page(gd)
    g.new_object("insight", "Rack plan of site SITE-1: host7 in rack 3", ["location:SITE-1"], {"content": "## Racks\n\nhost7 in rack 3.\n"},
                 reason="T", visibility="shared")
    lexicon.clear()
    d = collect.detect("which hosts are at SITE-1?")
    assert d and d["entities"] == ["location:SITE-1"]
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [1.0 for _ in docs])
    ctx, counts = collect.collect("hosts SITE-1", [], d)
    assert "rack 3" in ctx and counts["objects_with_entity_tag"] == 1


def test_the_lexicon_never_names_an_entity_the_asker_cannot_see(gd):
    from vi_mcp import lexicon
    g.new_object("insight", "secret box", ["host:secretbox9.example.org"], {}, reason="T", instance="other", visibility="private")
    lexicon.clear()
    token = g.current_instance.set("a")
    try:
        assert lexicon.link("hardware of secretbox9") == []
    finally:
        g.current_instance.reset(token)


def test_the_answer_names_the_next_steps_for_an_agentic_follow_up(gd, monkeypatch):
    _page(gd)
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [5.0 if "RAM" in d else -9.0 for d in docs])
    ctx, counts = collect.collect("RAM of host7", [], collect.detect("hardware of host7"), min_tokens=1, max_tokens=60, per_page=1)
    line = collect.note(counts)
    assert "\nfollow-up: " in line and "vi_object <id>" in line
    assert 'vi_recall("host:host7.example.org", collect=false, limit=50) lists all 3 objects' in line
    assert counts["pages_left_out"] and "pages not shown: " in line


def test_short_words_are_never_hosts(gd):
    from vi_mcp import lexicon
    g.new_object("insight", "abc host", ["host:abc.example.org"], {}, reason="T", visibility="shared")
    lexicon.clear()
    assert lexicon.link("which apps abc run") == []


def test_a_list_question_gets_the_entities_that_occur_with_it_and_a_broad_entity_is_narrowed(gd, monkeypatch):
    from vi_mcp import lexicon
    for i in range(12):
        g.new_object("insight", f"finding {i} on web{i % 3} at the site", ["location:SITE-9", f"host:web{i % 3}.example.org"],
                     {"content": f"## Finding\n\nweb{i % 3} disk {i}\n"}, reason="T", visibility="shared")
    lexicon.clear()
    monkeypatch.setattr(collect, "BROAD", 5)
    monkeypatch.setattr(collect, "BROAD_TOP", 4)
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [1.0 for _ in docs])
    d = collect.detect("which hosts are at SITE-9?")
    ctx, counts = collect.collect("Hosts SITE-9", [], d)
    hosts = dict(counts["related"]["host"])
    assert hosts == {"host:web0.example.org": 4, "host:web1.example.org": 4, "host:web2.example.org": 4}
    b = counts["broad_entity"]
    assert b["objects"] == 12 and b["kept_by_question"] + b["filled_by_recency"] == 4
    line = collect.note(counts)
    assert "with it — host: web0.example.org (4)" in line and "a broad entity (12 objects)" in line


def test_collect_mode_obeys_the_index_filter_and_never_reads_index_as_a_word(gd, monkeypatch):
    """0.70.1, seen live on 0.70.0 (18.11.2026): "index:ansible docker" made the word "index" an entity (host:index.html), and the
    collected chunks came from every index — the AND of index:<name> leaked into the collect mode."""
    _page(gd)
    g.new_object("insight", "Runbook index.html deploy", ["host:index.html"], {"source": "t", "content": "x"}, reason="T", visibility="shared")
    g.new_object("insight", "Project alpha: host7.example.org runs the build agent", ["host:host7.example.org"],
                 {"source": "https://wiki.example.org/pages/400/alpha", "content": "## Agent\n\nThe build agent of alpha.\n"},
                 reason="T", visibility="shared", index="alpha")
    monkeypatch.setattr(vector, "rerank_fn", lambda q, docs: [1.0 for _ in docs])
    out = tools._recall({"filter": "index:alpha host7", "reinforce": False}, "a", None, None)
    assert "host:index.html" not in out  # "index" of index:alpha is no word of the question
    assert "build agent of alpha" in out and "| RAM | 128 GB |" not in out and "two NVMe" not in out  # only the alpha object
    everywhere = tools._recall({"filter": "host7", "reinforce": False}, "a", None, None)
    assert "| RAM | 128 GB |" in everywhere  # without the index the global pages are collected as before
