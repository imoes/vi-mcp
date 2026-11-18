"""0.69.0: the documentation import access — vi_doc_sync (server) and `vi-mcp docs import` (client)."""
import json

import pytest

from vi_mcp import archive, config, doc_import, doc_triggers, memory as g, tools
from vi_mcp.tools import Rejected


def _call(name, args, instance="importer", importer=True):
    return json.loads(tools.call_tool(name, args, instance, False, import_permission=importer))


def _page(pid, title="Install the web cluster", body="## Steps\nRun the playbook on web1.example.org.\n\n## Check\nopen the page", **kw):
    return {"page_id": pid, "title": title, "markdown": f"# {title}\n\n{body}", "url": f"https://wiki.example.org/{pid}", "version": 3, **kw}


def test_an_agent_token_cannot_import(gd):
    with pytest.raises(Rejected, match="import right"):
        tools.call_tool("vi_doc_sync", {"action": "state", "source": "wiki"}, "claude-code", False)


def test_a_page_becomes_one_object_with_source_tags_and_triggers_at_once(gd):
    known = g.new_object("insight", "web1 runs nginx", ["host:web1.example.org", "topic:nginx"], {"source": "test"}, instance="a")
    for i in range(3):  # topic:deploy is a topic learned knowledge uses (doc_triggers.THEMA_MIN)
        g.new_object("insight", f"deploy fact {i}", ["topic:deploy"], {"source": "t"}, instance="a")
    doc_triggers._cache["at"] = 0.0
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "label": "Wiki IT", "knowledge_kind": "company-docs",
                              "pages": [_page("101", title="Deploy the web cluster", labels=["Runbook", "Web"], service="web-cluster",
                                              space="IT", area="it-muenchen")]})
    assert r["new"] == 1 and r["with_host"] == 1 and r["with_topic"] == 1
    o = g.load(doc_import.object_id("wiki", "101", 1))
    assert o.text.startswith("Wiki IT: Deploy the web cluster — ") and o.data["content"].startswith("# Deploy the web cluster")
    for t in ("source_kind:wiki", "knowledge_kind:company-docs", "page:101", "space:it", "area:it-muenchen", "label:runbook", "label:web",
              "service:web-cluster", "host:web1.example.org", "topic:deploy"):
        assert t in o.hashtags, t
    assert o.visibility == "internal" and o.data["derived_triggers"]["at"] == "import"
    assert known.id != o.id


def test_unchanged_pages_are_skipped_changed_ones_updated_in_place(gd):
    p = _page("7")
    assert _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [p]})["new"] == 1
    assert _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [p]})["unchanged"] == 1
    p2 = _page("7", body="## Steps\nnew text for the page")
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [p2]}, instance="another-importer")
    assert r["updated"] == 1  # the id is fixed per source and page, not per instance
    state = _call("vi_doc_sync", {"action": "state", "source": "wiki"})
    assert state["pages"]["7"] == doc_import.content_sha(p2["markdown"].strip()) and state["objects"] == 1


def test_the_old_shape_of_the_page_is_archived_whoever_wrote_it(gd):
    parts = [g.new_object("insight", f"Confluence IT: Install (Teil {i}/2)", ["source_kind:wiki", "page:55", "knowledge_kind:company-docs",
                                                                              f"topic:dns{i}", "area:it-kassel"],
                          {"source": "old import", "content": f"part {i}"}, instance="old-importer", visibility="internal") for i in (1, 2)]
    other_page = g.new_object("insight", "another page", ["source_kind:wiki", "page:56"], {"source": "old"}, instance="old-importer")
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("55")]})
    assert r["old_shape_archived"] == 2
    new = doc_import.object_id("wiki", "55", 1)
    for o in parts:
        assert g.load(o.id).mode == "archived" and new in g.load(o.id).data["reason"]
        assert archive.content(o.id)["text"].startswith("Confluence IT: Install (Teil")  # restorable, nothing lost
    assert g.load(other_page.id).mode == "active"
    tags = g.load(new).hashtags
    assert "topic:dns1" in tags and "topic:dns2" in tags and "area:it-kassel" in tags  # what the old shape carried stays
    # 0.69.2: and it stays when the page changes later (production 17.11.2026: an update dropped topic:stibo-doku)
    _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("55", body="## Steps\nchanged later")]})
    tags = g.load(new).hashtags
    assert "topic:dns1" in tags and "topic:dns2" in tags and "area:it-kassel" in tags


def test_removed_pages_are_archived_and_links_become_edges_in_both_orders(gd):
    _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("1", links=["2"])]})
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("2", title="Second page")]})
    assert r["links"] == 1  # page 1 linked to 2 before 2 existed: the edge comes when 2 arrives
    a, b = doc_import.object_id("wiki", "1", 1), doc_import.object_id("wiki", "2", 1)
    assert any(x == b and reason == "doc link" for x, reason in g.load(a).edges())
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "removed": ["2"]})
    assert r["removed_archived"] == 1 and g.load(b).mode == "archived"
    assert "2" not in _call("vi_doc_sync", {"action": "state", "source": "wiki"})["pages"]


def test_a_page_over_the_content_limit_is_split_and_a_shorter_version_archives_the_leftover_part(gd, monkeypatch):
    monkeypatch.setattr(g, "CONTENT_MAX", 200)
    long = _page("9", body="\n\n".join(f"paragraph {i} " + "x" * 80 for i in range(5)))
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [long]})
    n = r["new"]
    assert n >= 2 and r["parts"] == n
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("9")]})
    assert r["leftover_parts_archived"] == n - 1


def test_secrets_are_replaced_and_limits_hold(gd):
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page("3", body="login with password=hunter2 on the box")]})
    assert r["secrets_replaced"] == 1 and "hunter2" not in g.load(doc_import.object_id("wiki", "3", 1)).data["content"]
    again = doc_import.run([_page("3", body="login with password=hunter2 on the box")], "wiki", lambda n, a_: _call(n, a_))
    assert again["to_send"] == 0  # the hash is of the page as sent, so a page with a replaced secret is not sent again and again
    with pytest.raises(Rejected, match="at most"):
        _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [_page(str(i)) for i in range(doc_import.PAGES_MAX + 1)]})
    with pytest.raises(Rejected, match="source"):
        _call("vi_doc_sync", {"action": "sync", "source": "Bad Name!", "pages": [_page("4")]})
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [{"page_id": "", "markdown": "x"}]})
    assert r["rejected"] and r["new"] == 0


def test_the_client_sends_only_changed_pages_and_prunes(gd, tmp_path):
    f = tmp_path / "pages.jsonl"
    f.write_text("\n".join(json.dumps(_page(p)) for p in ("a1", "a2", "a3")), encoding="utf-8")
    call = lambda n, a: _call(n, a)  # noqa: E731
    r = doc_import.run(doc_import.read_pages(f), "wiki", call, index="docs-test", knowledge_kind="manual")
    assert r["to_send"] == 3 and r["totals"]["new"] == 3
    assert g.load(doc_import.object_id("wiki", "a1", 1)).idx == "docs-test"
    f.write_text("\n".join(json.dumps(_page(p)) for p in ("a1", "a2")), encoding="utf-8")
    r = doc_import.run(doc_import.read_pages(f), "wiki", call, prune=True)
    assert r["to_send"] == 0 and r["to_remove"] == 1 and r["totals"]["removed_archived"] == 1


def test_the_import_right_is_stored_and_read(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    config.create_instance("aikb-import", p=p, importer=True)
    config.create_instance("agent", p=p)
    k = config.load(p)
    assert k.instances["aikb-import"].importer and not k.instances["agent"].importer


def test_an_older_source_kind_is_retired_through_old_source_kind(gd):
    old = g.new_object("insight", "Stibo DX: page (Teil 1/1)", ["source_kind:stibodx", "page:900"], {"source": "old"}, instance="claude-code")
    r = _call("vi_doc_sync", {"action": "sync", "source": "dcx-docs", "pages": [_page("900")]})
    assert r["old_shape_archived"] == 0 and g.load(old.id).mode == "active"  # another source_kind: not touched by default
    r = _call("vi_doc_sync", {"action": "sync", "source": "dcx-docs", "old_source_kind": "stibodx", "pages": [_page("900", body="## new\nchanged text")]})
    assert r["old_shape_archived"] == 1 and g.load(old.id).mode == "archived"


def test_topics_come_from_the_title_without_filler_words_and_old_tagging_is_redone(gd, monkeypatch):
    """0.69.1: production 17.11.2026 — topics were taken from the key statement (title + the body's first 300 characters), and learned
    knowledge carried topic:for / topic:old, so documentation got topic:for, topic:old, topic:error."""
    for t in ("for", "old", "error", "deadlocks", "nginx"):
        for i in range(3):
            g.new_object("insight", f"{t} fact {i}", [f"topic:{t}"], {"source": "t"}, instance="a")
    doc_triggers._cache["at"] = 0.0
    p = _page("31", title="Coping with deadlocks", body="## Why\nDeadlocks happen for old error reasons, behind nginx too.")
    _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [p]})
    tags = g.load(doc_import.object_id("wiki", "31", 1)).hashtags
    assert "topic:deadlocks" in tags and not {"topic:for", "topic:old", "topic:error"} & set(tags)
    assert "topic:nginx" not in tags  # a topic named only in the body is no trigger (title only)
    # a page tagged by an older import version is reported without hash and re-tagged on the next run
    o = g.load(doc_import.object_id("wiki", "31", 1))
    o.data["doc_import"]["tagger"] = 1
    o.hashtags = sorted(set(o.hashtags) | {"topic:for"})
    g.save(o)
    assert _call("vi_doc_sync", {"action": "state", "source": "wiki"})["pages"]["31"] is None
    r = _call("vi_doc_sync", {"action": "sync", "source": "wiki", "pages": [p]})
    assert r["updated"] == 1 and "topic:for" not in g.load(o.id).hashtags


def test_sleep_takes_filler_topics_it_derived_earlier_off_again(gd):
    from vi_mcp import doc_triggers
    o = g.new_object("insight", "Confluence IT: for the old page", ["knowledge_kind:company-docs", "topic:for", "topic:dns"],
                     {"source": "old", "derived_triggers": {"version": 1, "host": [], "topic": ["for", "dns"]}}, instance="x")
    r = doc_triggers.run()
    tags = g.load(o.id).hashtags
    assert "topic:for" not in tags and "topic:dns" in tags and r.get("entfernt") == 1


def test_documents_of_a_directory_are_imported_and_prune_keeps_refused_files(gd, tmp_path):
    """0.70.0: `vi-mcp docs import DIR` — documents become pages (doc_formats); a file that cannot be read this time is refused with its
    reason, and --prune must not archive its page as if it had been removed at the source (nothing disappears silently)."""
    from test_doc_formats import _docx
    tmp_path = tmp_path / "docs"  # the test memory (vi.db) lives in tmp_path itself
    tmp_path.mkdir()
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "runbook.docx").write_bytes(_docx())
    (tmp_path / "notes.md").write_text("# Notes\n\nweb1.example.org restarts at night", encoding="utf-8")
    pages, refused = doc_import.load([str(tmp_path)])
    call = lambda n, a_: _call(n, a_)  # noqa: E731
    r = doc_import.run(pages, "files", call)
    assert r["to_send"] == 2 and not refused
    o = g.load(doc_import.object_id("files", "ops/runbook.docx", 1))
    assert "label:format-docx" in o.hashtags and "area:ops" in o.hashtags and "| mail01 | 120 GB |" in o.data["content"]
    (tmp_path / "ops" / "runbook.docx").write_bytes(b"broken now")   # unreadable this time
    (tmp_path / "notes.md").unlink()                                  # really removed at the source
    pages, refused = doc_import.load([str(tmp_path)])
    assert [x["kind"] for x in refused] == ["unreadable"]
    r = doc_import.run(pages, "files", call, prune=True, keep={doc_import._page_id_of(x["file"], [str(tmp_path)]) for x in refused})
    assert r["to_remove"] == 1  # notes.md only
    assert g.load(doc_import.object_id("files", "ops/runbook.docx", 1)).mode == "active"
    assert g.load(doc_import.object_id("files", "notes.md", 1)).mode == "archived"
    s = doc_import.summary(*doc_import.load([str(tmp_path)]))
    assert s["refused_by_class"] == {"unreadable": 1} and s["refused_files"][0]["reason"]
