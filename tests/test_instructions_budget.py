"""0.70.6: the instructions fit the client's cut. Claude Code shows only the first 4,096 characters of a server's instructions
(code.claude.com/docs/en/mcp.md); the old instructions were over 6,500 characters, so the rules after LEARN — 'Never learn' included —
and the memory index never reached the model (seen 19.11.2026: '… vi_confirm / vi_refute when yo… [truncated]'). Now: a short core
with search first, the index after it with the rest of the budget, and every detail as an initial skill the core names."""
import json
import threading

import pytest

from vi_mcp import config, knowledge_skills, server, tools
from vi_mcp import memory as g
from vi_mcp.server import INSTRUCTIONS_BUDGET

CLAUDE_CODE_CUT = 4096


def test_the_core_rules_say_search_first_and_never_learn_secrets():
    r = tools.RULES
    assert r.startswith("Rules for the VI")
    assert r.index("SEARCH FIRST") < r.index("LEARN") < r.index("NEVER learn passwords")
    for ref in ("insight:skill-vi-rules", "insight:skill-clingo", "insight:skill-philosophy", "insight:skill-finetune", "vi_capabilities"):
        assert ref in r  # every detail that left the core is named, like a link in a CLAUDE.md
    assert len(r) < 2400


def test_the_full_rules_are_an_initial_skill(gd):
    knowledge_skills.ensure()
    o = g.load(knowledge_skills.object_id("vi-rules"))
    assert o is not None and o.data["content"] == tools.RULES_FULL
    assert "Never learn: passwords, tokens, keys" in o.data["content"] and "Images are their own kind" in o.data["content"]


@pytest.fixture
def srv(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("anna")  # as tests/test_index.py
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], tok
    s.shutdown()
    s.server_close()
    server.finish([s])


def test_instructions_stay_under_the_cut_with_a_full_index(srv):
    from test_http import request
    port, tok = srv
    for i in range(40):  # far more requirements than the index can list: the index must yield, not the rules
        g.new_object("insight", f"The user decided rule number {i}: deploys need a ticket and a named reviewer every time",
                     ["topic:requirement"], {"source": "test"}, instance="anna")
    _, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "t"}}}, tok)
    ins = a["result"]["instructions"]
    assert len(ins) <= INSTRUCTIONS_BUDGET < CLAUDE_CODE_CUT
    seen = ins[:CLAUDE_CODE_CUT]
    assert "SEARCH FIRST" in seen and "NEVER learn passwords" in seen and "[Index]" in seen and "insight:skill-vi-rules" in seen
    assert seen.index("Rules for the VI") < seen.index("[Index]")


def test_the_search_tools_load_upfront_and_fit_the_cut():
    """Claude Code defers MCP tools; vi_recall, vi_object and vi_learn are marked to load at session start (_meta anthropic/alwaysLoad),
    and an upfront tool description is cut at 4,096 characters too."""
    listed = {t["name"]: t for t in tools.listing("anna")}
    for name in tools.ALWAYS_LOAD:
        assert listed[name]["_meta"] == {"anthropic/alwaysLoad": True}
        assert len(listed[name]["description"]) < CLAUDE_CODE_CUT
    assert "_meta" not in listed["vi_sleep"]  # the rest stays deferred
    assert not any("_meta" in t for t in tools.TOOLS)  # the shared definitions are not changed in place
