"""clingo-objekt A3 (0.63.0): what a logic program proposes is derived on the server, held in quarantine and applied only when someone
other than its author releases it — never silently (the epistemic rules: nothing changes without a reason chain and a decision)."""
import pytest

pytest.importorskip("clingo")

from vi_mcp import memory as g, p2p, tools  # noqa: E402

PROG = '''
in_dmz(H) <= (O in objects("zone:dmz")) & (O.host == H)
propose(tag(P, "status", "blocked")) <= (P in objects("plan:*")) & (P.host == H) & in_dmz(H)
propose(link(P, O, "plan targets a DMZ host")) <= (P in objects("plan:*")) & (O in objects("zone:dmz")) & (P.host == H) & (O.host == H)
'''


def _world():
    g.new_object("erkenntnis", "gate1 is the mail relay in the DMZ", ["host:gate1", "zone:dmz"], {"quelle": "t"}, reason="T", instance="a",
                 oid="erkenntnis:gate1", link=False)
    g.new_object("erkenntnis", "plan: roll out freeipa on gate1", ["host:gate1", "plan:freeipa"], {"quelle": "t"}, reason="T", instance="a",
                 oid="erkenntnis:plan-gate1", link=False)


def _held(out):
    return [line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("held for review: ")]


def test_a_proposal_is_held_and_its_author_cannot_release_it(gd):
    _world()
    out = tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False)
    held = _held(out)
    assert len(held) == 2 and "you cannot release your own proposal" in out
    o = g.load(held[0])
    assert o.kind == "vorschlag" and o.mode == "quarantaene" and o.data["regeln"] and o.data["programm_hash"]
    assert "status:blocked" not in g.load("erkenntnis:plan-gate1").hashtags  # nothing changed yet
    with pytest.raises(tools.Rejected, match="cannot release its own proposal"):
        tools.call_tool("vi_release", {"id": held[0], "reason": "mine"}, "a", True, True)
    q = tools.call_tool("vi_quarantine", {"limit": 10}, "release-cli", False, True)
    assert held[0] in q and "a logic program of instance a" in q


def test_release_applies_tag_and_link_with_origin(gd):
    _world()
    held = _held(tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False))
    for oid in held:
        tools.call_tool("vi_release", {"id": oid, "reason": "checked by a person"}, "release-cli", False, True)
    plan = g.load("erkenntnis:plan-gate1")
    assert "status:blocked" in plan.hashtags
    assert any("erkenntnis:gate1" == b for b, _why in plan.edges())
    assert any("logic proposal vorschlag:" in c["grund"] for c in plan.changes)
    assert all(g.load(oid).data.get("angewandt") for oid in held)


def test_discard_leaves_a_tombstone_and_the_same_proposal_is_not_stored_again(gd):
    _world()
    held = _held(tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False))
    again = tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False)
    assert "already waiting (counted again)" in again and not _held(again)
    assert g.load(held[0]).data["wiederholt"] == 1
    tools.call_tool("vi_release", {"id": held[0], "reason": "wrong rule", "action": "discard"}, "release-cli", False, True)
    o = g.load(held[0])
    assert o.mode == "widerlegt" and any("discarded" in c["was"] for c in o.changes)
    third = tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False)
    assert f"already decided (discarded): {held[0]}" in third


def test_system_tags_and_invisible_targets_are_refused(gd):
    _world()
    g.new_object("erkenntnis", "private of b", ["host:gate1", "plan:x"], {"quelle": "t"}, reason="T", instance="b", visibility="privat",
                 oid="erkenntnis:priv", link=False)
    out = tools.call_tool("vi_logic", {"action": "propose", "source":
                          'propose(tag(P, "modus", "aktiv")) <= (P in objects("plan:*"))'}, "a", False)
    assert "refused" in out and "only the system sets" in out and not _held(out)
    assert g.load("erkenntnis:priv") is not None and "erkenntnis:priv" not in out  # b's private object never reached a's program


def test_a_proposal_whose_target_vanished_is_not_applied(gd):
    _world()
    held = _held(tools.call_tool("vi_logic", {"action": "propose", "source": PROG}, "a", False))
    g.delete(["erkenntnis:plan-gate1"])
    with pytest.raises(tools.Rejected, match="can no longer be applied"):
        tools.call_tool("vi_release", {"id": held[0], "reason": "ok"}, "release-cli", False, True)
    assert g.load(held[0]).mode == "quarantaene"


def test_proposals_are_never_silent(gd):
    _world()
    assert "proposes nothing" in tools.call_tool("vi_logic", {"action": "propose", "source": 'p(O) <= (O in objects("plan:*"))'}, "a", False)
    assert p2p is not None


def test_rule_sets_and_rated_conclusions_become_training_data(gd, tmp_path):
    """C2 (0.63.0): "trainieren unsere VI mit clingo-objekt inkl. den DB-SQL-Objekten" — a saved rule set gives a tool-use example
    (task → program → solver answer), a conclusion rated right an ask example, one rated wrong a KTO negative; a private set never."""
    import json
    from vi_mcp import dataset
    _world()
    src = 'in_dmz(H) <= (O in objects("zone:dmz")) & (O.host == H)\nnever(in_dmz(H) & (H == "gate1"))'
    tools.call_tool("vi_logic", {"action": "save", "name": "dmz", "source": src, "description": "is gate1 kept out of the DMZ",
                                 "visibility": "internal"}, "a", False)
    tools.call_tool("vi_logic", {"action": "save", "name": "mine", "source": src, "visibility": "private"}, "a", False)
    tools.call_tool("vi_logic", {"action": "rate", "rule_set": "dmz", "conclusion": 'in_dmz("gate1")', "correct": True}, "a", False)
    tools.call_tool("vi_logic", {"action": "rate", "rule_set": "dmz", "conclusion": 'in_dmz("gate1")', "correct": False}, "a", False)
    m = dataset.export(tmp_path / "out")
    assert m["counts"]["logic"] == 2
    rows = [json.loads(x) for x in (tmp_path / "out" / "logic.jsonl").read_text().splitlines()]
    check = next(r for r in rows if r["meta"]["kind"] == "check")
    call = check["messages"][1]["tool_calls"][0]["function"]
    assert call["name"] == "vi_logic" and call["arguments"]["source"] == src and check["tools"][0]["function"]["name"] == "vi_logic"
    assert "violated never #2" in check["messages"][2]["content"] and check["messages"][3]["content"].startswith("Violated")
    rated = next(r for r in rows if r["meta"]["kind"] == "rated")
    assert 'in_dmz("gate1"): true' in rated["messages"][3]["content"]
    kto = [json.loads(x) for x in (tmp_path / "out" / "kto.jsonl").read_text().splitlines()]
    assert any(k["meta"].get("source") == "logic.rate" and k["label"] is False for k in kto)
    assert "logic.jsonl | 2 |" in (tmp_path / "out" / "DATASHEET.md").read_text()
    assert all(r["meta"]["rule_set"] != "mine" for r in rows)


def test_rules_are_learned_from_rated_conclusions_and_held_for_review(gd):
    """C3 (0.63.0): a rule set derives review(O) for every test object; people rated the DMZ ones right and the internal ones wrong.
    clingo, as the optimiser over a small hypothesis space, finds the narrower rule; it is held as a proposal and, released, becomes a
    new version of the rule set."""
    for i in range(10):
        zone = "dmz" if i % 2 == 0 else "intern"
        g.new_object("erkenntnis", f"note {i}", ["thema:oo", f"zone:{zone}", f"host:h{i}"], {"quelle": "t"}, reason="T",
                     oid=f"erkenntnis:n{i}", mode="test", link=False)
    src = 'review(O) <= (O in objects("thema:oo")) & (O.mode == "test")'
    tools.call_tool("vi_logic", {"action": "save", "name": "rev", "source": src, "visibility": "internal"}, "a", False)
    for i in range(10):
        tools.call_tool("vi_logic", {"action": "rate", "rule_set": "rev", "conclusion": f'review("erkenntnis:n{i}")',
                                     "correct": i % 2 == 0}, "a", False)
    out = tools.call_tool("vi_logic", {"action": "learn", "rule_set": "rev"}, "a", False)
    assert 'soft(review(O) <= (O in objects("thema:oo")) & (O.zone == "dmz")' in out
    assert "from 8 rated conclusions (2 held out to test)" in out and "held out: 1/1 right, 0/1 wrong" in out
    held = _held(out)
    assert len(held) == 1 and g.load(held[0]).data["vorschlag"]["aktion"] == "rule"
    tools.call_tool("vi_release", {"id": held[0], "reason": "the narrower rule is right"}, "release-cli", False, True)
    newest = tools._logic_set("rev", "a")
    assert '(O.zone == "dmz")' in newest.data["logik"]["quelle"] and src in newest.data["logik"]["quelle"]
    # ratings belong to a program text: the new version has none yet
    assert "nothing learned" in tools.call_tool("vi_logic", {"action": "learn", "rule_set": "rev"}, "a", False)


def test_a_question_in_natural_language_is_answered_on_the_server(gd, monkeypatch):
    """0.63.0: vi_logic action=answer — the server's language model writes clingo-object, the server solves it with the asker's objects
    (only notation runs, never Python); a refusal goes back to the model. Here a scripted model needs two rounds."""
    from vi_mcp import logic
    _world()
    g.new_object("erkenntnis", "private of b", ["host:secret1", "zone:dmz"], {"quelle": "t"}, reason="T", instance="b", visibility="privat",
                 oid="erkenntnis:priv-b", link=False)
    replies = iter(['```logic\nans(H) <= O in objects("zone:dmz") & (O.host == H)\n```',
                    '```logic\nans(H) <= (O in objects("zone:dmz")) & (O.host == H)\n```'])
    seen = []
    monkeypatch.setattr(logic, "agent_llm", lambda messages: seen.append([dict(m) for m in messages]) or next(replies))
    out = tools.call_tool("vi_logic", {"action": "answer", "question": "Which hosts are in the DMZ?"}, "a", False)
    assert out.startswith("state: answered · 1 answer(s) · 2 round(s)") and 'ans("gate1")' in out and "secret1" not in out
    assert "- zone: dmz" in seen[0][0]["content"]  # the vocabulary the asker may see went to the model
    assert "refused" in seen[1][-1]["content"]
    monkeypatch.setattr(logic, "agent_llm", None)
    monkeypatch.setattr(logic, "llm_available", lambda: False)
    with pytest.raises(tools.Rejected, match="no language model"):
        tools.call_tool("vi_logic", {"action": "answer", "question": "x"}, "a", False)


def test_answered_questions_become_training_data_once_rated(gd, monkeypatch, tmp_path):
    """0.63.2 — the user (14.11.2026): collect more training data from real use before fine-tuning. An answered question keeps its
    program; rated right it becomes an example, rated wrong a negative (the model's mistake, in its own words)."""
    import json
    from vi_mcp import dataset, logic
    _world()
    good = '```logic\nans(H) <= (O in objects("zone:dmz")) & (O.host == H)\n```'
    bad = '```logic\nans(H) <= (O in objects("host:*")) & (O.host == H)\n```'
    for reply, question in ((good, "Which hosts are in the DMZ?"), (bad, "Which hosts are in the DMZ, really?")):
        monkeypatch.setattr(logic, "agent_llm", lambda m, reply=reply: reply)
        out = tools.call_tool("vi_logic", {"action": "answer", "question": question}, "a", False)
        assert 'vi_logic(action="rate"' in out
    asked = logic.asked_questions()
    assert len(asked) == 2 and {q["frage"] for q in asked} == {"Which hosts are in the DMZ?", "Which hosts are in the DMZ, really?"}
    good_prog = next(q["programm"] for q in asked if q["frage"] == "Which hosts are in the DMZ?")
    bad_prog = next(q["programm"] for q in asked if q["frage"] != "Which hosts are in the DMZ?")
    tools.call_tool("vi_logic", {"action": "rate", "source": good_prog, "conclusion": 'ans("gate1")', "correct": True}, "a", False)
    tools.call_tool("vi_logic", {"action": "rate", "source": bad_prog, "conclusion": 'ans("gate1")', "correct": False}, "a", False)
    dataset.export(tmp_path / "out")
    logic_rows = [json.loads(x) for x in (tmp_path / "out" / "logic.jsonl").read_text().splitlines()]
    kto = [json.loads(x) for x in (tmp_path / "out" / "kto.jsonl").read_text().splitlines()]
    assert any(r["meta"].get("kind") == "asked" and r["messages"][0]["content"] == "Which hosts are in the DMZ?" for r in logic_rows)
    neg = [k for k in kto if k["meta"].get("source") == "logic.answer"]
    assert len(neg) == 1 and neg[0]["label"] is False and 'objects("host:*")' in neg[0]["completion"]
