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
