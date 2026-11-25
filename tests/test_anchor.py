"""0.72.0: title anchor + one mention hop in vi_recall (goal Z6), behind config search_anchor. Example names only."""
import hashlib
import re

import pytest

from vi_mcp import anchor, config, session, tools, vector
from vi_mcp import memory as g

DIM = 64


def _embed(texts):
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            v[int(hashlib.sha256(w.encode()).hexdigest()[:8], 16) % DIM] += 1.0
        out.append(v)
    return out


@pytest.fixture()
def docs(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", _embed)
    monkeypatch.setattr(vector, "config", {"model": "fake"})
    monkeypatch.setattr(anchor, "MODE", "off")
    monkeypatch.setattr(anchor, "SHARE", 0.0)
    monkeypatch.setattr(anchor, "HOPS", 1)
    anchor.forget()

    def page(key, text, instance="a", visibility="internal", idx="global"):
        o = g.new_object("insight", f"Confluence IT: {text}", ["source_kind:confluence"], {"content": text}, instance=instance,
                         visibility=visibility, oid=f"insight:doc-{key}")
        if idx != "global":
            o.idx = idx
            g.save(o)
        return o.id
    ids = {
        "vm": page("vm", "app0042.example.org — virtual machine for the shop, runs on pve0007.example.org"),
        "node": page("node", "pve0007.example.org — Proxmox node, operating system Debian 12, gateway 192.0.2.1"),
        "other": page("other", "web0001.example.org — web server, Debian, gateway configuration"),
    }
    for i in range(30):  # many pages that share the question's words, so the hybrid list alone does not put both in front
        page(f"noise{i}", f"Notes {i} — which operating system, gateway and node settings to use for the virtual machine shop")
    vector.catch_up(max_s=600)
    yield ids
    anchor.forget()


def _search(question, instance="a", limit=4):
    s = session.begin(instance, "test")  # as a client: the viewer (visibility) and the conversation (ab arm) come from the session
    with session.on_behalf(s):
        r = tools.call_tool("vi_recall", {"filter": question, "limit": limit, "reinforce": False}, instance, True)
    return re.findall(r"^\s*\[([a-z_]+:[0-9a-z\-]+)\]", str(r), re.M), str(r)


def test_title_keys_follow_the_digit_rule():
    assert anchor._keys("app0042.example.org — x") == ["app0042.example.org", "app0042"]
    assert anchor._keys("system.example.org overview") == ["system.example.org"]  # an everyday first label is no key
    assert anchor._keys("example.org only two labels") == []
    assert anchor.title_of("Confluence IT: pve0007.example.org — node") == "pve0007.example.org"


def test_off_changes_nothing_and_on_puts_anchor_and_hop_first(docs, monkeypatch):
    q = "Which operating system runs on the node that hosts the VM app0042?"
    off, note_off = _search(q)
    assert "anchor" not in note_off.splitlines()[0]
    monkeypatch.setattr(anchor, "MODE", "on")
    on, note_on = _search(q)
    assert on[:2] == [docs["vm"], docs["node"]]
    head = note_on.splitlines()[0]
    assert f"anchor on: app0042 → {docs['vm']} (+1 hop)" in head and "hybrid" in head


def test_the_hop_count_is_honoured(docs, monkeypatch):
    monkeypatch.setattr(anchor, "MODE", "on")
    monkeypatch.setattr(anchor, "HOPS", 0)
    on, note = _search("Which operating system runs on the node that hosts the VM app0042?")
    head = note.splitlines()[0]
    assert on[0] == docs["vm"] and f"app0042 → {docs['vm']}" in head and "hop)" not in head  # the anchor alone, no hop placed


def test_a_search_in_one_index_gets_no_anchor_from_another(docs, monkeypatch):
    monkeypatch.setattr(anchor, "MODE", "on")
    o = g.new_object("insight", "Runbook for the shop app0042 operating system in the project index", ["topic:shop"], {},
                     instance="a", visibility="internal")
    o.idx = "project-x"
    g.save(o)
    vector.catch_up(max_s=600)
    s = session.begin("a", "test")
    with session.on_behalf(s):
        r = str(tools.call_tool("vi_recall", {"filter": "operating system of app0042", "index": "project-x", "limit": 4,
                                              "reinforce": False}, "a", True))
    assert o.id in r  # the search of project-x works ...
    assert docs["vm"] not in r and docs["node"] not in r  # ... and the anchor pages live in global: not in a search of project-x alone


def test_an_anchor_or_hop_the_viewer_cannot_see_is_not_used(docs, monkeypatch):
    monkeypatch.setattr(anchor, "MODE", "on")
    with g.lock:  # the node page becomes private to another instance
        g.db().execute("UPDATE object SET visibility = 'private', instance = 'b' WHERE id = ?", (docs["node"],))
        g.db().commit()
    on, _ = _search("Which operating system runs on the node that hosts the VM app0042?")
    assert on[0] == docs["vm"] and docs["node"] not in on
    with g.lock:  # and the VM page too: no anchor at all
        g.db().execute("UPDATE object SET visibility = 'private', instance = 'b' WHERE id = ?", (docs["vm"],))
        g.db().commit()
    on, note = _search("Which operating system runs on the node that hosts the VM app0042?")
    assert docs["vm"] not in on and "no host page named" in note.splitlines()[0]


def test_pages_of_a_search_scoped_index_are_no_anchor(docs, monkeypatch):
    monkeypatch.setattr(anchor, "MODE", "on")
    o = g.load(docs["vm"])
    o.idx = "corpus"
    g.save(o)
    with g.lock:
        g.db().execute("UPDATE vi_index SET explicit = 2 WHERE name = 'corpus'")  # external (0.70.4)
        g.db().commit()
    anchor.forget()
    assert "app0042" not in anchor.title_index()
    on, _ = _search("Which operating system runs on the node that hosts the VM app0042?")
    assert on[:1] != [docs["vm"]]


def test_ab_keeps_one_arm_per_conversation(monkeypatch):
    monkeypatch.setattr(anchor, "MODE", "ab")
    monkeypatch.setattr(anchor, "SHARE", 0.5)
    arms = {c: anchor.active(c) for c in (f"2026112500{i:02d}" for i in range(60))}
    assert all(anchor.active(c) == a for c, a in arms.items())  # stable
    share = sum(1 for on, _ in arms.values() if on) / len(arms)
    assert 0.25 < share < 0.75 and {a for _, a in arms.values()} == {"ab:on", "ab:off"}
    assert anchor.active(None) == (False, "off")  # no conversation: no arm
    monkeypatch.setattr(anchor, "SHARE", 0.0)
    assert anchor.active("202611250001") == (False, "off")


def test_config_reads_the_switch_safely(tmp_path, monkeypatch):
    import json
    p = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(p))
    config.create_instance("a")
    raw = json.loads(p.read_text())
    for value, share, want in (("on", 0.1, ("on", 0.1)), ("AB", 0.9, ("ab", 0.5)), ("yes", "x", ("off", 0.0)), (None, None, ("off", 0.0))):
        raw.pop("search_anchor", None), raw.pop("search_anchor_share", None)
        if value is not None:
            raw.update(search_anchor=value, search_anchor_share=share)
        p.write_text(json.dumps(raw))
        k = config.load()
        assert (k.search_anchor, k.search_anchor_share) == want, value
