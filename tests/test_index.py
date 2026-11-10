"""0.38.0: the memory index in the instructions — like a MEMORY.md: pushed, one line per entry, details via vi_object."""
import json
import threading

import pytest

from vi_mcp import config, index, server
from vi_mcp import memory as g

from test_http import request


def _k(text, tags, instance="anna", **kw):
    return g.new_object("erkenntnis", text, tags, {"quelle": "test 10.11.2026"}, instance=instance, **kw)


def test_sections_requirements_proven_and_own(gd):
    req = _k("The user requires: deploys only after explicit approval", ["thema:vorgabe", "thema:deploy"], instance="bert")
    proven = _k("ssh to the build host only with the key file", ["thema:ssh"], instance="bert")
    proven.confirm("ki@carl", "worked", "carl", family="gpt")
    own = _k("Port 8765 is the default of the VI server", ["thema:port"])
    imported = _k("Manual section: how to install NetBox", ["art_wissen:handbuch"])
    imported.confirm("ki@carl", "x", "carl", family="gpt")
    refuted = _k("A wrong statement learned by anna", ["thema:x"])
    refuted.refute("ki@anna", "wrong", "anna")
    private = g.new_object("erkenntnis", "private note of bert only", ["thema:y"], {"quelle": "q"}, instance="bert", visibility="privat")
    s = index.sections("anna")
    assert [o.id for o in s["vorgaben"]] == [req.id]
    assert proven.id in [o.id for o in s["bewaehrt"]] and imported.id not in [o.id for o in s["bewaehrt"]]
    assert [o.id for o in s["hier"]] == [own.id]
    t = index.text("anna")
    assert t.startswith("[Index] Memory index for instance anna, like a MEMORY.md")
    assert f"- [{req.id}] The user requires: deploys only after explicit approval" in t
    for o in (refuted, private, imported):
        assert o.id not in t


def test_internal_only_with_a_token(gd):
    o = _k("Internal requirement: tickets go to the IMIT queue", ["thema:vorgabe"], visibility="intern")
    assert o.id in index.text("anna")
    assert o.id not in index.text(config.OPEN)


def test_bounded_and_the_cut_is_named(gd, monkeypatch):
    for i in range(30):
        _k(f"Requirement number {i}: " + "x" * 200, ["thema:vorgabe"])
    monkeypatch.setattr(index, "MAX_CHARS", 600)
    t = index.text("anna")
    assert len(t) <= 600 + 80 and t.endswith("(index cut at its size limit — vi_recall finds the rest)")
    assert all(len(line) <= index.LINE_CHARS + 40 for line in t.splitlines()[1:])


def test_empty_memory_sends_no_index(gd):
    assert index.text("anna") == ""


def test_images_are_marked(gd):
    from vi_mcp import images
    from test_images import png
    o = g.new_object("bild", "Screenshot of the setup dialog", ["thema:vorgabe"], {"quelle": "q", "bild": images.store(png())}, instance="anna")
    assert f"- [{o.id}] image: Screenshot of the setup dialog" in index.text("anna")


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("anna")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], tok
    s.shutdown()
    s.server_close()
    server.finish([s])


def test_initialize_carries_the_index_after_the_rules(srv):
    port, tok = srv
    o = _k("The user decided: images are their own memory kind", ["thema:vorgabe"])
    _, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "t"}}}, tok)
    ins = a["result"]["instructions"]
    assert "[Index] Memory index for instance anna" in ins and o.id in ins
    assert ins.index("Rules for the VI") < ins.index("[Index]")  # rules first: a client that cuts loses the index, not the rules
