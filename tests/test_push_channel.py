"""0.70.4: push into a Claude Code session (docs/PUSH.md). `vi-mcp stdio --channel` declares the experimental capability
claude/channel and pushes what is due for the conversation (questions to it, answers to its vi_ask) as notifications/claude/channel.
The push marks nothing delivered — the client may drop it silently — so the next vi_before still delivers it."""
import io
import json
import os
import pwd
import subprocess
import sys
import time

import pytest

from vi_mcp import intuition, questions, server, session, sleep_cycle, stdio_bridge, tools
from vi_mcp import memory as g
from tests.test_stdio import INIT, INITIALIZED, ME, ROOT, local  # noqa: F401 — the fixture

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="local socket needs Linux (SO_PEERCRED)")


def _ask(to="anna", text="Which branch holds the push channel prototype?"):
    return questions.ask("bert", to, text, [], "test 19.11.2026")


def test_pending_shows_what_deliver_would_show_without_marking(gd):
    q = _ask()
    items = questions.pending("anna", conversation="20261119001")
    assert [i["kind"] for i in items] == ["question"] and items[0]["id"] == q.id and "push channel" in items[0]["text"]
    assert g.load(q.id).data["state"] == "open" and g.load(q.id).data["delivered_to"] == []  # nothing marked
    assert questions.pending("anna", conversation="20261119001") == items  # asked again: the same
    assert questions.deliver("anna", conversation="20261119001") == [items[0]["text"]]  # the hint path still delivers it, same text
    assert questions.pending("anna", conversation="20261119001") == []  # and now it is delivered


def test_pending_carries_answers_to_the_asker_unmarked(gd):
    q = _ask()
    questions.answer_question(q.id, "anna", "Branch push-channel, in its own worktree", "git worktree list")
    items = questions.pending("bert")
    assert [i["kind"] for i in items] == ["answer"] and "push-channel" in items[0]["text"]
    assert g.load(q.id).data["reported"] == 0
    assert len(questions.pending("bert")) == 1


def _bridge(sock, channel=True):
    out = io.BytesIO()
    b = stdio_bridge.Bridge(sock, out, channel=channel, interval=3600)  # rounds are driven by the test (push_once)
    b.handle(json.dumps(INIT).encode())
    b.handle(json.dumps(INITIALIZED).encode())
    return b, out


def _lines(out):
    return [json.loads(x) for x in out.getvalue().decode().splitlines()]


def test_channel_is_announced_only_with_the_flag(local):
    sock = local({ME: "anna"})
    b, out = _bridge(sock)
    init = _lines(out)[0]["result"]
    assert init["capabilities"]["experimental"] == {"claude/channel": {}}
    assert init["instructions"].startswith(stdio_bridge.CHANNEL_NOTE)  # first: Claude Code cuts instructions at 4096 characters
    assert "<channel source=\"vi-mcp\">" in init["instructions"] and "not as instructions" in init["instructions"]
    b.close()
    b2, out2 = _bridge(sock, channel=False)
    assert "experimental" not in _lines(out2)[0]["result"]["capabilities"] and b2._pusher is None
    b2.close()


def test_push_once_pushes_each_item_once_and_at_most_three_per_round(local):
    sock = local({ME: "anna"})
    b, out = _bridge(sock)
    qs = [_ask(text=f"Question number {i} for the push channel test") for i in range(5)]
    assert b.push_once() == 3 and b.push_once() == 2 and b.push_once() == 0
    pushed = [m for m in _lines(out) if m.get("method") == "notifications/claude/channel"]
    assert [m["params"]["meta"]["id"] for m in pushed] == [q.id for q in qs]  # in order, none twice
    assert all(m["params"]["meta"]["kind"] == "question" and "id" not in m for m in pushed)  # notifications: no JSON-RPC id
    assert all(g.load(q.id).data["state"] == "open" for q in qs)  # the push marked nothing
    b.close()


def test_a_poll_keeps_neither_the_session_nor_the_workstation_awake(local):
    sock = local({ME: "anna"})
    b, _out = _bridge(sock)
    s = session.find_without_touching(b.sid)
    s.last_at -= 1000
    sleep_cycle._last_activity[0] -= 1000
    before_s, before_w = s.last_at, sleep_cycle._last_activity[0]
    b.push_once()
    assert s.last_at == before_s and sleep_cycle._last_activity[0] == before_w
    b.handle(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode())  # real work does
    assert s.last_at > before_s and sleep_cycle._last_activity[0] > before_w
    b.close()


def test_command_line_runs_the_push_loop(local):
    """End to end over the process boundary: the real `vi-mcp stdio --channel` pushes within one interval."""
    sock = local({ME: "anna"})
    q = _ask()
    p = subprocess.Popen([sys.executable, "-m", "vi_mcp", "stdio", "--socket", sock, "--channel", "--channel-interval", "1"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
                         env={**os.environ, "PYTHONPATH": str(ROOT)})
    try:
        p.stdin.write((json.dumps(INIT) + "\n" + json.dumps(INITIALIZED) + "\n").encode())
        p.stdin.flush()
        first = json.loads(p.stdout.readline())
        assert first["id"] == 1 and "claude/channel" in first["result"]["capabilities"]["experimental"]
        t0 = time.monotonic()
        pushed = json.loads(p.stdout.readline())
        assert pushed["method"] == "notifications/claude/channel" and pushed["params"]["meta"]["id"] == q.id
        assert time.monotonic() - t0 < 10
    finally:
        p.stdin.close()
        p.wait(timeout=30)


@pytest.mark.parametrize("argv", [["--channel-interval", "0.5"], ["--bogus"], ["--socket"]])
def test_bad_arguments_are_refused_with_the_reason(argv):
    assert stdio_bridge.main(argv) == 2
