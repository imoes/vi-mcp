"""0.30.0: switching visibility between shared and internal — dry run first, own objects or release right, private never, with history."""
import sys

import pytest

from vi_mcp import tools
from vi_mcp import memory as g


def _manual(text, instance="a", visibility="geteilt"):
    return g.new_object("erkenntnis", text, ["art_wissen:handbuch", "skill:x"], {"quelle": "SKILL.md"}, reason="T", instance=instance,
                        visibility=visibility)


def test_dry_run_then_apply_with_history(gd):
    own, other = _manual("Handbuch x: Abschnitt 1"), _manual("Handbuch x: Abschnitt 2", instance="b")
    done = _manual("Handbuch x: Abschnitt 3", visibility="intern")
    mine_private = _manual("Handbuch x: privat", visibility="privat")
    out = tools.call_tool("vi_set_visibility", {"filter": "art_wissen:handbuch", "visibility": "internal", "reason": "company host names"}, "a", False)
    assert "4 object(s)" in out and "1 would be switched to internal" in out and "1 already internal" in out
    assert "1 private (never switched)" in out and "1 of other instances (need the release right)" in out and "dry run" in out
    assert g.load(own.id).visibility == "geteilt"  # nothing changed
    out = tools.call_tool("vi_set_visibility", {"filter": "art_wissen:handbuch", "visibility": "internal", "reason": "company host names",
                                                "apply": True}, "a", False)
    assert "1 switched to internal" in out and "vi_net_forget" in out
    o = g.load(own.id)
    assert o.visibility == "intern" and o.changes[-1]["was"] == "visibility geteilt → intern" and o.changes[-1]["grund"] == "company host names"
    assert g.load(other.id).visibility == "geteilt" and g.load(mine_private.id).visibility == "privat" and g.load(done.id).visibility == "intern"
    # with the release right also objects of other instances
    out = tools.call_tool("vi_set_visibility", {"filter": "art_wissen:handbuch", "visibility": "internal", "reason": "operator", "apply": True},
                          "a", False, True)
    assert "1 switched to internal" in out and g.load(other.id).visibility == "intern"


def test_refusals_name_their_reason(gd):
    with pytest.raises(tools.Rejected, match="kind:value"):
        tools.call_tool("vi_set_visibility", {"filter": "handbuch", "visibility": "internal", "reason": "x"}, "a", False)
    with pytest.raises(tools.Rejected, match="shared or internal"):
        tools.call_tool("vi_set_visibility", {"filter": "skill:x", "visibility": "private", "reason": "x"}, "a", False)
    with pytest.raises(tools.Rejected, match="reason"):
        tools.call_tool("vi_set_visibility", {"filter": "skill:x", "visibility": "internal", "reason": " "}, "a", False)
    p = _manual("privat", visibility="privat")
    with pytest.raises(ValueError, match="stays with its instance"):
        g.set_visibility(p, "intern", "admin", "x")


def test_internal_is_hidden_from_open_access(gd):
    o = _manual("Handbuch x: intern")
    g.set_visibility(o, "intern", "admin", "company knowledge")
    assert not g.visible_to(g.load(o.id), g.OPEN_INSTANCE) and g.visible_to(g.load(o.id), "b")


def test_cli_goes_through_the_running_service(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("vi_mcp.__main__", Path(tools.__file__).with_name("__main__.py"))
    main = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", ["vi-mcp"])
    with pytest.raises(SystemExit):  # the module ends with sys.exit(_cli(...)); its namespace stays usable
        spec.loader.exec_module(main)
    calls = []
    monkeypatch.setattr(main, "_local_tool", lambda tool, a: calls.append((tool, a)) or 0)
    assert main._cli(["visibility", "art_wissen:handbuch", "internal", "company host names"]) == 0
    assert main._cli(["visibility", "art_wissen:handbuch", "internal", "company host names", "--apply"]) == 0
    assert calls == [("vi_set_visibility", {"filter": "art_wissen:handbuch", "visibility": "internal", "reason": "company host names", "apply": False}),
                     ("vi_set_visibility", {"filter": "art_wissen:handbuch", "visibility": "internal", "reason": "company host names", "apply": True})]
    assert main._cli(["visibility", "art_wissen:handbuch", "private", "x"]) == 2  # refused, usage shown
