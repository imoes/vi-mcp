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
    ('x(H) <= (O in objects("host:*")) & (O.host != H)', "== only"),
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
    assert r["importiert"]["objekte"] == 1 and r["importiert"]["abgeschnitten"] == 2
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
