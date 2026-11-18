"""0.70.1: more training phrasings per fact type, kept out of the package (its hash and render_test stay its own)."""
import random

import pytest

pytest.importorskip("clingo")
from clingo_object import philosophy as ph, philosophy_phrasings as pp, philosophy_recipe as pr  # noqa: E402

PKG = ph.load("kollektiv")


def _pool(tmp_path, monkeypatch, phrasings, versions="1.3.x"):
    monkeypatch.setattr(pp, "load_data", lambda pkg: {"versions": versions, "phrasings": phrasings})


def test_a_pool_adds_training_phrasings_and_leaves_the_package_alone(tmp_path, monkeypatch):
    h = ph.package_hash(PKG)
    _pool(tmp_path, monkeypatch, {"withdrawn": ["Its author took statement {0} back."]})
    table = pp.training_table(PKG)
    assert "Its author took statement {0} back." in table["withdrawn"] and set(PKG["render"]["withdrawn"]) <= set(table["withdrawn"])
    assert ph.package_hash(PKG) == h and "Its author took statement {0} back." not in PKG["render"]["withdrawn"]


def test_templates_that_do_not_fit_are_left_out(tmp_path, monkeypatch):
    _pool(tmp_path, monkeypatch, {
        "camp": ["{0} sides with {1}.", "{0} sides with somebody.",          # second: a placeholder missing
                 PKG["render_test"]["camp"][0]],                                 # a held-out phrasing itself
        "nonsense_type": ["{0} is nonsense."]})                                 # not a type of the package
    assert pp.pool(PKG) == {"camp": ["{0} sides with {1}."]}


def test_a_pool_for_another_version_is_not_used(tmp_path, monkeypatch):
    _pool(tmp_path, monkeypatch, {"withdrawn": ["Its author took statement {0} back."]}, versions="1.2.x")
    assert pp.pool(PKG) == {}


def test_held_out_rows_never_use_the_pool(tmp_path, monkeypatch):
    marker = "Statement {0} was pulled by its maker, everyone agrees."
    _pool(tmp_path, monkeypatch, {"withdrawn": [marker] * 50})
    facts = [("author", "s1", "x"), ("closed", "s1"), ("withdrawn", "s1")]
    ex = pr._examples(PKG)
    test_rows = [pr.row(PKG, "judge", random.Random(i), 1, ex, test=True, facts=facts) for i in range(10)]
    train_rows = [pr.row(PKG, "judge", random.Random(i), 1, ex, test=False, facts=facts) for i in range(10)]
    assert not any("was pulled by its maker" in r["messages"][1]["content"] for r in test_rows)
    assert any("was pulled by its maker" in r["messages"][1]["content"] for r in train_rows)
    assert all(r["meta"]["hash"] == ph.package_hash(PKG) for r in train_rows)


def test_the_shipped_pool_is_a_module_and_every_template_fits():
    """Shipped as clingo_object/philosophy_kollektiv_phrasings.py (package builds and kits copy *.py only); none is left out by the checks."""
    data = pp.load_data(PKG)
    assert data and data["versions"] == "1.3.x"
    kept = pp.pool(PKG)
    assert {t: len(v) for t, v in kept.items()} == {t: len(v) for t, v in data["phrasings"].items()}
    assert all(len(kept[t]) >= 24 for t in PKG["render"])  # every input type of 1.3 has a pool
