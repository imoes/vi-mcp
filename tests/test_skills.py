"""0.9.0: Skills — gelöst gemeldet, aus Erholung im Schlaf, Weiterentwicklung, strittig, Fusion mit Verweis."""
import pytest

from vi_mcp import bandit, intuition, sleep_cycle, session, skills, tools
from vi_mcp import memory as g

_n = iter(range(10_000))


def action(s, tool, ok, error=None, host="cue1"):
    args = {"host": host, "n": next(_n)}
    with session.on_behalf(s):
        v = intuition.before(tool, args, s.instance)
        return intuition.after(tool, args, ok, 1, error, "ok" if ok else None, v["vorher_id"], s.instance)["erfahrung"], v


def test_solved_skill_appears_and_evolves(gd):
    r = tools.call_tool("vi_geloest", {"name": "Graylog Timeout", "reize": ["tool:graylog_search", "fehler:timeout", "art:x"],
                                      "schritte": ["graylog_system_status", "graylog_search"], "anleitung": "Erst Systemstatus prüfen, dann mit kleinerem Zeitraum suchen",
                                      "grund": "dreimal so gelöst"}, "a", True)
    assert "Skill „graylog-timeout“ v1 (test" in r
    sk = g.load("skill:graylog-timeout")
    assert sk.visibility == "geteilt" and sk.data["problem"]["reize"] == ["fehler:timeout", "tool:graylog_search"]
    v = intuition.before("graylog_search", {"q": 1}, "b")
    assert any("Skill „graylog-timeout“" in h and "graylog_system_status → graylog_search" in h for h in v["hinweise"])
    intuition.after("graylog_search", {"q": 1}, True, 1, None, "ok", v["vorher_id"], "b")
    assert bandit.shown(g.load(sk.id)) == 1 and bandit.counter(g.load(sk.id))[0] > 0
    r = tools.call_tool("vi_geloest", {"name": "graylog-timeout", "reize": ["tool:graylog_search"], "schritte": ["graylog_search", "graylog_count"],
                                      "anleitung": "Statusprüfung, dann Zeitraum halbieren, dann zählen statt suchen", "grund": "schneller"}, "b", True)
    sk = g.load(sk.id)
    assert sk.data["version"] == 2 and [s["tool"] for s in sk.data["loesung"]["schritte"]] == ["graylog_system_status", "graylog_search", "graylog_count"]
    assert sk.data["versionen"][1]["wer"] == "ki@b" and "Statusprüfung" in sk.text
    with pytest.raises(tools.Rejected, match="Reiz"):
        tools.call_tool("vi_geloest", {"name": "x-test", "reize": ["kein-tag"], "schritte": ["t"], "anleitung": "lange genug anleitung", "grund": "g"}, "a", True)
    assert "v2" in tools.call_tool("vi_skill", {"id": sk.id}, "a", True)


def test_skill_from_recovery_in_sleep(gd):
    s = session.begin("a", "t")
    action(s, "checkmk_get_host", False, "ConnectionError: refused")
    action(s, "checkmk_get_host", False, "ConnectionError: refused")
    action(s, "Bash", True)  # z. B. Dienst neu gestartet
    e_ok, _ = action(s, "checkmk_get_host", True)
    assert "ueberraschung:erholt" in g.load(e_ok).hashtags
    b = sleep_cycle.run("Test")
    assert b.data["schritte"]["4c_skills"]["neu"] == 1
    sk = [o for _, o, _g in g.recall("art:skill", viewer=None)][0]
    assert sk.instance == g.SERVER_INSTANCE and sk.mode == "test"
    assert [x["tool"] for x in sk.data["loesung"]["schritte"]] == ["checkmk_get_host", "Bash", "checkmk_get_host"]
    assert {"tool:checkmk_get_host", "host:cue1"} <= set(sk.data["problem"]["reize"]) and any(t.startswith("fehler:") for t in sk.data["problem"]["reize"])
    assert len(sk.edges()) >= 4
    # zweite Erholung desselben Problems → Version 2, kein zweiter Skill
    s2 = session.begin("b", "t")
    action(s2, "checkmk_get_host", False, "ConnectionError: refused")
    action(s2, "Bash", True)  # wieder etwas am System getan; nur „nochmal versucht“ entwickelt den Weg nicht weiter
    action(s2, "checkmk_get_host", True)
    b2 = sleep_cycle.run("Test 2")
    assert b2.data["schritte"]["4c_skills"] == {"neu": 0, "weiterentwickelt": 1, "strittig": 0, "vorschlaege": 0}
    assert g.load(sk.id).data["version"] == 2


def test_skill_becomes_disputed_when_useless(gd):
    sk = skills.new("kaputt", ["tool:t_x"], ["t_y"], "angeblich hilft t_y vor t_x", "Testlauf", [], "a")
    for _ in range(3):
        bandit.book_entry([sk.id], False)
    assert sleep_cycle.run("Test").data["schritte"]["4c_skills"]["strittig"] == 1
    assert g.load(sk.id).mode == "strittig"


def test_merge_with_reference_and_proposal(gd):
    a = skills.new("a-weg", ["tool:t_x", "fehler:f_1"], ["t_a", "t_x"], "Weg A: erst t_a dann t_x", "Testlauf", [], "a")
    b = skills.new("b-weg", ["tool:t_x", "fehler:f_1", "host:h9"], ["t_b", "t_x"], "Weg B: erst t_b dann t_x", "Testlauf", [], "b")
    v = sleep_cycle.run("Test").data["schritte"]["4c_skills"]
    assert v["vorschlaege"] == 2 and "fusion:vorschlag" in g.load(a.id).hashtags
    r = tools.call_tool("vi_skill_fusion", {"a": a.id, "b": b.id, "name": "t_x Störung", "grund": "beide lösen dasselbe"}, "c", True)
    assert "aufgegangen" in r
    new_o = [o for _, o, _g in g.recall("art:skill", viewer=None)][0]  # der einzige nicht aufgegangene
    assert new_o.id == "skill:t_x-st-rung"  # Slug: Unterstrich bleibt, Umlaut wird Bindestrich
    assert [s["tool"] for s in new_o.data["loesung"]["schritte"]] == ["t_a", "t_x", "t_b"]
    assert new_o.data["problem"]["reize"] == ["fehler:f_1", "host:h9", "tool:t_x"] and new_o.data["fusion_aus"] == [a.id, b.id]
    assert g.load(a.id).mode == "aufgegangen" and g.load(a.id).data["aufgegangen_in"] == new_o.id
    assert [o.id for _, o, _g in g.recall("art:skill", viewer=None)] == [new_o.id]  # Aufgegangenes nicht mehr in Suchen
    assert g.load(a.id).id in [o.id for _, o, _g in g.recall("art:skill modus:aufgegangen", viewer=None)]  # aber auf Nachfrage
    assert "AUFGEGANGEN in" in tools.call_tool("vi_skill", {"id": a.id}, "a", True)
    with pytest.raises(tools.Rejected, match="bereits aufgegangen"):
        tools.call_tool("vi_skill_fusion", {"a": a.id, "b": new_o.id, "name": "x", "grund": "nochmal"}, "c", True)


def test_evolve_replaces_the_triggers(gd):
    """0.20.11: v2 eines Skills behielt den zu allgemeinen Reiz tool:Bash aus v1 und erschien vor jedem Shell-Befehl."""
    from vi_mcp import skills
    from vi_mcp import memory as g
    s1 = skills.new("pruefen", ["thema:ansible-lint", "tool:Bash"], ["Bash"], "ansible-lint --offline rolle", "erste Fassung", [], "a")
    assert "tool:Bash" in s1.hashtags
    s2 = skills.new("pruefen", ["thema:ansible-lint", "thema:yamllint"], ["Bash"], "ansible-lint --offline rolle; yamllint -d relaxed",
                    "zu allgemeiner Reiz entfernt", [], "a")
    o = g.load(s2.id)
    assert o.data["version"] == 2 and "tool:Bash" not in o.hashtags and "thema:yamllint" in o.hashtags
    assert "thema:ansible-lint" in o.hashtags  # 0.20.12: ein Reiz, der in beiden Versionen steht, darf nicht verschwinden
    assert o.data["problem"]["reize"] == ["thema:ansible-lint", "thema:yamllint"]
    assert o.data["versionen"][-1]["reize_vorher"] == ["thema:ansible-lint", "tool:Bash"]
    assert [x.id for _, x, _g in g.recall("tool:Bash", kinds=("skill",), viewer=None)] == []
