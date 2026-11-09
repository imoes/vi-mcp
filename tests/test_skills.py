"""0.9.0: Skills — gelöst gemeldet, aus Erholung im Schlaf, Weiterentwicklung, strittig, Fusion mit Verweis."""
import pytest

from vi_mcp import bandit, intuition, schlaf, sitzung, skills, werkzeuge
from vi_mcp import gedaechtnis as g

_n = iter(range(10_000))


def handlung(s, tool, ok, fehler=None, host="cue1"):
    args = {"host": host, "n": next(_n)}
    with sitzung.im_auftrag(s):
        v = intuition.vorher(tool, args, s.instanz)
        return intuition.nachher(tool, args, ok, 1, fehler, "ok" if ok else None, v["vorher_id"], s.instanz)["erfahrung"], v


def test_geloest_skill_erscheint_und_entwickelt_sich(gd):
    r = werkzeuge.rufe("vi_geloest", {"name": "Graylog Timeout", "reize": ["tool:graylog_search", "fehler:timeout", "art:x"],
                                      "schritte": ["graylog_system_status", "graylog_search"], "anleitung": "Erst Systemstatus prüfen, dann mit kleinerem Zeitraum suchen",
                                      "grund": "dreimal so gelöst"}, "a", True)
    assert "Skill „graylog-timeout“ v1 (test" in r
    sk = g.lade("skill:graylog-timeout")
    assert sk.sicht == "geteilt" and sk.daten["problem"]["reize"] == ["fehler:timeout", "tool:graylog_search"]
    v = intuition.vorher("graylog_search", {"q": 1}, "b")
    assert any("Skill „graylog-timeout“" in h and "graylog_system_status → graylog_search" in h for h in v["hinweise"])
    intuition.nachher("graylog_search", {"q": 1}, True, 1, None, "ok", v["vorher_id"], "b")
    assert bandit.gezeigt(g.lade(sk.id)) == 1 and bandit.zaehler(g.lade(sk.id))[0] > 0
    r = werkzeuge.rufe("vi_geloest", {"name": "graylog-timeout", "reize": ["tool:graylog_search"], "schritte": ["graylog_search", "graylog_count"],
                                      "anleitung": "Statusprüfung, dann Zeitraum halbieren, dann zählen statt suchen", "grund": "schneller"}, "b", True)
    sk = g.lade(sk.id)
    assert sk.daten["version"] == 2 and [s["tool"] for s in sk.daten["loesung"]["schritte"]] == ["graylog_system_status", "graylog_search", "graylog_count"]
    assert sk.daten["versionen"][1]["wer"] == "ki@b" and "Statusprüfung" in sk.text
    with pytest.raises(werkzeuge.Abgelehnt, match="Reiz"):
        werkzeuge.rufe("vi_geloest", {"name": "x-test", "reize": ["kein-tag"], "schritte": ["t"], "anleitung": "lange genug anleitung", "grund": "g"}, "a", True)
    assert "v2" in werkzeuge.rufe("vi_skill", {"id": sk.id}, "a", True)


def test_skill_aus_erholung_im_schlaf(gd):
    s = sitzung.beginne("a", "t")
    handlung(s, "checkmk_get_host", False, "ConnectionError: refused")
    handlung(s, "checkmk_get_host", False, "ConnectionError: refused")
    handlung(s, "Bash", True)  # z. B. Dienst neu gestartet
    e_ok, _ = handlung(s, "checkmk_get_host", True)
    assert "ueberraschung:erholt" in g.lade(e_ok).hashtags
    b = schlaf.lauf("Test")
    assert b.daten["schritte"]["4c_skills"]["neu"] == 1
    sk = [o for _, o, _g in g.erinnere("art:skill", betrachter=None)][0]
    assert sk.instanz == g.SERVER_INSTANZ and sk.modus == "test"
    assert [x["tool"] for x in sk.daten["loesung"]["schritte"]] == ["checkmk_get_host", "Bash", "checkmk_get_host"]
    assert {"tool:checkmk_get_host", "host:cue1"} <= set(sk.daten["problem"]["reize"]) and any(t.startswith("fehler:") for t in sk.daten["problem"]["reize"])
    assert len(sk.kanten()) >= 4
    # zweite Erholung desselben Problems → Version 2, kein zweiter Skill
    s2 = sitzung.beginne("b", "t")
    handlung(s2, "checkmk_get_host", False, "ConnectionError: refused")
    handlung(s2, "Bash", True)  # wieder etwas am System getan; nur „nochmal versucht“ entwickelt den Weg nicht weiter
    handlung(s2, "checkmk_get_host", True)
    b2 = schlaf.lauf("Test 2")
    assert b2.daten["schritte"]["4c_skills"] == {"neu": 0, "weiterentwickelt": 1, "strittig": 0, "vorschlaege": 0}
    assert g.lade(sk.id).daten["version"] == 2


def test_skill_wird_strittig_wenn_er_nicht_nuetzt(gd):
    sk = skills.neu("kaputt", ["tool:t_x"], ["t_y"], "angeblich hilft t_y vor t_x", "Testlauf", [], "a")
    for _ in range(3):
        bandit.verbuche([sk.id], False)
    assert schlaf.lauf("Test").daten["schritte"]["4c_skills"]["strittig"] == 1
    assert g.lade(sk.id).modus == "strittig"


def test_fusion_mit_verweis_und_vorschlag(gd):
    a = skills.neu("a-weg", ["tool:t_x", "fehler:f_1"], ["t_a", "t_x"], "Weg A: erst t_a dann t_x", "Testlauf", [], "a")
    b = skills.neu("b-weg", ["tool:t_x", "fehler:f_1", "host:h9"], ["t_b", "t_x"], "Weg B: erst t_b dann t_x", "Testlauf", [], "b")
    v = schlaf.lauf("Test").daten["schritte"]["4c_skills"]
    assert v["vorschlaege"] == 2 and "fusion:vorschlag" in g.lade(a.id).hashtags
    r = werkzeuge.rufe("vi_skill_fusion", {"a": a.id, "b": b.id, "name": "t_x Störung", "grund": "beide lösen dasselbe"}, "c", True)
    assert "aufgegangen" in r
    neu_o = [o for _, o, _g in g.erinnere("art:skill", betrachter=None)][0]  # der einzige nicht aufgegangene
    assert neu_o.id == "skill:t_x-st-rung"  # Slug: Unterstrich bleibt, Umlaut wird Bindestrich
    assert [s["tool"] for s in neu_o.daten["loesung"]["schritte"]] == ["t_a", "t_x", "t_b"]
    assert neu_o.daten["problem"]["reize"] == ["fehler:f_1", "host:h9", "tool:t_x"] and neu_o.daten["fusion_aus"] == [a.id, b.id]
    assert g.lade(a.id).modus == "aufgegangen" and g.lade(a.id).daten["aufgegangen_in"] == neu_o.id
    assert [o.id for _, o, _g in g.erinnere("art:skill", betrachter=None)] == [neu_o.id]  # Aufgegangenes nicht mehr in Suchen
    assert g.lade(a.id).id in [o.id for _, o, _g in g.erinnere("art:skill modus:aufgegangen", betrachter=None)]  # aber auf Nachfrage
    assert "AUFGEGANGEN in" in werkzeuge.rufe("vi_skill", {"id": a.id}, "a", True)
    with pytest.raises(werkzeuge.Abgelehnt, match="bereits aufgegangen"):
        werkzeuge.rufe("vi_skill_fusion", {"a": a.id, "b": neu_o.id, "name": "x", "grund": "nochmal"}, "c", True)


def test_weiterentwickeln_ersetzt_die_reize(gd):
    """0.20.11: v2 eines Skills behielt den zu allgemeinen Reiz tool:Bash aus v1 und erschien vor jedem Shell-Befehl."""
    from vi_mcp import skills
    from vi_mcp import gedaechtnis as g
    s1 = skills.neu("pruefen", ["thema:ansible-lint", "tool:Bash"], ["Bash"], "ansible-lint --offline rolle", "erste Fassung", [], "a")
    assert "tool:Bash" in s1.hashtags
    s2 = skills.neu("pruefen", ["thema:ansible-lint", "thema:yamllint"], ["Bash"], "ansible-lint --offline rolle; yamllint -d relaxed",
                    "zu allgemeiner Reiz entfernt", [], "a")
    o = g.lade(s2.id)
    assert o.daten["version"] == 2 and "tool:Bash" not in o.hashtags and "thema:yamllint" in o.hashtags
    assert o.daten["problem"]["reize"] == ["thema:ansible-lint", "thema:yamllint"]
    assert o.daten["versionen"][-1]["reize_vorher"] == ["thema:ansible-lint", "tool:Bash"]
    assert [x.id for _, x, _g in g.erinnere("tool:Bash", arten=("skill",), betrachter=None)] == []
