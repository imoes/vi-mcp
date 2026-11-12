"""0.55.0: the measuring instrument for the search — page-level metrics, variants that only read."""
import json

from vi_mcp import evaluation, memory as g


def test_query_metrics_one_relevant_page():
    m = evaluation.query_metrics(["a", "b", "t"], "t")
    assert m["rang"] == 3 and abs(m["rr"] - 1 / 3) < 1e-9 and not m["hit1"] and m["hit5"] and m["hit10"]
    assert abs(m["ndcg10"] - 0.5) < 1e-9  # 1 / log2(4)
    assert evaluation.query_metrics(["a"] * 0 + [f"x{i}" for i in range(12)] + ["t"], "t")["rr"] == 0.0  # beyond rank 10 counts 0


def test_page_ranking_counts_a_page_once(gd):
    a = g.new_object("erkenntnis", "Part 1 of the backup page", ["thema:backup"], {"quelle": "https://wiki.example.org/p/1 · Version 3"})
    b = g.new_object("erkenntnis", "Part 2 of the backup page", ["thema:backup"], {"quelle": "https://wiki.example.org/p/1 · Version 3"})
    c = g.new_object("erkenntnis", "Something own", ["thema:backup"], {"quelle": "session 12.11."})
    assert evaluation.page_ranking([a.id, b.id, c.id]) == ["https://wiki.example.org/p/1", c.id]


def test_run_measures_without_reinforcing(gd, tmp_path):
    o = g.new_object("erkenntnis", "Borg needs BORG_PASSCOMMAND for unattended backup runs", ["tool:borg"], {"quelle": "test"})
    g.new_object("erkenntnis", "Nginx reload after certificate renewal", ["tool:nginx"], {"quelle": "test"})
    before = g.load(o.id).accesses
    qs = [{"frage": "How do I run borg backups unattended", "stichworte": "borg passcommand", "target": o.id, "group": o.id, "stratum": "own"},
          {"error": "generation failed", "target": "x"}]
    res = evaluation.run(qs, evaluation.fulltext)
    assert res["gesamt"]["n"] == 2 and res["je_stil"]["stichworte"]["hit1"] == 1.0
    assert g.load(o.id).accesses == before  # a measurement must not change what it measures
    assert "| fulltext | all | 2 |" in evaluation.table({"fulltext": res})
    (tmp_path / "q.json").write_text(json.dumps(qs))
    assert evaluation.load_questions(tmp_path / "q.json")[0]["target"] == o.id


def test_a_failing_variant_is_a_measured_failure(gd):
    def broken(_q, _n):
        raise RuntimeError("service down")
    res = evaluation.run([{"frage": "x", "target": "t", "group": "t"}], broken, styles=("frage",))
    assert res["gesamt"]["fehler"] == 1 and res["gesamt"]["mrr"] == 0.0 and "service down" in res["zeilen"][0]["fehler"]


def test_nightly_writes_questions_in_portions_and_measures_once_a_day(gd, tmp_path, monkeypatch):
    from vi_mcp import reflection, usage_stats
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(evaluation, "EVAL_N", 6)
    monkeypatch.setattr(evaluation, "EVAL_MIN", 4)
    objs = [g.new_object("erkenntnis", f"Service number {i} needs restart flag --force-{i} after the upgrade", [f"thema:svc{i}"],
                         {"quelle": f"session {i}"}) for i in range(8)]
    by_text = {o.text: o for o in objs}
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"frage": f"which flag does {user.split(chr(10))[0].split()[2]} need", "stichworte": [user.split()[2], "restart", "flag"]}))
    assert "not recorded yet" in usage_stats.measurement_lines()[0]
    r = evaluation.nightly()
    assert r["zustand"] == "gemessen" and r["fulltext"]["n"] == 12  # 6 targets × 2 styles; list keywords were joined
    assert r["hybrid"]["zustand"] == "uebersprungen"  # no embedding service here — named, not silently missing
    qs = evaluation.load_questions(tmp_path / "eval" / "recall.json")
    assert len(qs) == 6 and all(q["target"] in {o.id for o in by_text.values()} for q in qs) and qs[0]["stratum"].startswith("own:")
    assert oct((tmp_path / "eval" / "recall.json").stat().st_mode)[-3:] == "600"
    assert evaluation.nightly()["zustand"] == "heute_schon"
    assert "P Measurement: 1 day(s)" in "\n".join(usage_stats.measurement_lines())


def test_nightly_without_language_model_names_it(gd, tmp_path, monkeypatch):
    from vi_mcp import reflection
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(reflection, "ask_fn", None)
    monkeypatch.setattr(reflection, "config", {})
    r = evaluation.nightly()
    assert r["zustand"] == "fragen_fehlen" and r["erzeugung"]["zustand"] == "uebersprungen"
