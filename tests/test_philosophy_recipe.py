"""0.70.1: the training recipe with reasoning traces for kollektiv 1.3.0 (philosophy_recipe)."""
import pytest

pytest.importorskip("clingo")
from clingo_object import philosophy as ph, philosophy_recipe as pr, philosophy_train as pt  # noqa: E402

PKG = ph.load("kollektiv")


@pytest.fixture(scope="module")
def built():
    return pr.rows(PKG, 160, 5)


def test_rows_are_built_from_the_seed_alone_and_repeat_exactly(built):
    again, _rep = pr.rows(PKG, 160, 5)
    assert [r["messages"] for r in again] == [r["messages"] for r in built[0]]


def test_every_target_reads_back_as_the_gold(built):
    rows, rep = built
    assert rep["refused_by_trace_check"] == 0
    for r in rows:
        m, a = r["meta"], r["messages"][2]["content"]
        if m["task"] in ("judge", "pressure"):
            sc = pt.score(PKG, m["gold"], pt.parse_verdict(PKG, pr.verdict_part(a)))
            assert sc["duties_exact"] and all(x["wrong"] == 0 and x["missing"] == 0 for x in sc["answers"].values())
            assert a.index("Facts:") < a.index("Statements:") < a.index("Count:") < a.index("Duty check:")
        elif m["task"] == "formalize":
            assert pr.facts_of(a) == {l.replace(" ", "") for l in m["facts"].splitlines() if l.strip()}


def test_worlds_cover_one_to_ten_statements_and_rare_cases(built):
    _rows, rep = built
    assert set(k for k, n in rep["statements"].items() if n) >= {"1", "2", "3", "7", "10"}
    floor = pr.CASE_FLOOR * rep["judged"]
    assert sum(1 for n in rep["cases_in_judged_rows"].values() if n >= floor) >= len(pr.CASES) - 3  # a few rows can lag the floor


def test_the_situation_is_numbered_with_unknown_lines():
    rows, _ = pr.rows(PKG, 60, 9)
    j = [r for r in rows if r["meta"]["task"] == "judge"]
    assert all("\n[1] " in r["messages"][1]["content"] for r in j)
    assert any("unknown" in r["messages"][2]["content"].split("\n\n")[0] for r in j)  # filler sentences are a trained class


def test_avoided_worlds_never_become_rows():
    first, _ = pr.rows(PKG, 30, 11)
    avoid = {r["meta"]["facts"] for r in first}
    again, rep = pr.rows(PKG, 30, 11, avoid=avoid)
    assert rep["skipped_as_avoided"] > 0 and not ({r["meta"]["facts"] for r in again} & avoid)


def test_scoring_reads_the_spoken_verdict_not_the_trace():
    """A duty a trace line names but the verdict does not say is not counted as said (the trace states conditions, not the answer)."""
    text = ("Facts:\n[1] author(s1, x)\n\nStatements: s1\n\nDuty check:\ns1: author x → x must not confirm s1\n\n"
            "Statement s1: no verdict, because the view of the evidence is not closed.\nDuties: none.")
    assert pt.parse_verdict(PKG, pr.verdict_part(text))["duties"] == []
    assert pt.parse_verdict(PKG, text)["duties"] == ["forbidden(confirm(x,s1))"]  # what the whole-text reading would have counted


def test_facts_of_reads_numbered_lines_joined_facts_and_unknown():
    assert pr.facts_of("Facts:\n[1] author(s1, x)\n[2] unknown\n[3] line(s1, pos, fam_a, y); closed(s1)\n\nCount:") == {
        "author(s1,x)", "line(s1,pos,fam_a,y)", "closed(s1)"}


def test_statements_follow_one_natural_order():
    facts = [("author", f"s{i}", "x") for i in (10, 2, 1)]
    assert pt.verdict(PKG, facts)["subjects"] == ["s1", "s2", "s10"]
