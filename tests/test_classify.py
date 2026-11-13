"""0.62.0: classify knowledge for the AI language — two prompt variants, schema checked here, labels as hashtags with their version."""
import json

import pytest

from vi_mcp import classify, reflection, tools, vil
from vi_mcp import memory as g


@pytest.fixture()
def llm(monkeypatch):
    """A stub model: answers per variant (recognised by its wording) from a table the test fills."""
    table = {}
    calls = []

    def ask(system, user):
        variant = "A" if system.startswith("You classify") else "B"
        title = user.split("Title: ", 1)[1].split("\n", 1)[0]
        calls.append((variant, title))
        ans = table[(variant, title)]
        return ans.pop(0) if isinstance(ans, list) else ans
    monkeypatch.setattr(reflection, "ask_fn", ask)
    return table, calls


def _ans(p, s="none", m="procedure", q=("how do I deploy?",)):
    return json.dumps({"primary": p, "secondary": s, "memory": m, "questions": list(q)})


def test_agreement_labels_disagreement_is_unsure_and_the_schema_is_checked_here(gd, llm):
    table, calls = llm
    a = g.new_object("erkenntnis", "deploy web1: stop, copy, start", ["thema:deploy"], {"quelle": "t", "inhalt": "1. stop 2. copy 3. start"})
    b = g.new_object("erkenntnis", "web1 runs nginx 1.24", ["thema:nginx"], {"quelle": "t"})
    c = g.new_object("erkenntnis", "broken answer", ["thema:x"], {"quelle": "t"})
    table[("A", a.text)] = _ans("how", "where")
    table[("B", a.text)] = _ans("how", "where")
    table[("A", b.text)] = _ans("what", m="fact")
    table[("B", b.text)] = _ans("where", m="fact")
    table[("A", c.text)] = [_ans("when"), _ans("when")]  # outside the enum twice: the endpoint did that on 13.11.2026
    table[("B", c.text)] = _ans("what", m="fact")
    r = classify.run(10, "test")
    assert (r["einig"], r["uneinig"], r["fehler"]) == (1, 1, 1) and "primary='when' outside the schema" in next(iter(r["gruende"]))
    a, b, c = g.load(a.id), g.load(b.id), g.load(c.id)
    assert {"answers:how", "answers:where", "memory:procedure"} <= set(a.hashtags)
    assert {"answers:unsure", "memory:fact"} <= set(b.hashtags)
    assert not any(t.startswith("answers:") for t in c.hashtags)  # an error is not a label: it stays pending, named
    assert a.data["klasse"]["version"]["prompt"] == classify.prompt_hash() and a.data["klasse"]["fragen"] == ["how do I deploy?"]
    assert a.changes[-1]["was"].startswith("classified")
    calls.clear()
    table[("A", c.text)] = _ans("what", m="fact")
    classify.run(10, "test")
    assert {t for _v, t in calls} == {c.text}  # labelled objects of the current version are not asked again


def test_labels_drive_the_ask_prior_and_the_tell_memory_kind(gd, llm):
    table, _calls = llm
    plain = g.new_object("erkenntnis", "web1 deploy log of last week", ["host:web1.example", "thema:deploy"], {"quelle": "t"}, importance=3)
    how = g.new_object("erkenntnis", "web1 deploy: the steps", ["host:web1.example", "thema:deploy"], {"quelle": "t"})
    for v in ("A", "B"):
        table[(v, plain.text)] = _ans("what", m="episode")
        table[(v, how.text)] = _ans("how")
    classify.run(10, "test")
    out = tools.call_tool("vi_recall", {"filter": "ask.how deploy @web1", "semantic": False, "reinforce": False, "format": "vil"}, "a", False)
    lines = out.splitlines()[1:]
    assert lines[0].startswith(f"tell.procedure {how.id}") and lines[1].startswith(f"tell.episode {plain.id}")
    assert vil.prior_rank(g.load(how.id), "how") == 0 and vil.prior_rank(g.load(plain.id), "how") == 2


def test_without_a_model_nothing_runs_and_sleep_needs_an_explicit_classify_model(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", None)
    monkeypatch.setattr(reflection, "config", {})
    g.new_object("erkenntnis", "x", ["thema:x"], {"quelle": "t"})
    assert classify.run(5)["zustand"] == "uebersprungen"
    assert classify.configured() is False and classify.per_sleep() == 10


def _clustered(n_per, rng, dim=16):
    """Objects whose vectors cluster by (answers, memory): how/procedure, what/fact, who/episode."""
    import numpy as np
    from vi_mcp import vector
    centers = {("how", "procedure"): 0, ("what", "fact"): 5, ("who", "episode"): 10}
    out = []
    for (a, m), c in centers.items():
        for i in range(n_per):
            o = g.new_object("erkenntnis", f"{a} object {i}", ["thema:x"], {"quelle": "t"})
            v = rng.normal(0, 0.3, dim)
            v[c:c + 3] += 3.0
            vector.save(o.id, v, "test")
            out.append((o, a, m))
    return out


def test_student_learns_the_labels_labels_new_objects_and_is_audited(gd, llm):
    import random
    import numpy as np
    table, calls = llm
    rng = np.random.default_rng(3)
    objs = _clustered(50, rng)
    for o, a, m in objs:
        for v in ("A", "B"):
            table[(v, o.text)] = _ans(a, m=m)
    assert classify.run(200, "test")["einig"] == 150
    r = classify.train_student("test")
    assert r["zustand"] == "aktiv" and r["n"] == 150 and r["koepfe"]["answers"]["genauigkeit_sicher"] >= 0.9
    assert r["koepfe"]["answers"]["klassen"] == ["how", "what", "who"] and "gewichte" not in r["koepfe"]["answers"]
    new = _clustered(4, rng)
    calls.clear()
    out = classify.run_with_student(5, "test", rng=random.Random(1))  # audit share 10 %: most by the student, a few checked by the LLM
    labelled = [g.load(o.id) for o, _a, _m in new]
    assert out["schueler"] + out["einig"] == 12 and out["schueler"] >= 8
    for o, (_x, a, m) in zip(labelled, new):
        assert f"answers:{a}" in o.hashtags and f"memory:{m}" in o.hashtags
    students = [o for o in labelled if o.data["klasse"]["zustand"] == "schueler"]
    assert students and all(o.data["klasse"]["version"]["modell"].startswith("student@") for o in students)
    by_llm = [o for o in labelled if o.data["klasse"]["zustand"] == "einig"]
    assert len(calls) == 2 * len(by_llm) == 2 * out["einig"]  # the LLM was asked only for the objects it labelled (audits or unsure)
    assert out["geprueft"] == out["einig"] and out["gleich"] == out["geprueft"]  # every LLM call here audited a sure student label
    assert g.load(classify.STUDENT).data["pruefung"] == {"geprueft": out["geprueft"], "gleich": out["gleich"]}


def test_student_needs_enough_agreed_labels_and_stays_test_below_the_gate(gd, llm):
    import numpy as np
    table, _calls = llm
    objs = _clustered(10, np.random.default_rng(4))
    for o, a, m in objs:
        for v in ("A", "B"):
            table[(v, o.text)] = _ans(a, m=m)
    classify.run(100, "test")
    r = classify.train_student("test")
    assert r["zustand"] == "zu_wenig" and "at least 120" in r["grund"]
    assert classify.student_label(objs[0][0]) is None  # no student → no label from it


def test_gold_from_people_only_measures_the_labels_and_the_truth_of_the_measurement(gd, llm):
    from vi_mcp import vil
    table, _calls = llm
    a = g.new_object("erkenntnis", "deploy steps", ["thema:deploy"], {"quelle": "t", "nuetzlich": {"ja": 9, "nein": 1, "n": 10}})
    b = g.new_object("erkenntnis", "web1 runs nginx", ["thema:nginx"], {"quelle": "t", "nuetzlich": {"ja": 1, "nein": 9, "n": 10}})
    for v in ("A", "B"):
        table[(v, a.text)] = _ans("how")
        table[(v, b.text)] = _ans("how", m="fact")  # the model is wrong about b
    classify.run(10, "test")
    with pytest.raises(ValueError, match="gold labels come from people only"):
        classify.set_gold(a.id, "how", "procedure", "claude-code", human=False)
    classify.set_gold(a.id, "how", "procedure", "max", human=True)
    classify.set_gold(b.id, "what", "fact", "max", human=True)
    r = classify.gold_report()
    assert r["gold"] == 2 and r["llm"] == {"n": 2, "richtig": 1, "unsure": 0, "genauigkeit": 0.5}
    assert r["je_klasse"] == {"how": {"n": 1, "richtig": 1}, "what": {"n": 1, "richtig": 0}}
    a, b = g.load(a.id), g.load(b.id)
    a.confirm("max", "checked on the host", instance="max")
    g.save(a)
    b.refute("max", "wrong host", instance="max")
    g.save(b)
    t = classify.truth_check({"max"})
    assert t == {"zustand": "gemessen", "auc": 1.0, "bestaetigt": 1, "widerlegt": 1}  # the measured weights agree with the person
    assert vil.weight_of(a)[0] > vil.weight_of(b)[0]
    assert classify.truth_check(set())["zustand"] == "keine_menschen"


def test_unlabelled_search_hits_migrate_first(gd, llm):
    """The user: unlabelled data a search returns is classified automatically — the old database migrates where it is used."""
    table, calls = llm
    old = [g.new_object("erkenntnis", f"old note {i} about nginx", ["tool:nginx"], {"quelle": "t"}) for i in range(3)]
    newer = g.new_object("erkenntnis", "a newer note nobody searched for", ["thema:x"], {"quelle": "t"})
    out = tools.call_tool("vi_recall", {"filter": "tool:nginx", "semantic": False, "reinforce": False}, "a", False)
    assert old[0].id in out and classify.queued() == 0  # a measurement (reinforce=false) changes nothing
    tools.call_tool("vi_recall", {"filter": "tool:nginx", "semantic": False}, "a", False)
    assert classify.queued() == 3
    assert set(classify.pending(3)) == {o.id for o in old}  # what was searched comes first
    assert newer.id in classify.pending(10) and classify.pending(10)[-1] == newer.id  # the queue comes before the newest
    for o in old:
        for v in ("A", "B"):
            table[(v, o.text)] = _ans("how")
    classify.run(3, "test")
    assert {t for _v, t in calls} == {o.text for o in old} and classify.queued() == 0
    assert all("answers:how" in g.load(o.id).hashtags for o in old)


def test_on_search_lets_an_active_student_label_at_once(gd, llm, monkeypatch):
    o = g.new_object("erkenntnis", "deploy steps", ["thema:deploy"], {"quelle": "t"})
    lab = {"zustand": "schueler", "answers": "how", "zweite": "none", "memory": "procedure", "fragen": [],
           "version": {"modell": "student@x", "prompt": classify.prompt_hash(), "schema": classify.SCHEMA_VERSION}}
    monkeypatch.setattr(classify, "student_label", lambda obj: lab)
    assert classify.on_search([g.load(o.id)]) == {"schueler": 1, "eingereiht": 0}
    assert "answers:how" in g.load(o.id).hashtags and classify.queued() == 0
    assert classify.on_search([g.load(o.id)]) == {"schueler": 0, "eingereiht": 0}  # labelled with the current version: nothing to do
