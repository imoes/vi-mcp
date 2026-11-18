"""0.70.1: reasoning traces for kollektiv 1.3.0 — every block names exactly the atoms the seed derives (no second semantics)."""
import copy
import random

import pytest

pytest.importorskip("clingo")
from clingo_object import philosophy as ph, philosophy_train as pt, philosophy_trace as tr  # noqa: E402

PKG = ph.load("kollektiv")


def test_package_is_the_one_the_traces_are_written_for():
    assert PKG["version"] == "1.3.0"


def test_every_block_agrees_with_the_seed_on_random_and_package_worlds():
    big = copy.deepcopy(PKG)
    big["generator"]["subjects"]["count"] = [1, 10]
    rnd = random.Random(7)
    worlds = [pt.facts_text(pt.draw_world(PKG if i % 2 else big, rnd)) for i in range(120)] + [w["facts"] for w in PKG["worlds"]]
    for ft in worlds:
        t = tr.trace(PKG, ft)  # raises TraceError on any disagreement
        assert t.startswith("Count:") and "\n\nDuty check:\n" in t


def test_rare_branches_are_written_and_checked():
    ft = ("author(s1, x)\nline(s1, pos, fam_a, y)\nline(s1, pos, fam_b, z)\nclosed(s1)\nevidence_kind(fam_a, hearsay)\n"
          "evidence_kind(fam_b, hearsay)\n"                                  # P9: hearsay only
          "author(s2, x)\nline(s2, pos, fam_c, y)\nline(s2, pos, fam_d, z)\nclosed(s2)\ncamp(fam_c, red)\ncamp(fam_d, red)\n"  # P10
          "author(s3, x)\nline(s3, pos, fam_e, y)\nline(s3, pos, fam_f, z)\nclosed(s3)\nextraordinary(s3)\n"                     # P12
          "author(s4, x)\nline(s4, pos, fam_g, y)\nline(s4, pos, fam_h, z)\nderives_from(fam_h, fam_g)\nclosed(s4)\n"            # P8 copy
          "author(s5, x)\nline(s5, pos, fam_i, y)\nclosed(s5)\nuntestable(s5)\n"                                                 # P11
          "author(s6, x)\nclosed(s6)\nwithdrawn(s6)\n")                                                                          # P13
    t = tr.trace(PKG, ft)
    for phrase in ("s1 pos: two or more roots, hearsay only yes", "held: hearsay only", "held: one camp only", "held: extraordinary",
                   "fam_h: copy of fam_g → root fam_g", "s4 pos: one root (fam_g) → single", "→ untestable",
                   "s6: support no, opposition no, closed yes → n; withdrawn by its author, nothing else → withdrawn",
                   "s5: acceptance untestable → may state s5 only as untestable, must not assert it"):
        assert phrase in t, phrase


def test_conditional_duty_lines_are_written_for_every_statement():
    """H7 (run 31): the ask line and the adopt line exist for every statement, 'not met' when their condition does not hold."""
    ft = "author(s1, x)\nline(s1, pos, fam_a, y)\nclosed(s1)\nauthor(s2, x)\nforeign(s2)\nunreviewed(s2)\npeer_offers(s2)\nclosed(s2)\n"
    duty = tr.trace(PKG, ft).split("Duty check:\n")[1]
    for s in ("s1", "s2"):
        assert sum(1 for l in duty.splitlines() if l.startswith(f"{s}: value ") and "peer offers" in l) == 1
        assert sum(1 for l in duty.splitlines() if l.startswith(f"{s}: foreign ")) == 1
    assert "s1: foreign no, unreviewed no → not met, no adopt rule" in duty and "s2: foreign yes, unreviewed yes → must not adopt s2" in duty
    assert "s2: value n, peer offers yes → ask the collective about s2" in duty


def test_a_block_that_states_another_semantics_is_refused(monkeypatch):
    real = tr.count_block

    def drops_the_author_rule(derived):  # counts the author's own line: P1 violated
        text, named = real(derived)
        return text, named | {f"counts({s},{p},{o})" for s, p, o, _i in tr.atoms(derived, "line")}
    monkeypatch.setattr(tr, "count_block", drops_the_author_rule)
    with pytest.raises(tr.TraceError, match="count: trace and seed differ"):
        tr.trace(PKG, "author(s1, x)\nline(s1, pos, fam_a, x)\nclosed(s1)\n")


def test_large_worlds_are_derived_completely():
    big = copy.deepcopy(PKG)
    big["generator"]["subjects"]["count"] = [10, 10]
    ft = pt.facts_text(pt.draw_world(big, random.Random(3)))
    assert len(tr.derive(PKG, ft)) > 200  # more than notation.MAX_SHOWN — nothing cut
    tr.trace(PKG, ft)
