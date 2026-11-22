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
    e = [o for _, o, _g in g.recall("tool:netbox_get_devices kind:experience ok:yes")]
    assert len(e) == 1 and e[0].data["before"]["triggers"][:3] == ["tool:netbox_get_devices", "skill:netbox", "host:web1"]
    # second identical call (other Claude session): from memory → denied with the answer as reason
    outputs = h.process(ev("PreToolUse", "cc-2", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u2"))
    hs = outputs["hookSpecificOutput"]
    assert hs["permissionDecision"] == "deny" and "web1 aktiv" in hs["permissionDecisionReason"]


def test_builtin_tools_never_from_memory(h):
    for uid in ("r1", "r2"):
        outputs = h.process(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid))
        assert outputs is None
        h.process(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid, tool_response="inhalt"))
    assert len(g.recall("tool:Read kind:experience")) == 2 and not g.recall("tool:Read kind:answer")


def test_error_hint_and_own_tools(h):
    h.process(ev("PreToolUse", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1"))
    h.process(ev("PostToolUseFailure", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1", error="Exit 127: x: not found"))
    assert [o.text for _, o, _g in g.recall("tool:Bash ok:no")][0].startswith("Bash(")
    # 0.49.0: a shell hint needs more than the tool in common — here the host
    g.new_object("insight", "web7 hier ohne Proxy-Variablen", ["tool:Bash", "host:web7.example"], {"source": "Test"}, reason="T")
    outputs = h.process(ev("PreToolUse", tool_name="Bash", tool_input={"command": "ssh web7.example uptime"}, tool_use_id="b2"))
    assert "ohne Proxy-Variablen" in outputs["hookSpecificOutput"]["additionalContext"]
    assert h.process(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_status", tool_input={}, tool_use_id="v1")) is None
    assert not g.recall("tool:vi_status")


def test_session_end_and_server_restart(h):
    h.process(ev("PreToolUse", "cc-9", tool_name="Grep", tool_input={"pattern": "a"}, tool_use_id="g1"))
    serial = [o for _, o, _g in g.recall("kind:conversation instance:laptop")][0].data["serial"]
    h.process(ev("SessionEnd", "cc-9", reason="exit"))
    gs = g.load_keyed("conversation", serial)
    assert gs.data["state"] == "ended" and gs.data["without_result"] == 1  # before without after: named
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


def test_feedback_request_per_round_names_each_action(h, monkeypatch):
    # 0.71.0 (replaces the session-wide request of 0.59.0): the ids come from zugriff.shown, one line per hinted action, asked once per
    # round, the server told it asked; English ids too (the 0.59.0 text regex missed every insight: id after 0.67.0)
    from vi_mcp import intuition
    monkeypatch.setattr(intuition, "NUDGE_OFF", 0.0)
    monkeypatch.delenv("VI_MCP_FEEDBACK_NUDGE", raising=False)
    k = g.new_object("insight", "web7 needs no proxy variables", ["tool:Bash", "host:web7.example"], {"source": "Test"}, reason="T")
    out = h.process(ev("PreToolUse", "f1", tool_name="Bash", tool_input={"command": "ssh web7.example uptime"}, tool_use_id="fb1"))
    assert k.id in out["hookSpecificOutput"]["additionalContext"]
    bid = h.read("vorher", "fb1")["vorher_id"]
    assert h.read("vorher", "fb1")["shown"] == [k.id]
    h.process(ev("PostToolUseFailure", "f1", tool_name="Bash", tool_input={"command": "ssh web7.example uptime"}, tool_use_id="fb1",
                 error="Exit 255"))  # asked regardless of the outcome
    h.process(ev("PreToolUse", "f1", tool_name="Glob", tool_input={"pattern": "*"}, tool_use_id="fb2"))  # no hints: not asked
    h.process(ev("PostToolUse", "f1", tool_name="Glob", tool_input={"pattern": "*"}, tool_use_id="fb2", tool_response="x"))
    r = h.process(ev("Stop", "f1"))
    assert r["decision"] == "block" and f"before_id {bid}" in r["reason"] and k.id in r["reason"] and "Glob" not in r["reason"]
    assert "used=[]" in r["reason"] and "reconnect" in r["reason"] and "do not put used ids into helped" in r["reason"]
    e = intuition.experience_for_before("laptop", bid)
    assert e.data.get("feedback_asked")  # the server knows it asked
    assert h.process(ev("Stop", "f1")) is None  # once per round


def test_feedback_request_respects_answer_arm_and_switch(h, monkeypatch):
    from vi_mcp import intuition
    monkeypatch.delenv("VI_MCP_FEEDBACK_NUDGE", raising=False)
    g.new_object("insight", "web8 needs no proxy variables", ["tool:Bash", "host:web8.example"], {"source": "Test"}, reason="T")

    def hinted(session, uid):
        h.process(ev("PreToolUse", session, tool_name="Bash", tool_input={"command": "ssh web8.example uptime"}, tool_use_id=uid))
        h.process(ev("PostToolUse", session, tool_name="Bash", tool_input={"command": "ssh web8.example uptime"}, tool_use_id=uid,
                     tool_response="x"))
        return h.read("vorher", uid)
    monkeypatch.setattr(intuition, "NUDGE_OFF", 0.0)
    hinted("a1", "x1")
    bid = h.read("rueckmeldung", "a1")["pending"][0]["before_id"]
    h.process(ev("PostToolUse", "a1", tool_name="mcp__vi-mcp__vi_feedback", tool_input={"before_id": bid, "used": []}))
    assert h.process(ev("Stop", "a1")) is None  # answered for that action: not asked
    hinted("a2", "x2")
    assert h.process(ev("Stop", "a2", stop_hook_active=True)) is None  # never loops
    monkeypatch.setenv("VI_MCP_FEEDBACK_NUDGE", "0")
    hinted("a3", "x3")
    assert h.process(ev("Stop", "a3")) is None
    monkeypatch.delenv("VI_MCP_FEEDBACK_NUDGE")
    monkeypatch.setattr(intuition, "NUDGE_OFF", 1.0)  # the "off" arm of the A/B test: the hook must not ask either
    hinted("a4", "x4")
    assert h.read("rueckmeldung", "a4") is None and h.process(ev("Stop", "a4")) is None


def test_shown_ids_reads_both_key_generations():
    assert hook.shown_ids({"zugriff": {"shown": ["insight:a"]}}) == ["insight:a"]
    assert hook.shown_ids({"zugriff": {"gezeigt": ["erkenntnis:b"]}}) == ["erkenntnis:b"]  # a server before 0.67.0
    assert hook.shown_ids({"zugriff": {"held_back": True}}) == [] and hook.shown_ids({}) == []


def test_before_vi_learn_the_hook_notes_the_project(h, monkeypatch):
    # 0.61.0: the hook's session knows the working directory, the agent's does not — vi_context right before vi_learn/vi_recall
    called = []
    monkeypatch.setattr(h, "call_tool", lambda s, c, name, args, raw=False: called.append((name, c)) or {})
    assert h.process(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_learn", tool_input={"text": "x"}, cwd="/home/x/cue-print")) is None
    assert called == [("vi_context", "/home/x/cue-print")]
    called.clear()
    h.process(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_object", tool_input={"id": "x"}))
    assert called == []  # only before learning and searching


def test_vi_context_answer_is_plain_text_and_logs_no_error(h):
    # vi_context answers plain text ("project … noted"); parsing it as JSON logged a JSONDecodeError before every vi_learn/vi_recall
    assert h.process(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_recall", tool_input={"filter": "x"}, cwd="/home/x/cue-print")) is None
    log = h.STATE / "hook.log"
    assert not log.exists() or "vi_context" not in log.read_text()


def _transcript(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


def test_session_start_gives_the_first_task_and_can_be_switched_off(monkeypatch):
    # 0.70.12 (user decision 20.11.2026): after start, resume and compaction the agent is told to search the memory first
    monkeypatch.delenv("VI_MCP_FIRST_TASK", raising=False)
    r = hook.process({"hook_event_name": "SessionStart", "session_id": "s1", "source": "compact"})
    assert r["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "vi_recall" in r["hookSpecificOutput"]["additionalContext"] and "status:" in r["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setenv("VI_MCP_FIRST_TASK", "0")
    assert hook.process({"hook_event_name": "SessionStart", "session_id": "s1"}) is None


def test_stop_holds_a_working_round_without_a_status_update_once(tmp_path, monkeypatch):
    # 0.70.12: >= STATUS_MIN tool calls in the round (the VI's own do not count) and no vi_learn key status:… → held once
    monkeypatch.setattr(hook, "STATE", tmp_path / "hook")
    monkeypatch.delenv("VI_MCP_STATUS_DUTY", raising=False)
    user = lambda c: {"type": "user", "message": {"role": "user", "content": c}}
    result = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}
    use = lambda n, i=None: {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": n, "input": i or {}}]}}
    work = [user("old question"), use("Bash")] + [user("new question")] + [r for _ in range(hook.STATUS_MIN) for r in (use("Bash"), result)]
    t = _transcript(tmp_path / "work.jsonl", work)
    r = hook.process({"hook_event_name": "Stop", "session_id": "w1", "transcript_path": t})
    assert r["decision"] == "block" and "status" in r["reason"] and f"{hook.STATUS_MIN} tool calls" in r["reason"]
    assert hook.process({"hook_event_name": "Stop", "session_id": "w1", "transcript_path": t, "stop_hook_active": True}) is None
    done = _transcript(tmp_path / "done.jsonl", work + [use("mcp__vi-mcp__vi_learn", {"key": "status:x", "text": "t"}), result])
    assert hook.process({"hook_event_name": "Stop", "session_id": "w2", "transcript_path": done}) is None
    vi_only = [user("q")] + [r for _ in range(hook.STATUS_MIN) for r in (use("mcp__vi-mcp__vi_recall"), result)]
    assert hook.process({"hook_event_name": "Stop", "session_id": "w3", "transcript_path": _transcript(tmp_path / "vi.jsonl", vi_only)}) is None
    small = [user("q")] + [r for _ in range(hook.STATUS_MIN - 1) for r in (use("Bash"), result)]
    assert hook.process({"hook_event_name": "Stop", "session_id": "w4", "transcript_path": _transcript(tmp_path / "s.jsonl", small)}) is None
    assert hook.process({"hook_event_name": "Stop", "session_id": "w5", "transcript_path": str(tmp_path / "missing.jsonl")}) is None
    monkeypatch.setenv("VI_MCP_STATUS_DUTY", "0")
    assert hook.process({"hook_event_name": "Stop", "session_id": "w6", "transcript_path": t}) is None


def test_stop_carries_status_duty_and_feedback_request_in_one_block(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "STATE", tmp_path / "hook")
    monkeypatch.delenv("VI_MCP_STATUS_DUTY", raising=False)
    monkeypatch.delenv("VI_MCP_FEEDBACK_NUDGE", raising=False)
    monkeypatch.setattr(hook, "report_asked", lambda *a: None)
    hook.note_action("b1", "beef00", "Bash", ["insight:a1", "rule:b2"])
    rows = [{"type": "user", "message": {"content": "q"}}] + [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}] * hook.STATUS_MIN
    r = hook.process({"hook_event_name": "Stop", "session_id": "b1", "transcript_path": _transcript(tmp_path / "b.jsonl", rows)})
    assert r["decision"] == "block" and "status object" in r["reason"] and "before_id beef00" in r["reason"] and "insight:a1" in r["reason"]


def test_signal_feedback_asked_only_for_the_own_session_and_korrektur_still_human_only(h, srv):  # noqa: F811
    import http.client
    port, tok, other = srv
    h.process(ev("PreToolUse", "sg1", tool_name="Glob", tool_input={"pattern": "*"}, tool_use_id="sg"))
    sid = h.read("sitzung", "sg1")["mcp_session_id"]

    def post(token, body):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/signal", body=json.dumps(body), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status
    assert post(tok, {"art": "feedback_asked", "mcp_session_id": sid, "before_ids": ["0123"]}) == 200
    assert post(other, {"art": "feedback_asked", "mcp_session_id": sid, "before_ids": ["0123"]}) == 404  # not its session
    assert post(tok, {"art": "feedback_asked", "mcp_session_id": sid, "before_ids": []}) == 400
    assert post(tok, {"art": "korrektur", "mcp_session_id": sid}) == 403  # the laptop instance is no human instance
