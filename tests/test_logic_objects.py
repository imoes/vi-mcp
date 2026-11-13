"""clingo-objekt (0.63.0): memory objects as facts in the logic notation, and proposals that only a person releases.

The user (13.11.2026): the data lie in objects in SQL, so we program with these objects in clingo — a dialect of SQL and clingo, the
way Delphi grew out of Pascal."""
import pytest

pytest.importorskip("clingo")

from vi_mcp import logic  # noqa: E402
from vi_mcp import memory as g  # noqa: E402


def _hosts():
    a = g.new_object("erkenntnis", "gate1 is the mail relay in the DMZ", ["host:gate1", "zone:dmz", "rolle:mail"], {"quelle": "t"},
                     reason="T", instance="a", oid="erkenntnis:gate1")
    b = g.new_object("erkenntnis", "web1 serves the intranet", ["host:web1", "zone:intern"], {"quelle": "t"}, reason="T", instance="a",
                     oid="erkenntnis:web1")
    plan = g.new_object("erkenntnis", "plan: roll out freeipa on gate1", ["host:gate1", "plan:freeipa"], {"quelle": "t"}, reason="T",
                        instance="a", oid="erkenntnis:plan-gate1", link=False)
    plan.link(a.id, "same host")
    return a, b, plan


DMZ_RULES = '''
in_dmz(H) <= (O in objects("zone:dmz")) & (O.host == H)
planned(R, H) <= (P in objects("plan:*")) & (P.plan == R) & (P.host == H)
never(planned(R, H) & in_dmz(H))
'''


def test_objects_fields_and_tags_become_facts(gd):
    _hosts()
    a = logic.ask('mail(O, H) <= (O in objects("rolle:mail")) & (O.host == H) & (O.kind == "erkenntnis")',
                  ['mail("erkenntnis:gate1","gate1")', 'mail("erkenntnis:web1","web1")'])
    assert a == {'mail("erkenntnis:gate1","gate1")': "true", 'mail("erkenntnis:web1","web1")': "not_derived"}


def test_a_saved_style_rule_set_checks_the_real_objects(gd):
    _hosts()
    r = logic.check(DMZ_RULES)
    assert r["zustand"] == "verletzt" and r["verletzt"][0]["nr"] == 3
    assert 'planned("freeipa","gate1")' in r["folgerungen"]
    imp = r["importiert"]
    assert imp["filter"] == ["zone:dmz", "plan:*"] and imp["je_filter"] == [1, 1] and imp["objekte"] == 2
    assert any("imported 2 objects" in line for line in logic.lines(r))


def test_linked_follows_edges_between_imported_objects(gd):
    _hosts()
    a = logic.ask('about(P, O) <= (P in objects("plan:*")) & (O in objects("zone:*")) & linked(P, O)', ['about("erkenntnis:plan-gate1","erkenntnis:gate1")'])
    assert a['about("erkenntnis:plan-gate1","erkenntnis:gate1")'] == "true"


def test_not_has_a_tag_is_written_with_not(gd):
    _hosts()
    a = logic.ask('outside(O) <= (O in objects("host:*")) & ~(O.zone == "dmz")', ['outside("erkenntnis:web1")', 'outside("erkenntnis:gate1")'])
    assert a == {'outside("erkenntnis:web1")': "true", 'outside("erkenntnis:gate1")': "not_derived"}


@pytest.mark.parametrize("bad, why", [
    ('x(H) <= (O.host == H)', "not bound"),
    ('x(O) <= O in objects("host:*") & y(O)', "parentheses"),
    ('x(H) <= (O in objects("host:*")) & (O.host != H)', "is compared with"),
    ('x(O.host)', "comparison of its own"),
    ('x(O) <= objects("host:*")', "binds a variable"),
    ('linked("a", "b")', "object dialect"),
    ('propose(tag("x", "a", "b"))', "object variable"),
    ('propose(tag(O, "a", "b")) <= q(O)', "not bound"),
])
def test_the_dialect_refuses_with_a_reason(bad, why):
    with pytest.raises(logic.LogicError, match=why):
        logic.translate(bad)


def test_a_filter_without_a_known_kind_is_refused(gd):
    _hosts()
    with pytest.raises(logic.LogicError, match="at least one kind:value"):
        logic.check('x(O) <= (O in objects("gate1 mail"))')


def test_visibility_of_the_asker_and_quarantine_never_imported(gd):
    g.new_object("erkenntnis", "db9 secret note", ["host:db9", "zone:dmz"], {"quelle": "t"}, reason="T", instance="b", visibility="privat",
                 oid="erkenntnis:private-db9")
    g.new_object("erkenntnis", "held", ["host:evil", "zone:dmz"], {"quelle": "t"}, reason="T", instance="b", mode="quarantaene",
                 oid="erkenntnis:held")
    _hosts()
    prog = 'dmz(O) <= (O in objects("zone:dmz"))'
    seen_by_a = logic.check(prog, viewer="a")
    assert 'dmz("erkenntnis:gate1")' in seen_by_a["folgerungen"] and not any("private-db9" in f for f in seen_by_a["folgerungen"])
    assert seen_by_a["importiert"]["nicht_sichtbar"] == 1
    assert not any("held" in f for f in seen_by_a["folgerungen"])
    assert not any("held" in f for f in logic.check(prog)["folgerungen"])  # not even for the server itself


def test_quarantine_is_dropped_even_if_a_filter_returned_it(gd, monkeypatch):
    """Second line of defence: whatever the filter search returns, quarantined and archived objects never become facts."""
    g.new_object("erkenntnis", "held", ["host:evil", "zone:dmz"], {"quelle": "t"}, reason="T", mode="quarantaene", oid="erkenntnis:held")
    monkeypatch.setattr(g, "ids_for_filter", lambda f, kinds=(), viewer=None: ["erkenntnis:held"])
    r = logic.check('dmz(O) <= (O in objects("zone:dmz"))')
    assert r["importiert"]["objekte"] == 0 and r["importiert"]["ausgeschlossen"] == 1 and r["folgerungen"] == []


def test_the_object_limit_is_named(gd, monkeypatch):
    _hosts()
    monkeypatch.setattr(logic, "MAX_OBJECTS", 1)
    r = logic.check('h(O) <= (O in objects("host:*"))')
    assert r["importiert"]["objekte"] == 1 and r["importiert"]["abgeschnitten"] >= 2  # objects one edge away count against the limit too
    assert any("cut (limit 1 objects)" in line for line in logic.lines(r))


def test_strings_from_memory_and_filters_stay_data(gd):
    g.new_object("erkenntnis", 'quote " and backslash \\ and #script (python)', ["host:x1", "zone:dmz"], {"quelle": "t"}, reason="T",
                 oid="erkenntnis:odd")
    r = logic.check('t(O, T) <= (O in objects("zone:dmz")) & (O.text == T)')
    assert r["zustand"] == "erfuellt" and len(r["folgerungen"]) == 1
    assert logic.check("x(O) <= (O in objects(\"host:x1' OR 1=1 --\"))")["importiert"]["objekte"] == 0


def test_without_a_memory_objects_says_where_it_runs():
    g.close_db() if g._db is not None else None
    with pytest.raises(logic.LogicError, match="reads the memory"):
        logic.check('x(O) <= (O in objects("host:*"))')


def test_proposals_are_listed_with_their_rule(gd):
    _hosts()
    r = logic.check(DMZ_RULES + 'propose(tag(P, "status", "blocked")) <= (P in objects("plan:*")) & (P.host == H) & in_dmz(H)')
    assert r["vorschlaege"] == [{"aktion": "tag", "ziel": "erkenntnis:plan-gate1", "art": "status", "wert": "blocked", "regeln": [4]}]
    assert any("proposes tag status:blocked on erkenntnis:plan-gate1 · by rule #4" in line for line in logic.lines(r))


# ── numbers and the boundary to the Python package clingo-object ─────────────


def _aged(oid, kind, days, mode="test"):
    from datetime import datetime, timedelta, timezone
    o = g.new_object(kind, f"{oid} text", ["thema:oo"], {"quelle": "t"}, reason="T", oid=oid, mode=mode, link=False)
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), oid))
        g.db().commit()
    return o


def test_numbers_compare_from_either_side(gd):
    _aged("erkenntnis:old", "erkenntnis", 120)
    a = logic.ask('old(O) <= (O in objects("thema:oo")) & (100 < O.age)\nyoung(O) <= (O in objects("thema:oo")) & (O.age <= 100)',
                  ['old("erkenntnis:old")', 'young("erkenntnis:old")'])
    assert a == {'old("erkenntnis:old")': "true", 'young("erkenntnis:old")': "not_derived"}


def test_an_edge_target_is_an_object(gd):
    _hosts()
    a = logic.ask('dmz_plan(P) <= (P in objects("plan:*")) & linked(P, O) & (O.zone == "dmz")', ['dmz_plan("erkenntnis:plan-gate1")'])
    assert a['dmz_plan("erkenntnis:plan-gate1")'] == "true"


@pytest.mark.parametrize("bad, why", [
    ("class Skill:\n    pass", "clingo-object"),
    ("def stale(self):\n    return a", "clingo-object"),
    ('x(O) <= (O in objects("host:*")) & ~(O.age > 3)', "opposite comparison"),
    ("p(Vi__1)", "reserved"),
    ('x(O) <= (O in objects("host:*")) & O.stale()', "predicate"),
])
def test_classes_live_in_the_python_package_not_in_the_server_notation(bad, why):
    """The user (13.11.2026): consistent with the clingo Python package — classes and methods are real Python in clingo-object, which
    compiles them to flat rules; the server runs only this notation and never Python."""
    with pytest.raises(logic.LogicError, match=why):
        logic.translate(bad)


def test_one_edge_away_respects_visibility_and_quarantine(gd):
    _hosts()
    plan = g.load("erkenntnis:plan-gate1")
    g.new_object("erkenntnis", "private of b", ["host:p1"], {"quelle": "t"}, reason="T", instance="b", visibility="privat",
                 oid="erkenntnis:priv", link=False)
    g.new_object("erkenntnis", "held", ["host:q1"], {"quelle": "t"}, reason="T", mode="quarantaene", oid="erkenntnis:q", link=False)
    plan.link("erkenntnis:priv", "x")
    plan.link("erkenntnis:q", "x")
    r = logic.check('near(B) <= (P in objects("plan:*")) & linked(P, B)', viewer="a")
    assert r["folgerungen"] == ['near("erkenntnis:gate1")']
    assert r["importiert"]["ueber_kanten"] == 1 and r["importiert"]["nicht_sichtbar"] == 1 and r["importiert"]["ausgeschlossen"] == 1


def test_the_objects_action_gives_the_same_data_as_json(gd):
    """A2: the data path for clingo-object — the same visibility as the server's own import."""
    import json
    from vi_mcp import tools
    _hosts()
    g.new_object("erkenntnis", "private of b", ["zone:dmz", "host:p9"], {"quelle": "t"}, reason="T", instance="b", visibility="privat",
                 oid="erkenntnis:priv9", link=False)
    d = json.loads(tools.call_tool("vi_logic", {"action": "objects", "filters": ["zone:dmz", "plan:*"]}, "a", False))
    ids = {o["id"] for o in d["objects"]}
    assert ids == {"erkenntnis:gate1", "erkenntnis:plan-gate1"} and d["members"] == [["erkenntnis:gate1"], ["erkenntnis:plan-gate1"]]
    gate = next(o for o in d["objects"] if o["id"] == "erkenntnis:gate1")
    assert gate["tags"]["zone"] == ["dmz"] and gate["kind"] == "erkenntnis" and isinstance(gate["age"], int)
    assert d["counts"]["not_visible"] == 1 and d["limit"] == logic.MAX_OBJECTS
    assert ["erkenntnis:plan-gate1", "erkenntnis:gate1", "same host"] in d["edges"]
    with pytest.raises(tools.Rejected, match="needs filters"):
        tools.call_tool("vi_logic", {"action": "objects"}, "a", False)


def test_edges_are_loaded_only_for_a_program_that_follows_them(gd):
    _hosts()
    without = logic.check('h(O) <= (O in objects("plan:*"))')
    assert without["importiert"]["objekte"] == 1 and without["importiert"]["ueber_kanten"] == 0
    with_edges = logic.check('h(B) <= (O in objects("plan:*")) & linked(O, B)')
    assert with_edges["importiert"]["ueber_kanten"] == 1
