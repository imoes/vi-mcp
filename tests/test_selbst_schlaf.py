"""0.4.0: self, sleep (consolidation), archive, power-law decay."""
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import intuition, sleep_cycle, self_model, session, tools
from vi_mcp import memory as g


def _age(oid: str, days: float) -> None:
    z = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ?, zuletzt = ? WHERE id = ?", (z, z, oid))
        g.db().commit()


_n = iter(range(10_000))


def _experience(tool, host, ok, instance="a", error=None):
    """One real action per call: unique arguments, otherwise from the 2nd time on the answer cache answers
    from memory and counts a second experience (wanted in the VI, not wanted here)."""
    args = {"host": host, "n": next(_n)}
    v = intuition.before(tool, args, instance)
    return intuition.after(tool, args, ok, 1, error, "ok" if ok else None, v["vorher_id"], instance)["erfahrung"]


def test_self_core_and_narrative(gd):
    k = self_model.core()
    assert k.id == self_model.CORE and k.data["version"] == 1 and k.instance == g.SERVER_INSTANCE and k.visibility == "geteilt"
    assert "self v1" in k.data["erzaehlung"] and "Limits:" in k.data["erzaehlung"]
    assert len(k.data["erzaehlung"].split()) <= 151
    assert self_model.core().id == k.id  # idempotent
    assert len(self_model.versions()) == sum(len(v) for v in self_model.DEFAULT_TARGET.values())


def test_self_proposal_needs_evidence_and_foreign_trusted_instance(gd):
    a, b, c = session.begin("a", "t"), session.begin("b", "t"), session.begin("c", "t")
    evidence_list = []
    for i in range(3):
        o = g.new_object("erkenntnis", f"Beleg {i} für Vorsicht bei Nachtarbeit", ["thema:nacht"], {"quelle": "x"}, reason="T")
        evidence_list.append(o.id)
    with session.on_behalf(a):
        with pytest.raises(tools.Rejected, match="at least 3 pieces of evidence"):
            tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list[:2]}, "a", True)
        with pytest.raises(tools.Rejected, match="different days"):
            tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list}, "a", True)
    _age(evidence_list[0], 2)
    with session.on_behalf(a):
        r = tools.call_tool("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": evidence_list}, "a", True)
    vid = r.split()[1]
    assert g.load(vid).mode == "test" and self_model.core().data["version"] == 1
    with session.on_behalf(a), pytest.raises(tools.Rejected, match="self-confirmation"):
        tools.call_tool("vi_bestaetige", {"id": vid, "grund": "ich selbst"}, "a", True)
    with session.on_behalf(b), pytest.raises(tools.Rejected, match="is not trusted"):
        tools.call_tool("vi_bestaetige", {"id": vid, "grund": "finde ich gut"}, "b", False)
    with session.on_behalf(c):
        r = tools.call_tool("vi_bestaetige", {"id": vid, "grund": "vom Menschen freigegeben"}, "c", True)
    assert "version 2" in r
    k = self_model.core()
    assert k.data["version"] == 2 and any("Nachts keine" in s["satz"] for s in k.data["soll"]["werte"])
    assert "Nachts keine" in k.data["erzaehlung"] and g.load(vid).mode == "aktiv"
    assert self_model.versions()[0][3] == "werte" and "vom Menschen freigegeben" in self_model.versions()[0][5]
    assert "Version 2" in tools.call_tool("vi_selbst", {"versionen": True}, "a", True)


def test_self_in_initialize_and_repetition(gd):
    s = session.begin("a", "t")
    with session.on_behalf(s):
        for i in range(self_model.REPEAT_PER - 1):
            assert not any(h.startswith("[Self]") for h in intuition.before("Bash", {"i": i}, "a", False)["hinweise"])
        assert any(h.startswith("[Self]") for h in intuition.before("Bash", {}, "a", False)["hinweise"])
    assert self_model.hint().startswith("[Self] I am the VI")


def test_decay_power_law(gd):
    o = g.new_object("erkenntnis", "alt aber wichtig", ["thema:v"], {"quelle": "x"}, reason="T")
    assert g.recall("thema:v", viewer=None)[0][2]["aktualitaet"] == 1.0
    _age(o.id, 30)
    a30 = g.recall("thema:v", viewer=None)[0][2]["aktualitaet"]
    assert 0.12 < a30 < 0.16  # (1+720)^-0.3 ≈ 0.139; exponential would be 0.03
    _age(o.id, 365)
    assert g.recall("thema:v", viewer=None)[0][2]["aktualitaet"] > 0.06


def test_sleep_abstraction_schema_conflict_and_report(gd):
    # cluster (host:web5, skill:checkmk): 4 actions on 2 days, all ok → insight (test) with evidence edges
    ids = [_experience("checkmk_get_host", "web5", True) for _ in range(4)]
    _age(ids[0], 1); _age(ids[1], 1)
    assert sleep_cycle.due(datetime(2026, 11, 9, 3, 5, tzinfo=timezone.utc)) == "nightly run 03:00 UTC (no sleep in 24 h)"
    assert sleep_cycle.due(datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)) is None  # importance 0, not night
    b = sleep_cycle.run("Test")
    assert b.kind == "schlaf" and "zustand:fertig" in b.hashtags and b.data["schritte"]["4_abstraktion"] == 1
    e = [o for _, o, _g in g.recall("herkunft:schlaf", viewer=None)][0]
    assert e.mode == "test" and e.data["ausgang"] == "gut" and "web5" in e.text and len(e.edges()) == 4
    assert b.text.startswith("Sleep finished") and sleep_cycle.last().id == b.id
    # second run, same cluster with the opposite outcome → conflict, no silent change
    for _ in range(3):
        _experience("checkmk_get_host", "web5", False, error="Timeout: 30 s")
    b2 = sleep_cycle.run("Test 2")
    assert b2.data["schritte"]["3_schema"]["konflikte"] == 1 and b2.data["schritte"]["4_abstraktion"] == 0
    e = g.load(e.id)
    assert "konflikt:offen" in e.hashtags and e.mode == "test" and e.data["konflikte"][0]["ausgang"] == "schlecht"
    # a sleep confirmation does not count as a foreign instance
    assert e.foreign_confirmations() == 0
    assert "Sleep finished" in tools.call_tool("vi_status", {}, "a", True)
    assert "conflicts" in tools.call_tool("vi_schlaf", {}, "a", True)
    with pytest.raises(tools.Rejected, match="is not trusted"):
        tools.call_tool("vi_schlaf", {"jetzt": True}, "b", False)


def test_sleep_self_actual(gd):
    for i in range(5):
        _experience("netbox_get_vms", "h9", i < 4)
    sleep_cycle.run("Test")
    actual = self_model.core().data["ist"]
    assert actual["kompetenz"][0] == {"bereich": "skill:netbox", "erfahrungen": 5, "erfolgsquote": 0.8, "zeitraum": "30 d"}
    assert "Experienced in: skill:netbox (5 actions, 80 % ok, 30 d)" in self_model.core().data["erzaehlung"]


def test_night_run_only_after_24_h_without_sleep(gd):
    """0.20.3: a sleep on the same calendar day (00:28) silently skipped the nightly run; now the nightly run is a safety net for quiet days."""
    b = sleep_cycle.run("Wichtigkeit")
    now = datetime.fromisoformat(b.ts)
    at_three = now.replace(hour=3, minute=5) if now.hour >= 3 else now.replace(hour=3, minute=5)
    assert sleep_cycle.due(at_three + timedelta(days=0 if at_three > now else 1)) is None  # last sleep < 24 h ago
    assert sleep_cycle.due(at_three + timedelta(days=2)).startswith("nightly run")       # > 24 h without sleep



def test_sleep_at_most_every_two_hours(gd):
    """0.21.1: 45 sleeps in 24 h with 3 new insights in total — threshold 80 and minimum spacing 120 min."""
    from datetime import datetime, timedelta, timezone
    for i in range(30):
        g.new_object("erfahrung", f"Handlung {i}", ["tool:x"], {}, importance=3, reason="T")
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    assert sleep_cycle.due(now) is not None  # 90 ≥ 80, never slept yet
    g.new_object("schlaf", "Schlaf fertig", ["zustand:fertig"], {}, reason="T")
    assert sleep_cycle.due(now) is None  # just slept


def test_self_proposal_can_replace_a_sentence(gd):
    """0.25.0: a confirmed proposal with replaces swaps the sentence instead of adding a contradicting second one."""
    a, c = session.begin("a", "t"), session.begin("c", "t")
    evidence_list = [g.new_object("erkenntnis", f"user decision {i}: all output in English", ["thema:sprache"], {"quelle": "x"}, reason="T").id
                     for i in range(3)]
    _age(evidence_list[0], 2)
    old = self_model.core().data["soll"]["stil"][0]["satz"]
    new = "Write in English and keep answers short; numbers with unit, period and origin."
    with session.on_behalf(a), pytest.raises(tools.Rejected, match="replaces: no sentence"):
        tools.call_tool("vi_self_propose", {"area": "style", "sentence": new, "reason": "user decision", "evidence": evidence_list,
                                            "replaces": "a sentence that is not there"}, "a", True)
    with session.on_behalf(a):
        vid = tools.call_tool("vi_self_propose", {"area": "style", "sentence": new, "reason": "user decision: English", "evidence": evidence_list,
                                                  "replaces": old}, "a", True).split()[1]
    with session.on_behalf(c):
        tools.call_tool("vi_confirm", {"id": vid, "reason": "the user asked for it"}, "c", True)
    style = [e["satz"] for e in self_model.core().data["soll"]["stil"]]
    assert style == [new] and self_model.core().data["soll"]["stil"][0]["replaced"] == old  # replaced, not added
    assert f"replaces: {old}" in self_model.versions()[0][5]  # the old sentence stays in the history
    assert new in self_model.core().data["erzaehlung"] and old not in self_model.core().data["erzaehlung"]


def test_a_weakness_says_when_it_happened(gd):
    """0.63.0, found on production (13.11.2026): "Weaknesses: tool:analyse … (184×)" read like an ongoing failure; all 184 had come in one
    hour that was over. The self model now says from when to when."""
    for _ in range(4):
        _experience("analyse", "h1", False, error="HTTP 400 max_tokens not supported")
    sleep_cycle._self_actual()
    k = self_model.core()
    text = self_model.narrative(k)
    assert "Weaknesses: tool:analyse" in text and "(4×, " in text and " UTC)" in text
