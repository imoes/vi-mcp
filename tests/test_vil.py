"""0.62.0: VIL — an AI asks the memory in a short, code-like language and gets the answer back in it."""
from datetime import datetime, timezone

import pytest

from vi_mcp import memory as g
from vi_mcp import tools, vil

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("text, act, qtype, flt, since, notes", [
    ("ask.how deploy @web1 #Vi-Mcp since:30d", "ask", "how", "deploy host:web1* thema:vi-mcp", "2026-10-14", 0),
    ("ask.why \"Origin null\" !#csrf @web1.example", "ask", "why", '"Origin null" !thema:csrf host:web1.example', None, 0),
    ("ask.where (#backup OR #restore) since:2026-11-01", "ask", "where", "(thema:backup OR thema:restore)", "2026-11-01", 0),
    ("ask.foo x", "ask", None, "x", None, 1),
    ("tell.fact x", "tell", None, "x", None, 0),
    ("host:web1 nginx", None, None, "host:web1 nginx", None, 0),       # no VIL: an ordinary filter, untouched
    ("mail user@host.example C#", None, None, "mail user@host.example C#", None, 0),
])
def test_parse(text, act, qtype, flt, since, notes):
    u = vil.parse(text, NOW)
    assert (u.act, u.qtype, u.filter, (u.since or "")[:10] or None, len(u.notes)) == (act, qtype, flt, since, notes)


def _seed():
    plain = g.new_object("erkenntnis", "deploy notes for web1: the deploy took 4 minutes", ["host:web1.example", "thema:deploy"],
                         {"quelle": "t"}, importance=3)
    how = g.new_object("erkenntnis", "deploy web1: stop, copy, start", ["host:web1.example", "thema:deploy", "art_wissen:loesung"],
                       {"quelle": "https://wiki.example/deploy", "nuetzlich": {"ja": 9, "nein": 1, "n": 10}})
    return plain, how


def test_ask_how_puts_the_answering_kind_first_and_answers_in_vil(gd):
    plain, how = _seed()
    out = tools.call_tool("vi_recall", {"filter": "ask.how deploy @web1", "semantic": False, "reinforce": False}, "a", False)
    ids = [line.split("]")[0].strip(" [") for line in out.splitlines()[1:] if line.startswith("  [")]
    assert ids[0] == how.id and plain.id in ids and "VIL ask.how" in out  # priority, not exclusion
    out = tools.call_tool("vi_recall", {"filter": "ask.how deploy @web1", "semantic": False, "reinforce": False, "format": "vil"}, "a", False)
    lines = out.splitlines()[1:]
    assert lines[0] == f'tell.procedure {how.id} "deploy web1: stop, copy, start" ev:measured w:0.83/10 src:"https://wiki.example/deploy"'
    assert lines[1] == f'tell.fact {plain.id} "deploy notes for web1: the deploy took 4 minutes" ev:unknown w:0.5/0 src:"t"'


def test_since_other_acts_and_evidence(gd):
    plain, how = _seed()
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = '2025-01-01T00:00:00+00:00', zuletzt = '2025-01-01T00:00:00+00:00' WHERE id = ?", (plain.id,))
        g.db().commit()
    out = tools.call_tool("vi_recall", {"filter": "ask.what deploy since:30d", "semantic": False, "reinforce": False}, "a", False)
    assert plain.id not in out and how.id in out and "1 older hit(s) left out" in out
    with pytest.raises(tools.Rejected, match="never run from a message"):
        tools.call_tool("vi_recall", {"filter": "do restart @web1", "semantic": False}, "a", False)
    foreign = g.new_object("erkenntnis", "imported", ["thema:x"], {"quelle": "t"}, instance="p2p-vi-abc")
    llm = g.new_object("erkenntnis", "derived", ["thema:x", "herkunft:schlaf-llm"], {"quelle": "sleep"})
    assert [vil.evidence_of(o) for o in (g.load(how.id), g.load(plain.id), foreign, llm)] == ["measured", "unknown", "hearsay", "inferred"]
    doc = g.new_object("erkenntnis", "documented", ["thema:x"], {"quelle": "https://docs.example/x"})
    assert vil.evidence_of(doc) == "documented"
