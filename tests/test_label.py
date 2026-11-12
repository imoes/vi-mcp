"""0.56.0: one label for router, bandit and metrics (scorer.label), weighted by its source."""
from vi_mcp import bandit, learning, metrics, scorer
from vi_mcp import memory as g


def test_label_order_and_weights():
    grades = {"7": {"note": 0.2, "quelle": "modell", "gewicht": 0.18}, "8": {"note": 0.1, "quelle": "mensch", "gewicht": 3.0}}
    d = {"score": {"note": 1.0}, "rueckmeldung": {"erkenntnis:a": -1}}
    assert scorer.label(d, True, None, {}, hint="erkenntnis:a") == (0, 2.0, "rueckmeldung")  # feedback on this hint beats everything
    assert scorer.label(d, True, "8", grades) == (0, 3.0, "mensch")  # a bad human grade fails the whole conversation
    assert scorer.label(d, True, "7", grades) == (0, 0.18, "modell")  # an uncalibrated model grade counts, but little
    assert scorer.label(d, False, None, grades) == (1, 1.0, "code")  # the code stage beats the tool's own outcome
    assert scorer.label({}, False, None, grades) == (0, 1.0, "ok")
    assert scorer.label({}, None, None, grades) is None


def test_grade_details_weigh_uncalibrated_model_grades(gd):
    g.new_object("bewertung", "model grade", ["scorer:modell"], {"scorer": "modell", "ziel": "5", "note": 0.25, "sicherheit": "hoch"})
    g.new_object("bewertung", "model grade", ["scorer:modell"], {"scorer": "modell", "ziel": "6", "note": 0.25, "sicherheit": "niedrig"})
    g.new_object("bewertung", "human grade", ["scorer:mensch"], {"scorer": "mensch", "ziel": "6", "note": 0.9})
    d = scorer.grade_details()
    assert d["5"] == {"note": 0.25, "quelle": "modell", "gewicht": round(scorer.WEIGHT["modell"] * 1.0 * scorer.UNCALIBRATED, 3)}
    assert d["6"]["quelle"] == "mensch" and d["6"]["gewicht"] == 3.0  # the human grade wins


def test_router_bandit_and_metrics_see_the_same_label(gd):
    # an action whose tool succeeded, in a conversation a human graded bad: every consumer must count it as a failure
    h = g.new_object("erkenntnis", "Restart the agent after the upgrade", ["tool:Bash"], {"quelle": "t"})
    e = g.new_object("erfahrung", "Bash ok", ["tool:Bash", "ok:ja"], {"vorher": {"reize": ["tool:Bash"], "gezeigt": [h.id]}})
    with g.lock:
        g.db().execute("UPDATE objekt SET gespraech = ? WHERE id = ?", ("42", e.id))
        g.db().commit()
    g.new_object("bewertung", "human grade", ["scorer:mensch"], {"scorer": "mensch", "ziel": "42", "note": 0.0})
    router = [(y, w) for _f, y, o, w in learning.weighted_observations() if o == e.id]
    assert router and all(y == 0 and w == 3.0 for y, w in router)
    rows = [(tool, ok, per) for tool, ok, _shown, per in bandit._observations()]
    assert rows == [("Bash", False, {h.id: (0, 3.0)})]
    metrics._GRADES["db"] = None
    assert metrics._ok(g.load(e.id)) is False
