"""0.73.0: two vi_recall pitfalls found by reading the code (26.11.2026), each proven by a test before the fix.
(a) A natural question starting with an act word ("Do I still have …?", "Rate the …") was parsed as a VIL act and refused.
(b) index:<name> written in the filter restricted the full-text half of a hybrid search but not its vector half."""
import hashlib
import re

import pytest

from vi_mcp import session, tools, vector, vil
from vi_mcp import memory as g

DIM = 64


def _embed(texts):
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            v[int(hashlib.sha256(w.encode()).hexdigest()[:8], 16) % DIM] += 1.0
        out.append(v)
    return out


@pytest.mark.parametrize("text", ["Do I still have a backup of web1?", "Tell me which host runs the shop", "Rate the deploy of web1",
                                  "Promise checks for web1?", "Def of the gateway on web1", "do i still have a backup of web1?"])
def test_a_natural_question_is_no_vil_act(text):
    assert vil.parse(text).act is None and vil.parse(text).filter == text


def test_vil_acts_stay_acts():
    assert vil.parse("tell.fact x").act == "tell" and vil.parse("do restart @web1").act == "do" and vil.parse("ask.how x").act == "ask"


def test_vi_recall_answers_a_question_that_starts_with_do(gd):
    o = g.new_object("insight", "backup of web1 is kept for 30 days", ["host:web1.example"], {"source": "t"})
    out = str(tools.call_tool("vi_recall", {"filter": "Do I still have a backup of web1?", "semantic": False, "reinforce": False}, "a", False))
    assert o.id in out
    with pytest.raises(tools.Rejected, match="never run from a message"):  # the VIL act is still refused
        tools.call_tool("vi_recall", {"filter": "do restart @web1", "semantic": False}, "a", False)


def test_index_in_the_filter_restricts_both_halves_of_a_hybrid_search(gd, monkeypatch):
    monkeypatch.setattr(vector, "embed_fn", _embed)
    monkeypatch.setattr(vector, "config", {"model": "fake"})
    inside = g.new_object("insight", "Runbook gateway restart for the shop", ["topic:shop"], {}, instance="a", visibility="internal")
    inside.idx = "project-x"
    g.save(inside)
    outside = [g.new_object("insight", f"gateway restart shop notes {i}", ["topic:shop"], {}, instance="a", visibility="internal")
               for i in range(5)]
    vector.catch_up(max_s=600)
    s = session.begin("a", "test")
    with session.on_behalf(s):
        by_arg = str(tools.call_tool("vi_recall", {"filter": "gateway restart shop", "index": "project-x", "limit": 10,
                                                   "reinforce": False}, "a", True))
        in_text = str(tools.call_tool("vi_recall", {"filter": "index:project-x gateway restart shop", "limit": 10,
                                                    "reinforce": False}, "a", True))
    assert "hybrid" in in_text.splitlines()[0]  # the vector half ran
    for out in (by_arg, in_text):
        assert inside.id in out and not any(o.id in out for o in outside), out
