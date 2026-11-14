"""The Python package clingo-object (0.63.0): real Python classes and expressions over VI memory objects, compiled to the notation the
server runs — the same text locally (clingo Python API) and on the server, so the same answers (the user, 13.11.2026: consistent with the
clingo Python package, developed further in Python)."""
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("clingo")

from clingo_object import ExprError, Obj, Program, VIObject, Var, linked, never, propose_tag, rel, soft  # noqa: E402
from vi_mcp import logic, tools  # noqa: E402
from vi_mcp import memory as g  # noqa: E402


class ServerData:
    """The memory side as the server sees it — what clingo_object.Memory fetches over vi_logic action=objects."""

    def __init__(self, viewer=None):
        self.viewer = viewer

    def objects(self, filters, edges=True):
        return logic.object_data(filters, self.viewer, edges=edges)


class Knowledge(VIObject):
    def stale(self):
        return (self.mode == "test") & (self.age > 90)


class Insight(Knowledge):
    kind = "erkenntnis"


class Skill(Knowledge):
    kind = "skill"

    def stale(self):
        return (self.mode == "test") & (self.age > 30)

    def risky(self):
        E = Obj("E")
        return self.stale() & linked(self, E) & (E.kind == "erkenntnis")


def _aged(oid, kind, days, mode="test"):
    o = g.new_object(kind, f"{oid} text", ["thema:oo"], {"quelle": "t"}, reason="T", oid=oid, mode=mode, link=False)
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), oid))
        g.db().commit()
    return o


def _program():
    O = Obj("O")
    return Program(Knowledge, Insight, Skill,
                   rel.review(O) <= O.where("thema:oo") & O.stale(),
                   rel.warn(O) <= O.where("thema:oo") & O.risky())


def test_expressions_build_the_notation():
    O, H = Obj("O"), Var("H")
    r = rel.in_dmz(H) <= O.where("zone:dmz") & (O.host == H) & ~(O.mode == "test") & (O.age >= 3)
    assert r.notation() == 'in_dmz(H) <= (O in objects("zone:dmz")) & (O.host == H) & ~(O.mode == "test") & (O.age >= 3)'
    assert never(rel.a(H) & rel.b(H)).notation() == "never(a(H) & b(H))"
    assert soft(rel.flies(H) <= rel.bird(H), 0.9).notation() == "soft(flies(H) <= bird(H), 0.9)"
    assert (-rel.allowed("x")).notation() == '-allowed("x")'
    assert (propose_tag(O, "status", "stale") <= O.where("art:skill")).notation() == 'propose(tag(O, "status", "stale")) <= (O in objects("art:skill"))'


def test_classes_compile_to_flat_rules_by_python_mro():
    text = _program().notation()
    assert 'stale(Self) <= (Self in objects("art:erkenntnis")) & (Self.mode == "test") & (Self.age > 90)' in text
    assert 'stale(Self) <= (Self in objects("art:skill")) & (Self.mode == "test") & (Self.age > 30)' in text
    assert "class" not in text and "def " not in text  # the server never sees Python
    logic.translate(text)  # and the server accepts it


def test_local_and_server_give_the_same_answers(gd):
    _aged("erkenntnis:old", "erkenntnis", 120)
    _aged("erkenntnis:young", "erkenntnis", 60)
    s = _aged("skill:mid", "skill", 60)
    _aged("skill:fresh", "skill", 10)
    s.link("erkenntnis:old", "uses")
    prog = _program()
    local = prog.check(ServerData())
    server = logic.check(prog.notation())
    assert local["folgerungen"] == server["folgerungen"]
    assert {'review("erkenntnis:old")', 'review("skill:mid")', 'warn("skill:mid")'} <= set(local["folgerungen"])
    assert 'review("erkenntnis:young")' not in local["folgerungen"] and 'review("skill:fresh")' not in local["folgerungen"]
    assert prog.ask(ServerData(), ['review("skill:fresh")'])['review("skill:fresh")'] == "not_derived"
    out = tools.call_tool("vi_logic", {"source": prog.notation()}, "a", False)  # the same text through the MCP tool
    assert "review" in out


def test_proposals_from_a_python_program_go_through_the_server(gd):
    _aged("skill:mid", "skill", 60)
    S = Obj("S")
    prog = Program(Knowledge, Skill, propose_tag(S, "status", "stale") <= S.where("art:skill") & S.stale())
    assert prog.check(ServerData())["vorschlaege"][0]["ziel"] == "skill:mid"
    out = tools.call_tool("vi_logic", {"action": "propose", "source": prog.notation()}, "a", False)
    assert "held for review: vorschlag:" in out


@pytest.mark.parametrize("build, why", [
    (lambda: rel.p(Var("H")) <= (Obj("O").host == Var("H")) & True, "cannot be joined"),
    (lambda: Obj("O").host != "x", "for \"not\" write"),
    (lambda: ~(Obj("O").age > 3), "opposite comparison"),
    (lambda: Var("h"), "capital"),
    (lambda: rel.objects(Var("H")), "word of the dialect"),
    (lambda: bool(Obj("O").where("art:skill")), "no truth value"),
])
def test_mistakes_are_named_where_they_are_made(build, why):
    with pytest.raises(ExprError, match=why):
        build()


def test_a_method_must_return_a_condition():
    class Bad(VIObject):
        kind = "skill"

        def broken(self):
            return 42
    with pytest.raises(ExprError, match="returns int"):
        Program(Bad).notation()


def test_only_the_classes_of_the_program_count():
    """A subclass the program was not given never joins silently: Knowledge alone has no kinds, so its method applies to nothing."""
    assert "stale" not in Program(Knowledge).notation()
    assert "art:skill" not in Program(Knowledge, Insight).notation()


# ── B3: the client against a real server (tests/test_http.py's fixture) ──────

from tests.test_http import srv  # noqa: E402,F401  — the fixture: a real vi-mcp on a random port


def test_memory_client_against_a_real_server(srv, tmp_path, monkeypatch):
    from clingo_object import Memory, ServerError
    port, tok_a, _tok_b = srv
    tf = tmp_path / "token"
    tf.write_text(tok_a)
    mem = Memory(f"http://127.0.0.1:{port}/mcp", tf)
    assert tok_a not in repr(mem)
    g.new_object("erkenntnis", "gate1 in the DMZ", ["host:gate1", "zone:dmz"], {"quelle": "t"}, reason="T", oid="erkenntnis:gate1", link=False)
    g.new_object("skill", "old skill", ["thema:oo"], {"quelle": "t"}, reason="T", oid="skill:x", mode="test", link=False)
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE id = 'skill:x'", ((datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),))
        g.db().commit()
    data = mem.objects(["zone:dmz"])
    assert [o["id"] for o in data["objects"]] == ["erkenntnis:gate1"]
    prog = _program()
    local = prog.check(mem)  # objects fetched over MCP, solved here
    assert 'review("skill:x")' in local["folgerungen"]
    assert 'review("skill:x")' in prog.check_on_server(mem)  # the same text on the server
    assert "saved" in prog.save(mem, "oo-review", "stale knowledge to review")
    assert "booked as right" in prog.rate(mem, 'review("skill:x")', True)
    with pytest.raises(ServerError, match="initialize: HTTP 401|token refused"):
        bad = tmp_path / "bad"
        bad.write_text("wrong-token")
        Memory(f"http://127.0.0.1:{port}/mcp", bad).objects(["zone:dmz"])


def test_memory_finds_url_and_token_like_the_hook(tmp_path, monkeypatch):
    from clingo_object import client
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("VI_MCP_URL", raising=False)
    monkeypatch.delenv("VI_MCP_TOKEN_FILE", raising=False)
    (tmp_path / ".config" / "vi-mcp").mkdir(parents=True)
    (tmp_path / ".config" / "vi-mcp" / "hook.json").write_text('{"url": "https://vi.example/mcp", "token_file": "~/t"}')
    url, tf = client._config()
    assert url == "https://vi.example/mcp" and tf == tmp_path / "t"
    monkeypatch.setenv("VI_MCP_URL", "http://127.0.0.1:9/mcp")
    assert client._config()[0] == "http://127.0.0.1:9/mcp"  # the environment wins


def test_the_wheel_installs_and_states_the_minimum_clingo(tmp_path):
    """Packaging: a pure-Python wheel built with the standard library; pip installs it (--no-deps, offline) and it imports alone."""
    import subprocess
    import sys
    import zipfile
    from clingo_object import notation
    whl = subprocess.run([sys.executable, "deploy/clingo-object/build_wheel.py", str(tmp_path)], capture_output=True, text=True, check=True)
    path = whl.stdout.strip()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        meta = z.read(next(n for n in names if n.endswith("METADATA"))).decode()
    assert "clingo_object/notation.py" in names and not any(n.startswith("vi_mcp/") for n in names)
    assert f"Requires-Dist: clingo>={notation.CLINGO_MIN}" in meta and "Name: clingo-object" in meta
    target = tmp_path / "site"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--quiet", "--target", str(target), path], check=True)
    out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(target)!r}); import clingo_object as c; "
                          "print(c.__file__, 'vi_mcp' in sys.modules)"], capture_output=True, text=True, check=True).stdout
    assert out.startswith(str(target)) and out.strip().endswith("False")


# ── the agent: write, check, correct (construct-and-check loop) ───────────────

class ServerCheck(ServerData):
    """memory.check as the server answers it (the text of vi_logic check)."""

    def check(self, source):
        try:
            return "\n".join(logic.lines(logic.check(source, viewer=self.viewer)))
        except logic.LogicError as e:
            raise RuntimeError(f"notation: {e}") from e


def test_the_agent_corrects_its_program_from_the_solver(gd):
    from clingo_object import agent
    g.new_object("erkenntnis", "gate1 in the DMZ", ["host:gate1", "netz:dmz"], {"quelle": "t"}, reason="T", oid="erkenntnis:g1", link=False)
    g.new_object("erkenntnis", "web1 internal", ["host:web1", "netz:intern"], {"quelle": "t"}, reason="T", oid="erkenntnis:w1", link=False)
    replies = iter([
        "```logic\nans(H) <= O in objects(\"netz:dmz\") & (O.host == H)\n```",              # & binds tighter: refused
        "```logic\nans(H) <= (O in objects(\"netz:dmz\")) & (O.hosts == H)\n```",            # wrong kind: solves, no ans
        "```logic\nans(H) <= (O in objects(\"netz:dmz\")) & (O.host == H)\n```",
    ])
    seen = []

    def llm(messages):
        seen.append(messages[-1]["content"])
        return next(replies)
    r = agent.solve("Which hosts are in the DMZ?", ServerCheck(), llm)
    assert r["state"] == "answered" and r["answer"] == ['ans("gate1")'] and r["rounds"] == 3
    assert "refused" in seen[1] and "parentheses" in seen[1] and "no ans" in seen[2]


def test_the_agent_says_when_it_found_nothing(gd):
    from clingo_object import agent
    r = agent.solve("?", ServerCheck(), lambda m: "```logic\nans(X) <= p(X)\n```", max_rounds=2)
    assert r["state"] == "empty" and r["answer"] == [] and r["rounds"] == 2


def test_the_agent_never_sends_max_tokens(monkeypatch):
    import json as _json
    from clingo_object import agent
    sent = []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    monkeypatch.setattr(agent.urllib.request, "urlopen", lambda req, timeout=0: sent.append(_json.loads(req.data)) or R())
    assert agent.openai_chat("http://127.0.0.1:1/v1/chat/completions", "m")([{"role": "user", "content": "x"}]) == "ok"
    assert "max_tokens" not in sent[0] and "n_predict" not in sent[0] and sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_the_agent_reads_the_vocabulary_from_the_server(gd):
    from clingo_object import agent

    class Mem:
        def call(self, tool, args):
            return tools.call_tool(tool, args, "a", False)
    g.new_object("erkenntnis", "gate1 in the DMZ", ["host:gate1", "netz:dmz"], {"quelle": "t"}, reason="T", oid="erkenntnis:g1", link=False)
    v = agent.vocabulary(Mem())
    assert "- netz: dmz" in v and "- host: gate1" in v and "instanz" not in v


def test_the_agent_end_to_end_over_a_real_server(srv, tmp_path):
    """The path of `python3 -m clingo_object.agent`: Memory over HTTP (objects, vocabulary), a scripted language model, an answer."""
    from clingo_object import Memory, agent
    port, tok_a, _b = srv
    tf = tmp_path / "token"
    tf.write_text(tok_a)
    mem = Memory(f"http://127.0.0.1:{port}/mcp", tf)
    g.new_object("erkenntnis", "gate1 in the DMZ", ["host:gate1", "netz:dmz"], {"quelle": "t"}, reason="T", oid="erkenntnis:g1", link=False)
    voc = agent.vocabulary(mem)
    assert "- netz: dmz" in voc
    seen = []

    def llm(messages):
        seen.append(messages[0]["content"])
        return '```logic\nans(H) <= (O in objects("netz:dmz")) & (O.host == H)\n```'
    r = agent.solve("Which hosts are in the DMZ?", mem, llm, vocabulary=voc)
    assert r["state"] == "answered" and r["answer"] == ['ans("gate1")'] and "- netz: dmz" in seen[0]


def test_memory_reads_the_hook_command_of_claude_code(tmp_path, monkeypatch):
    """0.63.1, found on the first live test against production: on Linux `vi-mcp setup` writes URL and token file into the hook
    command in ~/.claude/settings.json — there is no hook.json, and the client fell back to 127.0.0.1."""
    import json as _json
    from clingo_object import client
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("VI_MCP_URL", raising=False)
    monkeypatch.delenv("VI_MCP_TOKEN_FILE", raising=False)
    (tmp_path / ".claude").mkdir()
    cmd = "VI_MCP_URL=https://vi.example/vi-mcp/mcp VI_MCP_TOKEN_FILE=$HOME/.config/vi-mcp/token-claude python3 -I /usr/share/vi-mcp/hook/vi_hook.py"
    (tmp_path / ".claude" / "settings.json").write_text(_json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": cmd, "timeout": 5}]}]}}))
    url, tf = client._config()
    assert url == "https://vi.example/vi-mcp/mcp" and tf == tmp_path / ".config" / "vi-mcp" / "token-claude"
