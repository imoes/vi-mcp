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

    def objects(self, filters):
        return logic.object_data(filters, self.viewer)


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
