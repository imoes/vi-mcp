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
