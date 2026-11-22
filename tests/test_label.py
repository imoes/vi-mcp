"""0.56.0: one label for router, bandit and metrics (scorer.label), weighted by its source."""
from vi_mcp import bandit, learning, metrics, scorer
from vi_mcp import memory as g


def test_label_order_and_weights():
    grades = {"7": {"note": 0.2, "quelle": "model", "gewicht": 0.18}, "8": {"note": 0.1, "quelle": "human", "gewicht": 3.0}}
    d = {"score": {"note": 1.0}, "feedback": {"erkenntnis:a": -1}}
    assert scorer.label(d, True, None, {}, hint="erkenntnis:a") == (0, 2.0, "rueckmeldung")  # feedback on this hint beats everything
    assert scorer.label(d, True, "8", grades) == (0, 3.0, "human")  # a bad human grade fails the whole conversation
    assert scorer.label(d, True, "7", grades) == (0, 0.18, "model")  # an uncalibrated model grade counts, but little
    assert scorer.label(d, False, None, grades) == (1, 1.0, "code")  # the code stage beats the tool's own outcome
    assert scorer.label({}, False, None, grades) == (0, 1.0, "ok")
    assert scorer.label({}, None, None, grades) is None


def test_grade_details_weigh_uncalibrated_model_grades(gd):
    g.new_object("rating", "model grade", ["scorer:model"], {"scorer": "model", "target": "5", "note": 0.25, "certainty": "high"})
    g.new_object("rating", "model grade", ["scorer:model"], {"scorer": "model", "target": "6", "note": 0.25, "certainty": "low"})
    g.new_object("rating", "human grade", ["scorer:human"], {"scorer": "human", "target": "6", "note": 0.9})
    d = scorer.grade_details()
    assert d["5"] == {"note": 0.25, "quelle": "model", "gewicht": round(scorer.WEIGHT["model"] * 1.0 * scorer.UNCALIBRATED, 3)}
    assert d["6"]["quelle"] == "human" and d["6"]["gewicht"] == 3.0  # the human grade wins


def test_router_bandit_and_metrics_see_the_same_label(gd):
    # an action whose tool succeeded, in a conversation a human graded bad: every consumer must count it as a failure
    h = g.new_object("insight", "Restart the agent after the upgrade", ["tool:Bash"], {"source": "t"})
    e = g.new_object("experience", "Bash ok", ["tool:Bash", "ok:yes"], {"before": {"triggers": ["tool:Bash"], "shown": [h.id]}})
    with g.lock:
        g.db().execute("UPDATE object SET conversation = ? WHERE id = ?", ("42", e.id))
        g.db().commit()
    g.new_object("rating", "human grade", ["scorer:human"], {"scorer": "human", "target": "42", "note": 0.0})
    router = [(y, w) for _f, y, o, w in learning.weighted_observations() if o == e.id]
    assert router and all(y == 0 and w == 3.0 for y, w in router)
    rows = [(tool, ok, per) for tool, ok, _shown, per in bandit._observations()]
    assert rows == [("Bash", False, {h.id: (0, 3.0)})]
    metrics._GRADES["db"] = None
    assert metrics._ok(g.load(e.id)) is False


def test_adopted_hint_becomes_a_positive_label(gd):
    # 0.59.0: a distinctive token of a shown hint (here the key path) taken over into a later successful action = implicit "helped"
    from vi_mcp import intuition, session
    h = g.new_object("insight", "ssh to the LLM host only with ssh -i ~/.ssh/llm.key -o BatchMode=yes", ["tool:Bash"], {"source": "t"}, instance="a")
    s = session.begin("a", "t")
    with session.on_behalf(s):
        e1 = g.new_object("experience", "Bash ssh", ["tool:Bash", "ok:no"], {"args": {"command": "ssh llm"}, "before": {"shown": [h.id]}},
                          instance="a", conversation=s.serial)
        e2 = g.new_object("experience", "Bash ssh -i", ["tool:Bash", "ok:yes"], {"args": {"command": "ssh -i ~/.ssh/llm.key llm"}},
                          instance="a", conversation=s.serial)
    assert intuition.adopted(g.load(e2.id)) == [h.id]
    assert g.load(e1.id).data["used"] == [h.id]
    # 22.11.2026: weight 0 (placebo check failed) — the pair keeps its other label (here the failed action's ok tag), data.used stays
    assert scorer.WEIGHT["genutzt"] == 0.0
    assert scorer.label(g.load(e1.id).data, False, None, {}, hint=h.id) == (0, scorer.WEIGHT["ok"], "ok")
    assert intuition.adopted(g.load(e2.id)) == []  # counted once
    assert intuition.distinctive_tokens("see it-aikb-api docs --verbose /etc/x/y.conf") == frozenset({"--verbose", "/etc/x/y.conf"})


def test_adoption_counts_again_only_with_a_positive_weight(gd, monkeypatch):
    """The branch itself stays: should the heuristic pass a placebo check one day, a positive weight brings it back."""
    data = {"before": {"shown": ["insight:h"]}, "used": ["insight:h"]}
    assert scorer.label(data, False, None, {}, hint="insight:h") == (0, scorer.WEIGHT["ok"], "ok")
    monkeypatch.setitem(scorer.WEIGHT, "genutzt", 1.5)
    assert scorer.label(data, False, None, {}, hint="insight:h") == (1, 1.5, "genutzt")
