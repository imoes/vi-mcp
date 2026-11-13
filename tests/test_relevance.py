"""0.62.0: a language model grades real searches (UMBRELA 0–3) — the relevance label clicks could not give."""
import json

import pytest

from vi_mcp import evaluation, reflection, relevance, tools
from vi_mcp import memory as g


@pytest.fixture()
def grader(monkeypatch):
    """A stub assessor: grades per passage title from a table; records what it was sent."""
    table, sent = {}, []

    def ask(system, user):
        sent.append(user)
        assert system == relevance.SYSTEM
        passages = [p.split("\n", 1)[0].split(": ", 1)[1] for p in user.split("\n\n")[1:]]
        if table.get("_bad"):
            return json.dumps({"grades": [{"n": 1, "grade": 7}]})
        return json.dumps({"grades": [{"n": i, "grade": table.get(t, 0)} for i, t in enumerate(passages, 1)]})
    monkeypatch.setattr(reflection, "ask_fn", ask)
    return table, sent


def _search(q):
    return tools.call_tool("vi_recall", {"filter": q, "semantic": False}, "agent", False)


def test_free_text_searches_are_graded_and_reported(gd, grader):
    table, sent = grader
    a = g.new_object("erkenntnis", "deploy web1: stop the service, copy, start", ["host:web1.example", "thema:deploy"], {"quelle": "t"})
    b = g.new_object("erkenntnis", "deploy notes: the deploy of web1 took 4 minutes", ["host:web1.example", "thema:deploy"], {"quelle": "t"})
    secret = g.new_object("erkenntnis", "deploy web1 private trick", ["host:web1.example", "thema:deploy"], {"quelle": "t"},
                          instance="agent", visibility="privat")
    table[a.text] = 3
    table[b.text] = 1
    _search("deploy web1")
    _search("host:web1.example")  # a pure tag lookup is exact by construction: never judged
    assert len(relevance.pending(10)) == 1
    out = relevance.run(5, "test")
    assert out["beurteilt"] == 1 and out["fehler"] == 0 and len(sent) == 1
    assert secret.text not in sent[0]  # private knowledge never goes to the model
    with g.lock:
        rows = g.db().execute("SELECT objekt_id, note, grund FROM relevanz_urteil ORDER BY rang").fetchall()
    got = {oid: (note, why) for oid, note, why in rows}
    assert got[a.id] == (3, None) and got[b.id] == (1, None) and got[secret.id] == (None, "private or gone: not sent")
    r = relevance.report()
    assert r["suchen"] == 1 and r["mit_relevantem"] == 1 and r["ndcg10"] is not None
    assert relevance.pending(10) == []  # judged once
    assert "judged by the language model" in tools.call_tool("vi_stats", {"days": 1}, "agent", False)


def test_answers_outside_the_schema_are_named_not_stored_as_grades(gd, grader):
    table, sent = grader
    table["_bad"] = True
    g.new_object("erkenntnis", "nginx reload on web1", ["host:web1.example", "tool:nginx"], {"quelle": "t"})
    _search("nginx reload")
    out = relevance.run(5, "test")
    assert out["fehler"] == 1 and len(sent) == 2  # asked once more, then given up
    assert any("outside" in k or "passages" in k for k in out["gruende"])
    assert relevance.report()["fehler"] == 1 and relevance.report()["suchen"] == 0


def test_ndcg_and_validation():
    assert relevance.ndcg([3, 0, 1]) == pytest.approx(7.5 / (7 + 1 / 1.584962500721156), rel=1e-6)  # gain 2^g − 1, log2(rank + 1)
    assert relevance.ndcg([0, 0]) is None
    assert relevance.ndcg([1, 3]) < 1 and relevance.ndcg([3, 1]) == 1.0
    assert relevance.valid({"grades": [{"n": 1, "grade": 2}, {"n": 2, "grade": 0}]}, 2) is None
    assert relevance.valid({"grades": [{"n": 1, "grade": 2}]}, 2)
    assert relevance.valid({"grades": [{"n": 1, "grade": 4}]}, 1)


def test_without_a_model_nothing_runs(gd, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", None)
    monkeypatch.setattr(reflection, "config", {})
    from vi_mcp import classify
    monkeypatch.setattr(classify, "_config", lambda: {})
    assert relevance.run(3)["zustand"] == "uebersprungen"
    evaluation._log_table()


def test_grades_are_split_by_search_kind_with_and_without_the_reranker(gd):
    """0.63.0, found on production: grades of searches before and after the reranker was switched on were one number. The search kind
    now says whether it ran, and the report gives each kind its own numbers."""
    from vi_mcp import usage_stats
    assert usage_stats._hits("vi_recall", "3 objects for “x · default hybrid (embedding 9 ms, …; reranked 30 in 1800 ms)”")[1] == "hybrid+rerank"
    assert usage_stats._hits("vi_recall", "3 objects for “x · default hybrid (embedding 9 ms, …)”")[1] == "hybrid"
    relevance._table()
    rows = [("s1", "hybrid", 1, 0), ("s1", "hybrid", 2, 0), ("s2", "hybrid+rerank", 1, 3), ("s2", "hybrid+rerank", 2, 1)]
    with g.lock:
        for s, kind, rank, grade in rows:
            g.db().execute("INSERT INTO relevanz_urteil (suche, zeit, suche_zeit, anfrage, suchart, objekt_id, rang, note, version, grund) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)", (s, g.now(), g.now(), "q", kind, f"erkenntnis:{s}{rank}", rank, grade, "v", None))
        g.db().commit()
    r = relevance.report(1)
    assert r["je_art_werte"]["hybrid+rerank"] == {"suchen": 1, "rang1_beantwortet": 1, "nichts_relevant": 0}
    assert r["je_art_werte"]["hybrid"]["nichts_relevant"] == 1
    assert "hybrid+rerank: 1, rank 1 100 %, nothing 0 %" in relevance.line(1)
