"""Block 4: Claude Code hook against a real vi-mcp server (hook events as JSON like from Claude Code)."""
import importlib.util
import json
from pathlib import Path

import pytest

from vi_mcp import memory as g

from test_http import srv  # noqa: F401 — Fixture: echter Server auf Zufallsport

_spec = importlib.util.spec_from_file_location("vi_hook", Path(__file__).parent.parent / "hook" / "vi_hook.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


@pytest.fixture()
def h(srv, tmp_path, monkeypatch):  # noqa: F811
    port, tok, _ = srv
    (tmp_path / "token").write_text(tok + "\n")
    monkeypatch.setattr(hook, "URL", f"http://127.0.0.1:{port}/mcp")
    monkeypatch.setattr(hook, "TOKEN_FILE", tmp_path / "token")
    monkeypatch.setattr(hook, "STATE", tmp_path / "hook")
    return hook


def ev(name, session="cc-1", **kw):
    return {"hook_event_name": name, "session_id": session, "cwd": "/tmp", **kw}


def test_tool_name_and_read_only():
    assert hook.tool_parts("mcp__skills__netbox_get_devices") == ("netbox_get_devices", "skills")
    assert hook.tool_parts("Bash") == ("Bash", None)
    assert hook.read_only_hint("Read") is False and hook.read_only_hint("mcp__x__y") is None


def test_before_after_and_remembered_answer(h):
    t = "mcp__skills__netbox_get_devices"
    assert h.process(ev("PreToolUse", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u1")) is None
    h.process(ev("PostToolUse", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u1",
                    tool_response={"content": [{"type": "text", "text": "web1 aktiv"}]}))
    e = [o for _, o, _g in g.recall("tool:netbox_get_devices art:erfahrung ok:ja")]
    assert len(e) == 1 and e[0].data["vorher"]["reize"][:3] == ["tool:netbox_get_devices", "skill:netbox", "host:web1"]
    # second identical call (other Claude session): from memory → denied with the answer as reason
    outputs = h.process(ev("PreToolUse", "cc-2", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u2"))
    hs = outputs["hookSpecificOutput"]
    assert hs["permissionDecision"] == "deny" and "web1 aktiv" in hs["permissionDecisionReason"]


def test_builtin_tools_never_from_memory(h):
    for uid in ("r1", "r2"):
        outputs = h.process(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid))
        assert outputs is None
        h.process(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid, tool_response="inhalt"))
    assert len(g.recall("tool:Read art:erfahrung")) == 2 and not g.recall("tool:Read art:antwort")


def test_error_hint_and_own_tools(h):
    h.process(ev("PreToolUse", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1"))
    h.process(ev("PostToolUseFailure", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1", error="Exit 127: x: not found"))
    assert [o.text for _, o, _g in g.recall("tool:Bash ok:nein")][0].startswith("Bash(")
    # 0.49.0: a shell hint needs more than the tool in common — here the host
    g.new_object("erkenntnis", "web7 hier ohne Proxy-Variablen", ["tool:Bash", "host:web7.example"], {"quelle": "Test"}, reason="T")
    outputs = h.process(ev("PreToolUse", tool_name="Bash", tool_input={"command": "ssh web7.example uptime"}, tool_use_id="b2"))
    assert "ohne Proxy-Variablen" in outputs["hookSpecificOutput"]["additionalContext"]
    assert h.process(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_status", tool_input={}, tool_use_id="v1")) is None
    assert not g.recall("tool:vi_status")


def test_session_end_and_server_restart(h):
    h.process(ev("PreToolUse", "cc-9", tool_name="Grep", tool_input={"pattern": "a"}, tool_use_id="g1"))
    serial = [o for _, o, _g in g.recall("art:gespraech instanz:laptop")][0].data["serial"]
    h.process(ev("SessionEnd", "cc-9", reason="exit"))
    gs = g.load(f"gespraech:{serial}")
    assert gs.data["zustand"] == "beendet" and gs.data["ohne_ergebnis"] == 1  # before without after: named
    # state file points to an unknown session (server restarted) → hook registers again
    h.write("sitzung", "cc-10", {"mcp_session_id": "veraltet"})
    assert h.process(ev("PreToolUse", "cc-10", tool_name="Glob", tool_input={"pattern": "*"}, tool_use_id="g2")) is None
    assert h.read("sitzung", "cc-10")["mcp_session_id"] != "veraltet"


def test_outage_runs_through(h, monkeypatch, capsys):
    monkeypatch.setattr(h, "URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(ev("PreToolUse", tool_name="Bash", tool_input={}))))
    assert h.main() == 0
    assert capsys.readouterr().out == ""
    assert "continuing without memory" in (h.STATE / "hook.log").read_text()


def test_masking_and_truncation():
    a = hook.sanitize({"command": "sshpass -p geheim1 ssh x; curl -H 'Authorization: Bearer abc123' https://u:pw2@h/ ; PASSWORD=xyz; curl -u a:b9 h", "n": 3, "l": ["token=t0k"]}, 300)
    for secret in ("geheim1", "abc123", "pw2", "xyz", "b9", "t0k"):
        assert secret not in json.dumps(a), secret
    assert a["n"] == 3 and "ssh x" in a["command"]
    assert len(hook.sanitize({"content": "x" * 5000}, 300)["content"]) == 300
    assert hook.read_only_hint("mcp__skills__pwdepot_search_entries") is False and hook.read_only_hint("mcp__skills__netbox_get_vms") is None


def test_result_only_for_mcp(h, monkeypatch):
    sent = {}
    real = h.call_tool

    def spy(s, c, name, args):
        sent[(name, args["tool"])] = args
        return real(s, c, name, args)
    monkeypatch.setattr(h, "call_tool", spy)
    for tool, uid in (("Read", "e1"), ("mcp__skills__netbox_get_vms", "e2"), ("mcp__skills__pwdepot_search_entries", "e3")):
        h.process(ev("PreToolUse", tool_name=tool, tool_input={"q": uid}, tool_use_id=uid))
        h.process(ev("PostToolUse", tool_name=tool, tool_input={"q": uid}, tool_use_id=uid, tool_response="INHALT"))
    assert "result" not in sent[("vi_after", "Read")]
    assert "result" not in sent[("vi_after", "pwdepot_search_entries")]
    assert sent[("vi_after", "netbox_get_vms")]["result"] == "INHALT"
    assert h.process(ev("PreToolUse", tool_name="mcp__skills__vi_status", tool_input={}, tool_use_id="v2")) is None


def test_feedback_request_once_at_stop(tmp_path, monkeypatch):
    # 0.59.0: ≥ FEEDBACK_MIN hints shown and no feedback → the turn is held once with a request; never twice, never after feedback
    monkeypatch.setattr(hook, "STATE", tmp_path / "hook")
    monkeypatch.delenv("VI_MCP_FEEDBACK_NUDGE", raising=False)
    hook.note_hints("s1", ["Learned [erkenntnis:aaa111] (from x, unmeasured): …", "Rule [regel:bbb222] …", "Skill \"x\" [skill:ccc333]"])
    r = hook.process({"hook_event_name": "Stop", "session_id": "s1"})
    assert r["decision"] == "block" and "erkenntnis:aaa111" in r["reason"] and "vi_feedback" in r["reason"]
    assert hook.process({"hook_event_name": "Stop", "session_id": "s1"}) is None  # asked once
    hook.note_hints("s2", ["[erkenntnis:a1] [regel:b2] [skill:c3]"])
    hook.process({"hook_event_name": "PostToolUse", "session_id": "s2", "tool_name": "mcp__vi-mcp__vi_feedback", "tool_input": {}})
    assert hook.process({"hook_event_name": "Stop", "session_id": "s2"}) is None  # feedback given
    hook.note_hints("s3", ["[erkenntnis:a1]"])
    assert hook.process({"hook_event_name": "Stop", "session_id": "s3"}) is None  # too few hints
    hook.note_hints("s4", ["[erkenntnis:a1] [regel:b2] [skill:c3]"])
    assert hook.process({"hook_event_name": "Stop", "session_id": "s4", "stop_hook_active": True}) is None  # never loops
    monkeypatch.setenv("VI_MCP_FEEDBACK_NUDGE", "0")
    hook.note_hints("s5", ["[erkenntnis:a1] [regel:b2] [skill:c3]"])
    assert hook.process({"hook_event_name": "Stop", "session_id": "s5"}) is None
