"""The logic layer (0.62.0): Python-like notation → clingo, four-valued answers, reported violations, rules with learned weights."""
import pytest

pytest.importorskip("clingo")

from vi_mcp import logic  # noqa: E402

DMZ = '''zone("gate1", "dmz")
zone("web1", "intern")
planned(run("freeipa", "gate1"))
forbidden(run(R, H)) <= zone(H, "dmz") & planned(run(R, H))
never(planned(A) & forbidden(A))'''

BIRDS = '''bird("tweety")
bird("pingu")
penguin("pingu")
soft(flies(X) <= bird(X), 0.9)
-flies(X) <= penguin(X)'''


def test_violated_constraint_is_reported_with_number_and_line():
    r = logic.check(DMZ)
    assert r["zustand"] == "verletzt"
    assert r["verletzt"] == [{"nr": 5, "zeile": 5, "never": "never(planned(A) & forbidden(A))"}]
    assert 'forbidden(run("freeipa","gate1"))' in r["folgerungen"]
    assert r["evidenz"] == "inferred"
    assert not any(a.startswith("vi__") for a in r["folgerungen"])


def test_satisfied_when_nothing_is_planned_in_the_dmz():
    r = logic.check(DMZ.replace('planned(run("freeipa", "gate1"))', 'planned(run("freeipa", "web1"))'))
    assert r["zustand"] == "erfuellt" and r["verletzt"] == []


def test_answers_true_false_unknown_not_derived():
    prog = DMZ + '\nprod("web1")\nobligatory(backup(H)) <= prod(H)\ndone(backup("web1"))\n-reachable("gate1")'
    a = logic.ask(prog, ['forbidden(run("freeipa","gate1"))', 'reachable("gate1")', 'zone("web1","dmz")', 'violation(backup("web1"))',
                         'colour("web1")'])
    assert a['forbidden(run("freeipa","gate1"))'] == "true"
    assert a['reachable("gate1")'] == "false"
    assert a['zone("web1","dmz")'] == "not_derived"  # zone is defined, this instance does not follow
    assert a['violation(backup("web1"))'] == "not_derived"
    assert a['colour("web1")'] == "unknown"  # the program says nothing about colour


def test_deontic_violation_and_norm_conflict():
    prog = 'prod("db1")\nobligatory(backup(H)) <= prod(H)\nforbidden(backup("db1"))'
    r = logic.check(prog)
    assert r["zustand"] == "verletzt"
    assert r["normkonflikte"] == ['conflict(norm,backup("db1"))']
    assert logic.ask(prog, ['violation(backup("db1"))'])['violation(backup("db1"))'] == "true"


def test_choice_is_undetermined():
    assert logic.ask("a <= ~b\nb <= ~a", ["a", "b"]) == {"a": "undetermined", "b": "undetermined"}


def test_contradiction_is_named_not_empty():
    r = logic.check('p("a")\n-p("a")')
    assert r["zustand"] == "widerspruch" and r["widersprueche"] == ['p("a")']
    assert logic.ask('p("a")\n-p("a")', ['p("a")'])['p("a")'] == "both"


@pytest.mark.parametrize("bad", [
    "import os", "__import__('os')", "x = 1", "(lambda: 1)()", "Zone('a')", "os.system('x')", "never(a) <= b",
    "p(1.5)", "p(True)", "vi__unsat(1)", "p(neg__x)", "p(x) <= q(x) | r(x)", "p(X) <= q(X) & X < 3", "p(k=1)", "soft(p, 2)", "soft(never(a))",
    "a <= b <= c"])
def test_anything_outside_the_notation_is_refused(bad):
    with pytest.raises(logic.LogicError):
        logic.translate(bad)


def test_comments_and_directives_never_reach_clingo():
    program, stmts = logic.translate('#script (python)\nzone("a", "b")  # a comment\n')
    assert "#" not in program and "script" not in program
    assert len(stmts) == 1
    program, _ = logic.translate('p("#script (python) import os #end.")')
    assert program.splitlines()[0] == 'p("#script (python) import os #end.").'  # inside a string it is data


def test_size_limits():
    with pytest.raises(logic.LogicError):
        logic.translate("a\n" * (logic.MAX_STATEMENTS + 1))
    with pytest.raises(logic.LogicError):
        logic.translate("p(" * 40 + "a" + ")" * 40)


def test_timeout_is_a_named_state(monkeypatch):
    monkeypatch.setattr(logic, "TIMEOUT_S", 0.001)
    holes = "\n".join(f"hole({h})" for h in range(1, 12)) + "\n" + "\n".join(f"pigeon({p})" for p in range(1, 13))
    pigeonhole = holes + """
in_(P, H) <= pigeon(P) & hole(H) & ~out(P, H)
out(P, H) <= pigeon(P) & hole(H) & ~in_(P, H)
bad <= in_(P, H) & in_(Q, H) & (P < Q)
has(P) <= in_(P, H)
bad <= pigeon(P) & ~has(P)
-bad"""
    assert logic.check(pigeonhole)["zustand"] == "zeitlimit"


def test_model_limit_is_said_not_hidden():
    r = logic.check("\n".join(f"q({i}) <= ~nq({i})\nnq({i}) <= ~q({i})" for i in range(10)))
    assert r["modelle"] == f"≥ {logic.MAX_MODELS}" and r["vollstaendig"] is False
    assert any("not every answer set" in line for line in logic.lines(r))


def test_function_terms_are_data():
    program, _ = logic.translate("p(open('f'))")
    assert program.startswith('p(open("f")).')  # a term, never a call


def test_soft_rule_ground_instances_are_dropped_one_by_one():
    a = logic.ask(BIRDS, ['flies("tweety")', 'flies("pingu")'])
    assert a == {'flies("tweety")': "true", 'flies("pingu")': "false"}
    p = logic.ask_probabilities(BIRDS, ['flies("tweety")', '-flies("pingu")'])
    assert p['flies("tweety")'] == pytest.approx(0.9, abs=0.001)  # one instance: P = the rule's probability (LPMLN)
    assert p['-flies("pingu")'] == 1.0 and p["_exact"] is True


def test_soft_rule_weights_are_learned_from_rated_conclusions(tmp_path):
    from vi_mcp import memory as g
    g.open_db(tmp_path / "t.db")
    try:
        before = logic.check(BIRDS)["regeln"][0]
        assert before["p"] == 0.9 and before["gemessen"] == [0, 0]
        for _ in range(6):
            out = logic.rate(BIRDS, 'flies("tweety")', False)
            assert [c["nr"] for c in out["gutgeschrieben"]] == [4]
        assert logic.ask(BIRDS, ['flies("tweety")'])['flies("tweety")'] == "not_derived"  # now outweighed
        r = logic.check(BIRDS)["regeln"][0]
        assert r["p"] < 0.5 and r["gewicht"] < 0 and r["gemessen"] == [0, 6]
        for _ in range(12):  # a rule once outweighed can earn its weight back
            logic.rate(BIRDS, 'flies("tweety")', True)
        assert logic.ask(BIRDS, ['flies("tweety")'])['flies("tweety")'] == "true"
        miss = logic.rate(BIRDS, 'swims("pingu")', True)
        assert miss["gutgeschrieben"] == [] and "missing rule" in miss["grund"]
    finally:
        g.close_db()


def test_hard_rule_stays_hard_but_shows_its_measurement(tmp_path):
    from vi_mcp import memory as g
    g.open_db(tmp_path / "t.db")
    try:
        for _ in range(4):
            logic.rate(DMZ, 'forbidden(run("freeipa","gate1"))', False)
        r = logic.check(DMZ)
        assert r["zustand"] == "verletzt"  # the measurement never changes what a hard rule derives
        rule = next(x for x in r["regeln"] if x["nr"] == 4)
        assert rule["soft"] is False and rule["gemessen"] == [0, 4] and "make it soft" in rule["hinweis"]
    finally:
        g.close_db()


def test_rule_weights_travel_only_where_allowed(tmp_path, monkeypatch):
    from vi_mcp import memory as g, p2p, word_weights
    g.open_db(tmp_path / "t.db")
    try:
        named = 'soft(down(H) <= host(H) & (H == "db1.corp.example.com"))'
        plain = 'soft(flies(X) <= bird(X))'
        for src, concl in ((named + '\nhost("db1.corp.example.com")', 'down("db1.corp.example.com")'), (plain + '\nbird("t")', 'flies("t")')):
            for _ in range(word_weights.MIN_N):
                logic.rate(src, concl, True)
        monkeypatch.setattr(p2p, "is_company", lambda net: net == "firma")
        open_out, firm_out = logic.outgoing("standard"), logic.outgoing("firma")
        assert len(firm_out) == 2 and len(open_out) == 1
        h = open_out[0]["ziel"]
        assert word_weights.known_hash(h)  # a rating for this hash is routed to the rule store
        assert h == logic.rule_hash("flies(X) :- bird(X).")
    finally:
        g.close_db()


def test_tool_check_ask_save_rate(tmp_path):
    from vi_mcp import config, memory as g, tools
    g.open_db(tmp_path / "t.db")
    try:
        out = tools.call_tool("vi_logic", {"source": DMZ}, "max", False)
        assert "violated never #5" in out and "evidence: inferred" in out
        saved = tools.call_tool("vi_logic", {"action": "save", "name": "dmz-rules", "source": DMZ, "description": "what may run in the DMZ",
                                             "visibility": "shared"}, "max", False)
        assert "rule set dmz-rules" in saved
        o = g.load(saved.split()[1])
        assert o.kind == "regel" and o.visibility == "geteilt" and "logik:dmz-rules" in o.hashtags and o.data["inhalt"] == DMZ
        ans = tools.call_tool("vi_logic", {"action": "ask", "rule_set": "dmz-rules", "source": 'planned(run("x","web1"))',
                                           "queries": ['forbidden(run("x","web1"))', 'forbidden(run("freeipa","gate1"))'],
                                           "probabilities": True}, "moritz", False)
        assert 'forbidden(run("x","web1")): not_derived' in ans and 'forbidden(run("freeipa","gate1")): true · P = 1.0' in ans
        rated = tools.call_tool("vi_logic", {"action": "rate", "rule_set": "dmz-rules", "conclusion": 'forbidden(run("freeipa","gate1"))',
                                             "correct": True}, "moritz", False)
        assert "rule #4" in rated and "1 right / 0 wrong" in rated
        with pytest.raises(tools.Rejected, match="notation"):
            tools.call_tool("vi_logic", {"source": "import os"}, "max", False)
        with pytest.raises(tools.Rejected, match="no rule set"):
            tools.call_tool("vi_logic", {"rule_set": "nope"}, "max", False)
        private = tools.call_tool("vi_logic", {"action": "save", "name": "mine", "source": "a", "visibility": "private"}, "max", False)
        assert private.startswith("saved ")
        with pytest.raises(tools.Rejected, match="no rule set"):
            tools.call_tool("vi_logic", {"rule_set": "mine"}, "moritz", False)  # another instance never sees a private rule set
        assert "vi_logic" not in {t["name"] for t in tools.listing(config.OPEN)}  # writes weights and objects: a token is required
    finally:
        g.close_db()


def test_install_into_a_target_outside_the_default_places_checks_that_target(tmp_path, monkeypatch, capsys):
    """0.62.4, reported from the CentralStation container: `vi-mcp logic install --target DIR` installed correctly and still said
    "still not importable" (exit 1) — the check looked only in the default places."""
    import subprocess
    import sys as _sys
    target = tmp_path / "py"
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, check=False: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    monkeypatch.delenv("VI_MCP_EXTRA_PYTHON", raising=False)
    seen = []
    monkeypatch.setattr(logic, "available", lambda: seen.append(str(target) in _sys.path) or True)
    try:
        assert logic.install(target) == 0
        assert "--target" in calls[0] and str(target) in calls[0]
        assert seen == [True]  # the target was on the import path when it was checked
        assert f"VI_MCP_EXTRA_PYTHON={target}" in capsys.readouterr().out  # the service needs to be told
    finally:
        if str(target) in _sys.path:
            _sys.path.remove(str(target))
