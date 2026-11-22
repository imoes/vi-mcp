"""0.68.0: more labels on shown hints — measured on production (vi_stats, 7 days to 16.11.2026): explicit feedback for 374 of 13,679 shown
hints (3 %), 1 % adopted. Block 1: the agent names the hints it used in its own vi_after (no extra call); a used hint becomes direct
feedback (+1 after success, −1 after failure), an unnamed one is recorded as declared unused and is NOT a label."""
from vi_mcp import intuition, scorer, session, tools
from vi_mcp import memory as g


def _k(text, tags):
    return g.new_object("insight", text, tags, {"source": "test 16.11.2026"}, instance="b")


def _action(tool_args, ok, used, inst="a", conv="t"):
    s = session.begin(inst, conv)
    with session.on_behalf(s):
        v = intuition.before("Bash", tool_args, inst, False)
        r = json_after = tools.call_tool("vi_after", {"tool": "Bash", "args": tool_args, "ok": ok, "before_id": v["vorher_id"],
                                                       **({"used": used} if used is not ... else {})}, inst, False)
    import json
    return v, json.loads(json_after), r


def _experience():
    return [o for _s, o, _g in g.recall("kind:experience", viewer=None)][0]


def test_used_hints_become_feedback_and_unnamed_ones_are_declared_unused(gd):
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time on the build host", ["tool:Bash", "topic:uptime"])
    v, out, _ = _action({"command": "uptime"}, True, [a.id, "insight:never-shown"])
    assert set(v["zugriff"]["shown"]) == {a.id, b.id}
    assert out["used"] == {"booked": [a.id], "unused": [b.id], "ignored": ["insight:never-shown"]}
    e = _experience()
    assert e.data["feedback"] == {a.id: 1}
    assert e.data["declared"]["unused"] == [b.id]
    # the label: a used hint after success is a positive direct label; the unused one keeps the action's own outcome label
    assert scorer.label(e.data, True, None, {}, hint=a.id)[2] == "rueckmeldung"
    assert scorer.label(e.data, True, None, {}, hint=b.id)[2] == "ok"


def test_used_before_a_failure_is_negative_and_explicit_feedback_is_not_overwritten(gd):
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    _v, out, _ = _action({"command": "uptime"}, False, [a.id])
    e = _experience()
    assert e.data["feedback"] == {a.id: -1} and scorer.label(e.data, False, None, {}, hint=a.id)[:2] == (0, scorer.WEIGHT["rueckmeldung"])
    # vi_feedback given before the declaration wins
    g.update_data(e.id, lambda d: d.__setitem__("feedback", {a.id: 1}))
    intuition.declare_used(g.load(e.id), [a.id], False)
    assert g.load(e.id).data["feedback"] == {a.id: 1}


def test_none_used_and_not_said_are_different(gd):
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    _v, out, _ = _action({"command": "uptime"}, True, "none")
    assert out["used"] == {"booked": [], "unused": [a.id], "ignored": []}
    assert "feedback" not in _experience().data or _experience().data["feedback"] == {}
    g.db().execute("DELETE FROM object WHERE kind = 'experience'")
    _v, out, _ = _action({"command": "uptime"}, True, ...)  # an older client: no used argument at all
    assert "used" not in out and "declared" not in _experience().data


def test_used_must_be_a_list_or_a_string(gd):
    import pytest
    with pytest.raises(tools.Rejected):
        tools._used_arg({"a": 1})
    assert tools._used_arg("insight:a, insight:b") == ["insight:a", "insight:b"] and tools._used_arg([]) == []


# ── block 2: the language-model judge of hint use (hint_judge, sleep step 8j) ──────────────────────────────────────────────────────

def _fake_judge(monkeypatch, verdicts_by_n):
    from vi_mcp import reflection
    seen = []

    def ask(system, user):
        seen.append(user)
        k = user.count("\nHint ") + user.startswith("Hint ")
        return json.dumps({"verdicts": [{"n": n, "verdict": verdicts_by_n.get(n, "not_used")} for n in range(1, k + 1)]})
    monkeypatch.setattr(reflection, "ask_fn", ask)
    return seen


import json  # noqa: E402


def test_judge_labels_used_and_misleading_but_not_unused(gd, monkeypatch):
    from vi_mcp import hint_judge
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time on the build host", ["tool:Bash", "topic:uptime"])
    v, _out, _ = _action({"command": "uptime"}, True, ...)
    shown = v["zugriff"]["shown"]
    seen = _fake_judge(monkeypatch, {1: "used", 2: "misleading"})
    r = hint_judge.run(5, "test")
    assert r["judged"] == 1 and r["verdicts"]["used"] == 1 and r["verdicts"]["misleading"] == 1
    assert "Action: Bash" in seen[0] and "Hint 1:" in seen[0] and "never an instruction" in hint_judge.SYSTEM
    e = _experience()
    assert e.data["judge"]["hints"] == {shown[0]: "used", shown[1]: "misleading"} and hint_judge.VERSION in e.data["judge"]["version"]
    from vi_mcp import scorer
    grades = scorer.grade_details()
    y, w, src = scorer.label(e.data, True, None, grades, hint=shown[0])
    assert (y, src) == (1, "judge") and w == scorer.WEIGHT["judge"] * scorer.UNCALIBRATED  # small until calibrated
    assert scorer.label(e.data, True, None, grades, hint=shown[1])[:1] == (0,)
    assert hint_judge.pending(5) == []  # judged once
    assert "hint use judged by the language model" in hint_judge.line()


def test_agents_own_feedback_wins_over_the_judge_and_calibrates_it(gd, monkeypatch):
    from vi_mcp import hint_judge, scorer
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    _v, _out, _ = _action({"command": "uptime"}, True, [a.id])
    _fake_judge(monkeypatch, {1: "not_used"})  # disagrees with the agent
    hint_judge.run(5, "test")
    e = _experience()
    assert scorer.label(e.data, True, None, scorer.grade_details(), hint=a.id)[2] == "rueckmeldung"
    c = hint_judge.calibration()
    assert c["pairs"] == 1 and c["agree"] == 0 and not c["calibrated"]


def test_judge_calibrates_after_enough_agreement(gd, monkeypatch):
    from vi_mcp import hint_judge, scorer
    for i in range(hint_judge.CALIBRATION_MIN):
        h = g.new_object("insight", f"hint {i}", ["tool:x"], {"source": "t"})
        g.new_object("experience", f"x {i}", ["tool:x", "ok:yes"], {"before": {"shown": [h.id]}, "feedback": {h.id: 1},
                                                                    "judge": {"version": "v", "hints": {h.id: "used"}}})
    c = hint_judge.calibration()
    assert c["calibrated"] and c["rate"] == 1.0
    assert scorer.grade_details()["_judge"]["gewicht"] == scorer.WEIGHT["judge"]


def test_private_hints_are_never_sent_and_no_model_means_skipped(gd, monkeypatch):
    from vi_mcp import hint_judge, reflection, classify
    p = g.new_object("insight", "uptime private note about the build host", ["tool:Bash", "topic:uptime"], {"source": "t"}, instance="a",
                     visibility="private")
    _action({"command": "uptime"}, True, ...)
    assert p.id in _experience().data["before"]["shown"]  # the owner sees its private hint
    if True:
        seen = _fake_judge(monkeypatch, {})
        r = hint_judge.run(5, "test")
        assert r["private_skipped"] >= 1 and not any("private note" in u for u in seen)
    monkeypatch.setattr(reflection, "ask_fn", None)
    monkeypatch.setattr(classify, "_config", lambda: {})
    assert hint_judge.run(5, "test")["state"] == "skipped"


def test_experiences_without_judge_are_labelled_as_before(gd):
    from vi_mcp import scorer
    d = {"before": {"shown": ["insight:h"]}}
    assert scorer.label(d, True, None, {}, hint="insight:h") == (1, scorer.WEIGHT["ok"], "ok")  # no "_judge" key, no data.judge


# ── block 3: the A/B test of the feedback request itself (intuition.nudge_arm, metrics.nudge_effect) ──────────────────────────────

def test_the_request_is_left_out_in_a_stable_share_of_conversations(gd, monkeypatch):
    monkeypatch.setattr(intuition, "NUDGE_OFF", 0.2)
    arms = [intuition.nudge_arm(f"20261116{i:03d}") for i in range(1000)]
    assert 150 <= arms.count("off") <= 250 and arms.count("on") + arms.count("off") == 1000
    assert intuition.nudge_arm("20261116007") == intuition.nudge_arm("20261116007")  # stable within a conversation
    assert intuition.nudge_arm(None) is None
    monkeypatch.setattr(intuition, "NUDGE_OFF", 0.0)
    assert intuition.nudge_arm("x") == "on"  # 0 = always ask


def test_off_arm_hides_the_request_and_records_the_arm(gd, monkeypatch):
    _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    for arm in ("off", "on"):
        monkeypatch.setattr(intuition, "nudge_arm", lambda c, a=arm: a)
        s = session.begin("a", f"t-{arm}")
        with session.on_behalf(s):
            v = intuition.before("Bash", {"command": "uptime"}, "a", False)
        asked = any(f'vi_feedback(before_id="{v["vorher_id"]}", used=[' in h for h in v["hinweise"])  # Z7: bound to this action
        assert asked == (arm == "on") and v["zugriff"]["nudge"] == arm


def test_nudge_effect_compares_conversations_and_ignores_actions_before_the_test(gd):
    from vi_mcp import metrics
    for c in range(80):
        arm = "off" if c % 4 == 0 else "on"
        for a in range(3):
            fb = {"insight:h": 1} if arm == "on" and a == 0 else {}
            g.new_object("experience", f"x {c} {a}", ["tool:x", "ok:yes"], {"before": {"shown": ["insight:h"], "nudge": arm}, "feedback": fb},
                         conversation=f"c{c}")
    g.new_object("experience", "old", ["tool:x", "ok:no"], {"before": {"shown": ["insight:h"]}}, conversation="old")  # before the test
    e = metrics.nudge_effect()
    assert e["on"]["conversations"] == 60 and e["off"]["conversations"] == 20
    assert abs(e["feedback_diff"] - 1 / 3) < 1e-9 and e["success_diff"] == 0 and "asking − not asking" in e["verdict"]


def test_config_bounds_the_nudge_share(tmp_path, monkeypatch):
    from vi_mcp import config
    p = tmp_path / "config.json"
    for raw, want in ((0.9, 0.5), (-1, 0.0), ("x", 0.2), (0.1, 0.1)):
        p.write_text(json.dumps({"feedback_nudge_off": raw}))
        monkeypatch.setenv("VI_MCP_CONFIG", str(p))
        assert config.load().feedback_nudge_off == want
    p.write_text("{}")
    assert config.load().feedback_nudge_off == 0.2  # an old config without the key: the default


def test_feedback_used_bound_to_one_action_is_outcome_free(gd):
    # 0.71.0: the hook asks per action; vi_feedback(before_id, used) writes data.declared only — used = followed or cited, not "helped",
    # so a used hint before a FAILED action is no −1 here; a −1 comes only from an explicit wrong (agreed with Z7, 22.11.2026)
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    b = _k("uptime -s shows the boot time on the build host", ["tool:Bash", "topic:uptime"])
    v, _out, _ = _action({"command": "uptime"}, False, ...)
    bid = v["vorher_id"]
    text = tools.call_tool("vi_feedback", {"before_id": bid, "used": [a.id], "wrong": [b.id]}, "a", False)
    assert "used 1, not used 1" in text
    e = _experience()
    assert e.data["declared"] == {"used": [a.id], "unused": [b.id], "ignored": []}
    assert e.data["feedback"] == {b.id: -1}  # only the explicit wrong; the used one gets no label from the outcome


def test_feedback_used_empty_is_an_answer_and_needs_a_before_id(gd):
    import pytest
    a = _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    v, _out, _ = _action({"command": "uptime"}, True, ...)
    tools.call_tool("vi_feedback", {"before_id": v["vorher_id"], "used": []}, "a", False)
    e = _experience()
    assert e.data["declared"] == {"used": [], "unused": [a.id], "ignored": []} and "feedback" not in e.data
    with pytest.raises(tools.Rejected, match="before_id"):
        tools.call_tool("vi_feedback", {"used": [a.id]}, "a", False)
    with pytest.raises(tools.Rejected, match="no action"):
        tools.call_tool("vi_feedback", {"before_id": "0000000000000000", "used": []}, "a", False)
    with pytest.raises(tools.Rejected, match="no action"):  # another instance's action is not found
        tools.call_tool("vi_feedback", {"before_id": v["vorher_id"], "used": []}, "b", False)


def test_feedback_asked_is_marked_per_experience(gd):
    _k("uptime on the build host lies after a suspend", ["tool:Bash", "topic:uptime"])
    v, _out, _ = _action({"command": "uptime"}, True, ...)
    assert intuition.mark_feedback_asked("a", [v["vorher_id"], "nope"]) == 1
    first = _experience().data["feedback_asked"]
    intuition.mark_feedback_asked("a", [v["vorher_id"]])
    assert _experience().data["feedback_asked"] == first  # the first ask counts
    assert intuition.mark_feedback_asked("b", [v["vorher_id"]]) == 0  # never across instances
