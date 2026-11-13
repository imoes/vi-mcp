"""0.62.0: training data from the memory — the goal: a VI out of the incubator fine-tunes an AI."""
import json

from vi_mcp import dataset, evaluation
from vi_mcp import memory as g


def _k(text, tags=(), yes=0.0, no=0.0, **kw):
    data = {"quelle": kw.pop("quelle", "https://docs.example/x"), "inhalt": kw.pop("inhalt", f"details of {text}"),
            "nuetzlich": {"ja": yes, "nein": no, "n": int(yes + no)}, **kw.pop("data", {})}
    return g.new_object(kw.pop("kind", "erkenntnis"), text, list(tags) or ["thema:x"], data, visibility=kw.pop("visibility", "intern"),
                        instance=kw.pop("instance", "a"), **kw)


def test_export_writes_qa_kto_dpo_with_datasheet_and_holds_out_the_evaluation(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    good = _k("restart nginx with systemctl reload, not restart", ["tool:nginx", "thema:reload"], 9, 1,
              data={"klasse": {"answers": "how", "memory": "procedure", "fragen": ["Wie lade ich nginx neu?", "nginx reload ohne Ausfall?"]}})
    bad = _k("nginx needs a full restart after config changes", ["tool:nginx", "thema:reload"], 1, 9)
    held = _k("the evaluation target", ["thema:y"])
    _k("private note", visibility="privat")
    _k("def f(): pass", ["art_wissen:code", "datei:x.py"])
    g.new_object("erfahrung", "Bash ok", ["tool:Bash"], {"quelle": "t"})
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "recall.json").write_text(json.dumps([{"target": held.id, "group": "g", "stratum": "s", "frage": "nginx reload ohne Ausfall?",
                                                                  "stichworte": "nginx"}]))
    out = tmp_path / "ds"
    m = dataset.export(out)
    qa = [json.loads(line) for line in (out / "qa.jsonl").read_text().splitlines()]
    questions = [x["messages"][0]["content"] for x in qa]
    assert "Wie lade ich nginx neu?" in questions and "nginx reload ohne Ausfall?" not in questions  # equal to an evaluation question
    assert all(x["meta"]["id"] != held.id for x in qa) and m["held_out"] == 1
    assert not any("private note" in q or "def f()" in q or "Bash ok" in q for q in questions)
    a = next(x for x in qa if x["meta"]["id"] == good.id)
    assert a["messages"][1]["content"].endswith("Source: https://docs.example/x") and a["meta"]["question_source"] == "doc2query"
    assert m["skipped"] == {"code piece (a copy of a repository)": 1, "target of the fixed question set (held out for evaluation)": 1,
                            "question equal to an evaluation question": 1}
    kto = [json.loads(line) for line in (out / "kto.jsonl").read_text().splitlines()]
    assert {(x["meta"]["id"], x["label"]) for x in kto} == {(good.id, True), (bad.id, False)}
    dpo = [json.loads(line) for line in (out / "dpo.jsonl").read_text().splitlines()]
    assert dpo and all(x["chosen"] == good.text and x["rejected"] == bad.text for x in dpo)
    sheet = (out / "DATASHEET.md").read_text()
    assert "## Left out, with the reason" in sheet and "held out" in sheet and "Known gaps" in sheet
    assert all((out / f).stat().st_mode & 0o077 == 0 for f in ("qa.jsonl", "kto.jsonl", "dpo.jsonl", "manifest.json", "DATASHEET.md"))
    assert (out.stat().st_mode & 0o077) == 0


def test_scrubbing_is_audited_and_an_index_can_be_exported_alone(gd, tmp_path, monkeypatch):
    from vi_mcp import anonymize
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    o = _k("deploy note", ["thema:deploy"], index="proj")
    _k("other project", ["thema:deploy"], index="other")
    # a credential that slipped past the scrubber at save time (e.g. a pattern added later) — simulated by writing it directly
    with g.lock:
        g.db().execute("UPDATE objekt SET daten = ? WHERE id = ?", (json.dumps({**o.data, "inhalt": "password=hunter2secret"}), o.id))
        g.db().commit()
    m = dataset.export(tmp_path / "ds", "proj")
    qa = (tmp_path / "ds" / "qa.jsonl").read_text()
    assert m["counts"]["qa"] == 1 and "other project" not in qa
    assert anonymize.without_secrets("password=hunter2secret") == "<geheimnis>"
    agentic = (tmp_path / "ds" / "agentic.jsonl").read_text()
    assert "hunter2secret" not in qa
    assert "hunter2secret" not in agentic
    assert "<geheimnis>" in qa
    assert m["scrubbed"]["answer"] == 1 + m["counts"]["agentic"]  # once in qa, once per agentic trajectory that answers from it


def test_agentic_trajectories_search_the_vi_in_vil_relax_once_and_never_teach_a_miss(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    direct = _k("restart nginx on web1 with reload", ["host:web1.example", "thema:nginx"],
                data={"klasse": {"answers": "how", "memory": "procedure", "fragen": ["How do I restart nginx on web1?"]}})
    relaxed = _k("the backup runs nightly at two", ["host:db1.example", "thema:backup"],
                 data={"klasse": {"answers": "what", "memory": "fact", "fragen": ["Wann läuft die Sicherung?"]}})  # no question word in the text
    _k("a lonely fact without tags matching its question", ["quelle_art:test"], data={"klasse": {"fragen": ["Quasselstrippe Zauberwort?"]}})
    _k("secret db1 backup password location", ["host:db1.example", "thema:backup"], visibility="privat", instance="b")
    data = dataset.build()
    by = {x["meta"]["id"]: x for x in data["agentic"]}
    a = by[direct.id]
    assert a["meta"]["steps"] == 1 and a["tools"][0]["function"]["name"] == "vi_recall"
    call = a["messages"][1]["tool_calls"][0]["function"]
    assert call["arguments"] == {"filter": "ask.how restart nginx web1 @web1.example #nginx", "format": "vil"}
    assert a["messages"][2]["role"] == "tool" and f"tell.fact {direct.id}" in a["messages"][2]["content"]  # memory: comes from the hashtag, not from daten.klasse
    assert a["messages"][-1]["content"].endswith(f"(from {direct.id})")
    b = by[relaxed.id]
    assert b["meta"]["steps"] == 2  # the first question found nothing, the relaxed one (tags only) found the target
    assert b["messages"][3]["tool_calls"][0]["function"]["arguments"]["filter"] == "ask.what @db1.example #backup"
    assert "secret" not in json.dumps(b)  # someone's private object never appears in a tool answer
    assert data["skipped"]["agentic: the search did not find the target (no example teaches a wrong answer)"] == 1
    m = dataset.export(tmp_path / "ds")
    assert m["counts"]["agentic"] == 2 and len((tmp_path / "ds" / "agentic.jsonl").read_text().splitlines()) == 2
