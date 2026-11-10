"""0.33.0 (Condorcet's independence condition): confirmations and refutations count per independent line — one per model family,
none from the object's own source. Instances without a declared family count as their own line (as before)."""
import json

import pytest

from vi_mcp import config, tools
from vi_mcp import memory as g


def _fact(src="free -m on web1, 10.11. 14:00"):
    return g.new_object("erkenntnis", "Dienst y braucht 2 GB RAM", ["thema:y"], {"quelle": src}, reason="T", instance="a")


def test_one_family_counts_once(gd):
    o = _fact()
    g.load(o.id).confirm("ki@b", "bei mir auch", "b", family="claude")
    g.load(o.id).confirm("ki@c", "bei mir auch", "c", family="claude")
    assert g.load(o.id).foreign_confirmations() == 1 and g.load(o.id).independent_lines() == {"claude"}
    g.load(o.id).confirm("ki@d", "gemessen", "d", family="qwen")
    assert g.load(o.id).foreign_confirmations() == 2


def test_same_source_is_no_independent_line(gd):
    o = _fact()
    g.load(o.id).confirm("ki@b", "steht so in der Quelle", "b", family="gpt", source="Free -m on web1, 10.11. 14:00.")
    o2 = g.load(o.id)
    assert o2.foreign_confirmations() == 0 and "same source as the object" in o2.changes[-1]["was"]
    g.load(o.id).confirm("ki@b", "selbst gemessen", "b", family="gpt", source="free -m on web2, 10.11. 16:00")
    assert g.load(o.id).foreign_confirmations() == 1


def test_undeclared_and_legacy_count_per_instance(gd):
    o = _fact()
    o.data["bestaetigt_von"] = {"x": 1, "y": 2}  # stored before 0.33.0, no family known
    g.save(o)
    assert g.load(o.id).foreign_confirmations() == 2
    g.load(o.id).confirm("ki@z", "ok", "z")  # no family declared → its own line
    assert g.load(o.id).independent_lines() == {"x", "y", "z"}


def test_refutation_needs_two_families(gd):
    o = _fact()
    g.load(o.id).refute("ki@b", "bei mir 4 GB", "b", family="claude")
    g.load(o.id).refute("ki@c", "bei mir auch 4 GB", "c", family="claude")
    assert g.load(o.id).mode == "strittig"  # two instances of one model: still only disputed
    g.load(o.id).refute("ki@d", "gemessen: 4 GB", "d", family="qwen")
    assert g.load(o.id).mode == "widerlegt"


def test_tool_passes_family_and_source(gd):
    o = _fact()
    tools.call_tool("vi_confirm", {"id": o.id, "reason": "geprüft", "source": "free -m on web3"}, "b", False, False, "claude")
    tools.call_tool("vi_confirm", {"id": o.id, "reason": "geprüft"}, "c", False, False, "claude")
    out = tools.call_tool("vi_object", {"id": o.id}, "a", False)
    assert "independent lines: 1" in out
    e = g.load(o.id).data["bestaetigungen"]
    assert [x["familie"] for x in e] == ["claude", "claude"] and e[0]["quelle"] == "free -m on web3"


def test_family_is_declared_in_the_configuration(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instanzen": {"claude-code": {"token_sha256": "0" * 64}}}))
    assert config.set_family("claude-code", "claude", cfg) is None
    assert config.load(cfg).instances["claude-code"].family == "claude"
    assert config.set_family("claude-code", None, cfg) == "claude" and config.load(cfg).instances["claude-code"].family is None
    with pytest.raises(ValueError, match="unknown"):
        config.set_family("nobody", "gpt", cfg)
    with pytest.raises(ValueError, match="letters"):
        config.set_family("claude-code", "gpt 5", cfg)
