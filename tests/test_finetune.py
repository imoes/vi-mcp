"""0.62.0: fine-tuning an AI with what a VI learned — the VI knows how; vi-mcp writes the kit and records the run, it trains nothing."""
import json
import py_compile

import pytest

from clingo_object import philosophy as ph
from vi_mcp import evaluation, finetune, tools
from vi_mcp import memory as g


@pytest.fixture()
def vi(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    for i in range(12):
        g.new_object("insight", f"knowledge {i}: how to deploy service {i}", ["topic:deploy"],
                     {"source": "t", "content": f"step one, step two for {i}", "class": {"questions": [f"how to deploy {i}?", f"deploy {i} steps?"]}},
                     visibility="internal", instance="a")
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "recall.json").write_text(json.dumps([{"target": "erkenntnis:none", "group": "g", "stratum": "s",
                                                                  "frage": "how is the database backed up?", "stichworte": "backup database"}]))
    return tmp_path


def test_plan_names_an_immature_vi_and_the_missing_base_model(vi):
    p = finetune.plan()
    assert p["zustand"] == "im_inkubator" and p["fehlt"] and p["grundmodell"] is None
    text = "\n".join(finetune.plan_lines(p))
    assert "still in the incubator" in text and "trial run" in text and "--force" in text
    out = tools.call_tool("vi_finetune", {}, "a", False)
    assert "still in the incubator" in out and "Steps:" in out
    assert "LoRA" in tools.call_tool("vi_finetune", {"action": "guide"}, "a", False)
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_finetune", {}, "offen", False)  # needs a token
    assert "call vi_finetune" in tools.RULES  # "I want to fine-tune" is enough for an AI on vi-mcp


def test_kit_writes_data_split_and_valid_scripts_without_running_anything(vi):
    with pytest.raises(ValueError, match="no base model"):
        finetune.kit(str(vi / "k0"), force=True)
    with pytest.raises(ValueError, match="still in the incubator"):
        finetune.kit(str(vi / "k1"), base_model="Qwen/Qwen3-4B")
    r = finetune.kit(str(vi / "kit"), base_model="Qwen/Qwen3-4B", force=True)
    d = vi / "kit"
    for f in ("dataset/qa.jsonl", "dataset/DATASHEET.md", "split/train.jsonl", "split/test.jsonl", "train.py", "evaluate.py", "convert.sh",
              "README-FINETUNE.md", "run.json", "eval_questions.json", "training_runtime.py", "requirements-train.txt"):
        assert (d / f).exists(), f
    train = {json.loads(x)["meta"]["id"] for x in (d / "split/train.jsonl").read_text().splitlines()}
    test = {json.loads(x)["meta"]["id"] for x in (d / "split/test.jsonl").read_text().splitlines()}
    assert train and test and not (train & test)  # split by object: no object on both sides
    assert r["split"]["train"] + r["split"]["test"] == 24 and r["eval_fragen"] == 1
    for f in ("train.py", "evaluate.py", "heldout_loss.py"):
        py_compile.compile(str(d / f), doraise=True)
        assert '"max_tokens"' not in (d / f).read_text() and "max_new_tokens" not in (d / f).read_text() and (d / f).stat().st_mode & 0o777 == 0o700
    assert (d / "run.json").stat().st_mode & 0o077 == 0 and json.loads((d / "run.json").read_text())["base_model"] == "Qwen/Qwen3-4B"


def test_documents_without_a_question_become_grounded_synthetic_pairs_never_echo_rows(vi, monkeypatch):
    """14.11.2026: 96 % of the first production run's SFT rows were "question = the document's beginning" — the model learned to echo.
    Knowledge without stored pairs goes to documents.jsonl; synth_qa.py keeps only grounded pairs (qa_pairs.py, the server's definition),
    holds one per document out as its probe, and `finetune split` puts pairs and probes of trained objects into the split. probe.py
    judges and unblinds; record names the probe."""
    import http.server
    import subprocess
    import sys
    import threading
    for i in range(6):
        g.new_object("insight", f"backup of db{i} runs nightly", ["topic:backup"],
                     {"source": f"https://wiki.example/db{i}", "content": f"The backup of db{i}.example runs at 02:00 with borg to /srv/backup/db{i}."},
                     visibility="internal", instance="a")
    d = vi / "kit"
    finetune.kit(str(d), base_model="Qwen/Qwen3-4B", force=True)
    docs = [json.loads(x) for x in (d / "dataset/documents.jsonl").read_text().splitlines()]
    qa = [json.loads(x) for x in (d / "dataset/qa.jsonl").read_text().splitlines()]
    assert len(docs) == 18 and all(x["meta"]["question_source"] == "doc2query" for x in qa)  # no stored pairs yet: every object
    assert not any(r["messages"][0]["content"].startswith("backup of db") for r in qa)  # never the text as its own question
    script = (d / "synth_qa.py").read_text()
    for f in ("synth_qa.py", "qa_pairs.py", "probe.py"):
        py_compile.compile(str(d / f), doraise=True)
    assert "max_tokens" not in script and '"enable_thinking": False' in script and (d / "synth_qa.py").stat().st_mode & 0o777 == 0o700
    assert (d / "qa_pairs.py").read_text() == (finetune.Path(finetune.__file__).with_name("qa_pairs.py")).read_text()  # one definition
    assert "max_tokens" not in (d / "probe.py").read_text()
    import re
    calls, support_calls = [], []

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            system, doc = body["messages"][0]["content"], body["messages"][1]["content"]
            if system.startswith("You check training data"):  # qa-v4 support check: everything supported here
                calls.pop()
                support_calls.append(body)
                n_pairs = len(re.findall(r"^\d+\. Q:", doc, re.M))
                content = json.dumps({"verdicts": [{"i": i, "supported": True, "reason": "stated"} for i in range(n_pairs)]})
            elif system.startswith("You grade answers"):
                content = json.dumps({"A": "correct", "B": "wrong", "reason": "A names the time"})
            elif "db" not in doc:
                content = json.dumps({"pairs": []})
            else:
                n = doc.split("db", 1)[1][0]
                more = [{"question": f"Which tool backs up db{n}.example at 02:00?", "answer": "borg."}] if "up to 7 questions" in system else []
                pairs = more + [{"question": f"At what time is db{n}.example backed up each night?", "answer": "At 02:00 with borg."},
                                {"answer": "a pair without a question is rejected, never a crash"},
                                {"question": f"When does the backup of db{n}.example run?", "answer": f"At 02:00 with borg to /srv/backup/db{n}."},
                                {"question": f"What does the document say about db{n}?", "answer": f"The backup of db{n}.example runs at 02:00."},
                                {"question": f"Who owns db{n}.example in the finance team?", "answer": "Alice Example from finance owns it since 2019."}]
                content = "```json\n" + json.dumps({"pairs": pairs}) + "\n```"
            out = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        run = lambda: subprocess.run([sys.executable, "synth_qa.py", "--url", url, "--model", "m", "--workers", "2"], cwd=d,
                                     capture_output=True, text=True, timeout=60)
        p = run()
        assert p.returncode == 0, p.stderr
        assert all("max_tokens" not in c and c["chat_template_kwargs"] == {"enable_thinking": False} for c in calls) and len(calls) == 18
        synth = [json.loads(x) for x in (d / "dataset/qa_synth.jsonl").read_text().splitlines()]
        probes = [json.loads(x) for x in (d / "dataset/probe_synth.jsonl").read_text().splitlines()]
        assert len(synth) == 6 and len(probes) == 6 and all(r["meta"]["question_source"] == "synthetic" and r["meta"]["generator"] == "m" for r in synth)
        good = ("At what time is db", "When does the backup")
        for r in synth:  # per document: one grounded pair trained, the other held out as its probe — never both on one side
            pr = next(x for x in probes if x["id"] == r["meta"]["id"])
            assert r["messages"][0]["content"].startswith(good) and pr["question"].startswith(good)
            assert r["messages"][0]["content"] != pr["question"] and pr["meta"]["question_source"] == "probe"
        assert all(r["messages"][1]["content"].split("Source: ")[1].startswith("https://wiki.example/db") for r in synth)
        report = json.loads((d / "synth_report.json").read_text())
        assert report["pairs"] == 6 and report["probes"] == 6 and len(support_calls) == 6  # every kept pair went through the check
        assert report["rejected"] == {"refers to the document instead of its subject": 6, "a number the document does not state": 6, "length": 6}
        assert run().returncode == 0 and len(calls) == 18  # resumable: done documents are not asked again
        # --more asks chosen documents again for further, varied pairs; a repeat of the probe is rejected, a repeat of a pair too
        ids = sorted(r["meta"]["id"] for r in synth)
        (d / "more.txt").write_text("\n".join(ids[:2]) + "\n")
        p = subprocess.run([sys.executable, "synth_qa.py", "--url", url, "--model", "m", "--pairs", "7", "--more", "more.txt"], cwd=d,
                           capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        assert len(calls) == 20 and "up to 7 questions" in calls[-1]["messages"][0]["content"]
        synth = [json.loads(x) for x in (d / "dataset/qa_synth.jsonl").read_text().splitlines()]
        assert sorted(r["meta"]["id"] for r in synth if r["messages"][0]["content"].startswith("Which tool")) == ids[:2]
        report = json.loads((d / "synth_report.json").read_text())
        assert report["rejected"]["too close to a held-out evaluation question"] == 2 and report["rejected"]["duplicate question"] == 2
        assert report["pairs_asked"] == 7 and report["probes"] == 0  # a document keeps its one probe
        split = finetune.resplit(str(d))
        assert split["train"] + split["test"] == 24 + 8
        assert sum(side.get("synthetic", 0) for side in split["qa_question_sources"].values()) == 8
        assert split["probe"]["trained_objects"] + split["probe"]["objects_not_trained"] == 6
        trained = {json.loads(x)["meta"]["id"] for x in (d / "split/train.jsonl").read_text().splitlines()}
        kept = [json.loads(x) for x in (d / "split/probe.jsonl").read_text().splitlines()]
        assert len(kept) == split["probe"]["trained_objects"] and all(x["id"] in trained for x in kept)
        rj = json.loads((d / "run.json").read_text())
        assert rj["qa_synth_sha256"] and rj["probe_synth_sha256"] and rj["split"] == split
        assert finetune.main(["split", str(d)]) == 0
        # probe.py judge + summarize on recorded answers (answering needs the model; the files are what `probe.py answer` writes)
        assert kept, "the seeded split keeps at least one db object on the train side"
        (d / "probe").mkdir()
        with open(d / "probe/answers_blind.jsonl", "w") as f, open(d / "probe/ab_key.jsonl", "w") as k:
            for x in kept:
                f.write(json.dumps({"id": x["id"], "group": x["meta"]["group"], "question": x["question"], "reference": x["answer"],
                                    "A": "At 02:00.", "A_finish": "stop", "B": "I do not know.", "B_finish": "stop"}) + "\n")
                k.write(json.dumps({"id": x["id"], "A": "tuned", "B": "base"}) + "\n")
        import hashlib as _h
        p = subprocess.run([sys.executable, "probe.py", "summarize"], cwd=d, capture_output=True, text=True, timeout=60)
        assert p.returncode != 0  # nothing judged yet, and no answer run recorded: refused, never a decision
        (d / "probe/answer_run.json").write_text(json.dumps({"probe_sha256": _h.sha256((d / "split/probe.jsonl").read_bytes()).hexdigest()}))
        p = subprocess.run([sys.executable, "probe.py", "judge", "--url", url, "--model", "m"], cwd=d, capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        assert all("max_tokens" not in c for c in calls)
        p = subprocess.run([sys.executable, "probe.py", "summarize"], cwd=d, capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        ev = json.loads((d / "probe/probe_eval.json").read_text())
        assert ev["grades"]["tuned"]["correct"] == len(kept) and ev["grades"]["base"]["wrong"] == len(kept)
        assert ev["judges"] == ["m"] and "self-preference" in ev["warning"]  # the judge wrote the probes: named, not hidden
    finally:
        srv.shutdown()
    (d / "out" / "sft").mkdir(parents=True)
    (d / "out" / "sft" / "adapter_model.safetensors").write_bytes(b"weights")
    o = finetune.record(str(d))
    assert "knowledge probe" in o.text and o.data["wissensprobe"]["n"] == len(kept) and o.mode == "test"  # the probe is no adoption gate


def test_server_stores_training_pairs_with_a_probe_and_the_export_uses_them(vi, monkeypatch):
    """0.65.0 — the user: "die Daten müssen von Anfang an in der richtigen Art und Weise gespeichert sein". The server writes grounded
    pairs and one probe question onto each knowledge object (sleep step 8i / vi-mcp classify --pairs); the export trains the pairs,
    holds the probe out, and treats pairs of changed knowledge as stale."""
    from vi_mcp import classify, dataset, qa_pairs, reflection
    asked = []

    def fake(system, user):
        if system == qa_pairs.SUPPORT_SYSTEM:
            return json.dumps({"verdicts": [{"i": i, "supported": True, "reason": "stated"} for i in range(user.count(". Q:"))]})
        asked.append(system)
        if "fail" in user:
            raise ConnectionError("model down")
        i = user.split("knowledge ", 1)[1].split(":", 1)[0]
        return json.dumps({"pairs": [{"question": f"How do I deploy service {i}?", "answer": f"step one, step two for {i}"},
                                     {"question": f"What are the steps to deploy service {i}?", "answer": "step one, step two"},
                                     {"question": "What does the document say?", "answer": "step one"}]})
    monkeypatch.setattr(reflection, "ask_fn", fake)
    secret = g.new_object("insight", "knowledge 99: private", ["topic:deploy"], {"content": "step one"}, visibility="private", instance="a")
    failing = g.new_object("insight", "knowledge fail: model down", ["topic:deploy"], {"content": "fail"}, visibility="internal", instance="a")
    assert secret.id not in classify.pairs_pending(100) and failing.id in classify.pairs_pending(100)
    r = classify.run_pairs(100, "test", workers=3)
    assert r["ok"] == 12 and r["error"] == 1 and r["pairs"] == 12 and r["probes"] == 12
    assert r["rejected"] == {"refers to the document instead of its subject": 12} and r["reasons"] == {"ConnectionError: model down": 1}
    assert asked[0] == qa_pairs.system_for() and "max_tokens" not in asked[0]
    assert classify.pairs_pending(100) == []  # a fresh failure waits a day instead of blocking every sleep
    o = g.load(failing.id)
    o.data["qa"]["time"] = "2020-01-01T00:00:00.000+00:00"
    g.save(o)
    assert classify.pairs_pending(100) == [failing.id]
    rep = classify.pairs_report()
    assert rep["ok"] == 12 and rep["error"] == 1 and rep["pairs"] == 12 and rep["probes"] == 12
    # changed knowledge: its pairs are stale — not exported, renewed by --stale
    ids = [x[0] for x in g.db().execute("SELECT id FROM object WHERE kind = 'insight' AND json_extract(data, '$.qa.state') = 'ok'")]
    changed = g.load(ids[0])
    changed.data["content"] = "step one, step two, step three"
    g.save(changed)
    assert changed.id in classify.pairs_pending(100, stale=True) and changed.id not in classify.pairs_pending(100)
    data = dataset.build(agentic=False)
    synthetic = [x for x in data["qa"] if x["meta"]["question_source"] == "synthetic"]
    assert len(synthetic) == 11 and len(data["probe"]) == 11 and all(x["meta"]["generator"] for x in synthetic)
    trained_q = {x["messages"][0]["content"] for x in data["qa"]}
    assert not any(p["question"] in trained_q for p in data["probe"])  # a probe is never trained
    assert any(d["meta"]["id"] == changed.id for d in data["documents"])
    assert data["pair_states"] == {"stored pairs used": 11, "stored training pairs are stale (the knowledge changed since): exported to documents.jsonl": 1,
                                   "stored training pairs in state error: exported to documents.jsonl": 1}
    m = dataset.export(vi / "ds")
    assert m["counts"]["probe"] == 11 and (vi / "ds" / "probe.jsonl").stat().st_mode & 0o777 == 0o600
    assert "probe.jsonl | 11" in (vi / "ds" / "DATASHEET.md").read_text()
    import types
    from vi_mcp import config
    monkeypatch.setattr(config, "load", lambda: types.SimpleNamespace(llm=None, db=vi / "vi.db"))  # never the person's real database
    assert classify.main(["--pairs", "--dry-run"]) == 0
    g.open_db(vi / "vi.db")  # main closes the database it opened


def test_record_keeps_the_lineage_and_adopts_only_what_measured_better(vi):
    finetune.kit(str(vi / "kit"), base_model="Qwen/Qwen3-4B", force=True)
    d = vi / "kit"
    with pytest.raises(ValueError, match="no trained adapter"):
        finetune.record(str(d))
    (d / "out" / "sft").mkdir(parents=True)
    (d / "out" / "sft" / "adapter_model.safetensors").write_bytes(b"weights")
    o = finetune.record(str(d))
    assert o.mode == "test" and "not evaluated" in o.text and o.data["adapter_sha256"]["sft"]
    (d / "eval.json").write_text(json.dumps({"base": 0.31, "tuned": 0.52, "n": 25, "better": 14, "worse": 3}))
    o = finetune.record(str(d))
    assert o.mode == "test"  # old word-overlap reports never authorize adoption
    import hashlib
    ev = {"base": 0.31, "tuned": 0.52, "n": 25, "better": 14, "worse": 3, "metric": "verified_task_success", "lower_95": -0.1, "decision": True, "p_one_sided": 0.006,
          "evaluation_set_sha256": hashlib.sha256((d / "split/test.jsonl").read_bytes()).hexdigest()}
    (d / "eval.json").write_text(json.dumps(ev))
    o = finetune.record(str(d))
    assert o.mode == "active" and "fine-tuned 0.52 vs base 0.31 on 25 held-out questions" in o.text
    assert o.data["dataset_manifest_sha256"] and o.data["incubator"]["zustand"] == "im_inkubator"


def test_grounding_counts_facts_not_function_words():
    """qa-v2 (15.11.2026): with qa-v1, real Qwen3.6-35B answers to six short German findings kept 1 of 25 pairs — "die, wurde, auf"
    counted as ungrounded, and "host"/"dns01" hidden in host:dns01.example.org were not found. Invented facts must still fail."""
    from vi_mcp import qa_pairs
    doc = ('Bekannter Fehler: dns01: erstmals www.bad-shop.example (6×) sinkholed — neue Schad-Domain in Serie — Filter: '
           'host:dns01.example.org bedrohung:"generic:www.bad-shop.example(789736897)"')
    q = "Welche Domain wurde auf dem Host dns01 sinkholed?"
    assert qa_pairs.check({"question": q, "answer": "Die Domain www.bad-shop.example wurde auf dem Host dns01 erstmals sinkholed."}, doc) is None
    assert qa_pairs.check({"question": q, "answer": "Die Domain wurde auf dns02.example.org am 2025-03-01 von 10.1.2.3 gemeldet."}, doc) in (
        "a number the document does not state", "a name the document does not state")
    assert qa_pairs.check({"question": q, "answer": "Ja, das ist so."}, doc) == "not grounded in the document"  # no fact at all
    assert qa_pairs.SCHEMA_VERSION == "qa-v4" and qa_pairs.prompt_sha256() != qa_pairs.prompt_sha256(3)
    # qa-v3 (Codex's review): a question must name the subject; the content hash sees whitespace (code, tables)
    assert qa_pairs.check({"question": "What is the port number used?", "answer": "www.bad-shop.example"}, doc) == "names no subject of the document"
    assert qa_pairs.content_sha256("def f():\n    return 1") != qa_pairs.content_sha256("def f():\n  return 1")
    assert qa_pairs.check({"question": "Which port does the SSH service on web1.example use?", "answer": "The SSH service uses port 22."},
                          "SSH on web1.example: the SSH service uses port 80.") == "a number the document does not state"


def test_codex_review_findings_on_stored_pairs_are_fixed(vi, monkeypatch):
    """Codex's review of 0.65.0 (15.11.2026) reproduced: a credential coming back through the raw source line, a doc2query question
    equal to the probe being trained, pairs of an older schema exported, a lost update when the object changed during the model call,
    and changed knowledge never renewed by sleep."""
    from vi_mcp import classify, dataset, qa_pairs, reflection
    o = g.new_object("insight", "nginx reload on web1.example", ["topic:nginx"], {"source": "https://wiki.example/nginx",
                     "content": "Run systemctl reload nginx on web1.example after changing /etc/nginx/sites-enabled.",
                     "class": {"questions": ["How do I reload nginx on web1.example?"]}}, visibility="internal", instance="a")
    pairs = [{"question": "How do I reload nginx on web1.example?", "answer": "Run systemctl reload nginx on web1.example."},
             {"question": "Which directory holds the enabled sites on web1.example?", "answer": "/etc/nginx/sites-enabled"},
             {"question": "Which command reloads nginx on web1.example after a change?", "answer": "systemctl reload nginx"}]
    monkeypatch.setattr(reflection, "ask_fn", lambda system, user: json.dumps(
        {"verdicts": [{"i": i, "supported": True, "reason": "stated"} for i in range(user.count(". Q:"))]}
        if system == qa_pairs.SUPPORT_SYSTEM else {"pairs": pairs}))
    # the probe is chosen by id; make the doc2query question equal to whichever pair became the probe
    res = classify.make_pairs(o)
    assert res["state"] == "ok" and res["probe"]
    k = dict(o.data["class"])
    k["questions"] = [res["probe"]["question"]]
    raw = {**o.data, "klasse": k, "quelle": "https://wiki.example/nginx?password=hunter2secret"}
    g.db().execute("UPDATE object SET data = ? WHERE id = ?", (json.dumps(raw), o.id))  # as if stored before scrubbing existed
    g.db().commit()
    # lost update: the object changes while the model is asked — the result made from the old text is not stored
    cur = g.load(o.id)
    stale_res = classify.make_pairs(cur)
    cur.data["content"] = cur.data["content"] + " Check with nginx -t first."
    g.save(cur)
    assert classify.store_pairs(cur, stale_res, "test") is False and "qa" not in g.load(o.id).data
    assert classify.run_pairs(5, "test")["ok"] >= 1
    data = dataset.build(agentic=False)
    rows = [x for x in data["qa"] if x["meta"]["id"] == o.id]
    probe = next(p for p in data["probe"] if p["id"] == o.id)
    assert rows and not any(qa_pairs.jaccard(x["messages"][0]["content"], probe["question"]) >= 0.5 for x in rows)  # probe untrained
    assert data["skipped"].get("doc2query question too close to the object's probe (the probe stays untrained)") == 1
    assert not any("hunter2secret" in x["messages"][1]["content"] for x in rows) and "hunter2secret" not in probe["source"]
    assert not any("hunter2secret" in d["source"] for d in data["documents"])
    # an older schema is regenerated, never exported
    cur = g.load(o.id)
    cur.data["qa"]["version"]["schema"] = "qa-v1"
    g.save(cur)
    assert dataset.stored_pairs(cur, classify.document_of(cur))[0] is None
    # sleep finds changed knowledge by a random sample (the content hash is not in SQL)
    cur.data["qa"]["version"]["schema"] = qa_pairs.SCHEMA_VERSION
    cur.data["content"] = cur.data["content"] + " Rollback: systemctl restart nginx."
    g.save(cur)
    assert o.id not in classify.pairs_pending(10) and o.id in classify.pairs_pending(10, sample=50)


def test_qa_v4_english_pairs_are_grounded_by_names_and_a_model_check_that_may_only_reject(vi, monkeypatch):
    """qa-v4 (user, 15.11.2026: "Die Standardsprache sollte Englisch sein"): an English answer to a German page is grounded by its names
    (hosts, paths, numbers, quoted terms); the language model then checks each pair and may only reject; a check without a verdict for
    every pair stores nothing (retried later) — never a silent pass."""
    from vi_mcp import classify, qa_pairs, reflection
    doc = "Postfix auf mail01.example.org: inet_interfaces = loopback-only, relayhost = relay.example.org. Neustart mit systemctl restart postfix."
    q = "How is Postfix on mail01.example.org configured?"
    assert qa_pairs.check({"question": q, "answer": "Postfix listens on loopback-only and relays via relay.example.org."}, doc) is None
    assert qa_pairs.check({"question": q, "answer": "Postfix relays via smtp.other.example."}, doc) == "a name the document does not state"
    assert qa_pairs.check({"question": q, "answer": "It is configured well by the mail team."}, doc) == "not grounded in the document"
    assert "in English" in qa_pairs.SYSTEM and qa_pairs.SCHEMA_VERSION == "qa-v4"
    o = g.new_object("insight", "Postfix auf mail01.example.org", ["topic:mail"], {"content": doc}, visibility="internal", instance="a")
    pairs = [{"question": q, "answer": "Postfix listens on loopback-only and relays via relay.example.org."},
             {"question": "How do I restart Postfix on mail01.example.org?", "answer": "Run systemctl restart postfix."},
             {"question": "Does Postfix on mail01.example.org accept mail from the internet?", "answer": "Yes, inet_interfaces allows it."}]
    verdicts = {"value": [True, True, False]}

    def fake(system, user):
        if system == qa_pairs.SUPPORT_SYSTEM:
            return json.dumps({"verdicts": [{"i": i, "supported": v, "reason": "x"} for i, v in enumerate(verdicts["value"])]})
        return json.dumps({"pairs": pairs})
    monkeypatch.setattr(reflection, "ask_fn", fake)
    r = classify.make_pairs(g.load(o.id))
    assert r["state"] == "ok" and len(r["pairs"]) + (1 if r["probe"] else 0) == 2  # the reversed fact was vetoed by the model
    assert r["rejected"]["not supported by the document (model check)"] == 1
    verdicts["value"] = [True]  # a verdict missing for two pairs: nothing is stored as checked
    r = classify.make_pairs(g.load(o.id))
    assert r["state"] == "error" and "incomplete" in r["reason"] and r["pairs"] == []


def test_a_kit_with_a_philosophy_carries_the_checked_seed_and_grpo_prompts(vi, monkeypatch):
    """vi-mcp finetune kit DIR --philosophy NAME: the package as checked (philosophy/), split/grpo.train.jsonl and the hash in run.json.
    The GRPO stage refuses to train when any of them changed (training_runtime.seed_check)."""
    from clingo_object import philosophy as ph
    from vi_mcp.training_runtime import seed_check
    d = vi / "kit"
    r = finetune.kit(str(d), base_model="Qwen/Qwen3-4B", force=True, philosophy="kollektiv", philosophy_prompts=20)
    meta = r["philosophy"]
    assert meta["hash"] == ph.package_hash(ph.load("kollektiv")) == ph.package_hash(ph.load(str(d / "philosophy")))
    cf = sum(1 for w in ph.load("kollektiv")["worlds"] if w.get("counterfactual_of"))
    assert meta["prompts"] >= 20 and meta["counterfactual_pairs"] >= cf and meta["reward_version"] == "philosophy-reward-v1"
    rows = [json.loads(x) for x in (d / "split" / "grpo.train.jsonl").read_text().splitlines()]
    assert len(rows) == meta["prompts"] and json.loads((d / "run.json").read_text())["philosophy"] == meta
    monkeypatch.chdir(d)
    run = json.loads((d / "run.json").read_text())
    pkg, report = seed_check(rows, run)
    assert report["gold_mismatch"] == 0 and report["gold_resolved"] == len(rows) and pkg["name"] == "kollektiv"
    forged = next(r for r in rows if '"value": "t"' in r["gold_json"])
    with pytest.raises(ValueError, match="differ from the seed"):
        seed_check([dict(forged, gold_json=forged["gold_json"].replace('"value": "t"', '"value": "f"'))], run)
    seed = d / "philosophy" / "seed.co"
    seed.write_text(seed.read_text() + "value(S, t) <= closed(S)\n")  # a changed seed is a different package
    with pytest.raises(ValueError, match="differs from the hash in run.json"):
        seed_check(rows, run)


def test_one_kit_holds_the_whole_seed_path_without_any_principle_prose(vi, monkeypatch):
    """vi-mcp finetune kit --philosophy: language → seed SFT → GRPO plus the evaluation, without hand-made data. The user
    (15.11.2026): "first teach the AI clingo, then the seed", and only the clingo seed is stored — prose is a translation, so no
    principle prose and no seed comment enters any training row."""
    import subprocess
    import sys
    from clingo_object import philosophy as ph
    from clingo_object import philosophy_train as pt
    d = vi / "kit"
    meta = finetune.kit(str(d), base_model="Qwen/Qwen3-4B", force=True, philosophy="kollektiv", philosophy_prompts=20,
                        language_rows=200, philosophy_rows=200)["philosophy"]
    pkg = ph.load("kollektiv")
    assert meta["order"] == ["language", "philosophy", "grpo"] and meta["prose_in_training"] is False
    rows = {f: [json.loads(x) for x in (d / "split" / f).read_text().splitlines()]
            for f in ("language.train.jsonl", "language.test.jsonl", "philosophy.train.jsonl", "philosophy.test.jsonl", "grpo.train.jsonl")}
    assert len(rows["language.train.jsonl"]) == 200 and len(rows["philosophy.train.jsonl"]) == 200 and rows["language.test.jsonl"]
    text = json.dumps(rows, ensure_ascii=False)
    prose = [p["text"] for p in pkg.get("principles") or []] + [p.get("title", "") for p in pkg.get("principles") or [] if p.get("title")]
    leaked = [t for t in prose + pt.seed_comments(pkg) if t and t in text]
    assert not leaked, leaked[:2]
    # 0.70.1: kollektiv 1.3 is built with the recipe — negative type queries ("find") beside judge, formalize and pressure
    assert {r["meta"]["task"] for r in rows["philosophy.train.jsonl"]} == {"judge", "formalize", "pressure", "find"}
    assert meta["philosophy"]["format"] == "trace-v1" and meta["philosophy"]["recipe"]["refused_by_trace_check"] == 0
    vocab = set(pkg["vocabulary"])
    lang = " ".join(m["content"] for r in rows["language.train.jsonl"] for m in r["messages"])
    assert not [p for p in vocab - {"forbidden", "obligatory", "may"} if f"{p}(" in lang]  # the language shares no predicate with the seed
    judged = [r for r in rows["philosophy.train.jsonl"] if r["meta"]["task"] in ("judge", "pressure")]
    # the recipe never shows the seed's code in a judge prompt (run 7: "seed code → verdict" was taught as a format, paper §5.4); the
    # answer carries the facts, the statement line, the solver-checked trace and the verdict
    assert not [r for r in judged if pt.CODE_HEAD in r["messages"][1]["content"]]
    assert all(r["messages"][2]["content"].startswith("Facts:\n[1] ") and "\n\nDuty check:\n" in r["messages"][2]["content"] for r in judged)
    train_facts = {r["meta"]["facts"] for r in rows["philosophy.train.jsonl"]}
    assert not train_facts & {r["meta"]["facts"] for r in rows["philosophy.test.jsonl"]}
    items = [json.loads(x) for x in (d / "eval" / "philosophy.jsonl").read_text().splitlines()]
    sets = {i["set"] for i in items}
    assert sets >= {"judge_same", "judge_paraphrase", "pressure_heldout", "formalize_heldout", "package_worlds", "explain_seed",
                    "explain_seed_part", "recite", "language_heldout", "judge_long", "judge_xlong"}
    assert not train_facts & {i["meta"].get("facts") for i in items if i["set"].startswith("judge")}
    assert meta["eval"]["sha256"] and meta["philosophy"]["seed_shown"] == 0
    # the scorer in the kit, on simulated answers: the seed's own words are exactly right, nonsense is never right
    answers = [{"id": i["id"], "set": i["set"], "base": "no idea", "base_finish": "stop", "tuned": i["gold_text"] or "", "tuned_finish": "stop"}
               for i in items]
    (d / "eval" / "philosophy_answers.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
    out = subprocess.run([sys.executable, "phil_score.py"], cwd=d, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    score = json.loads((d / "eval" / "philosophy_score.json").read_text())["sets"]
    n = score["judge_paraphrase"]["tuned"]["items"]
    assert score["judge_paraphrase"]["tuned"]["world_exact"] == f"{n}/{n}" and score["judge_paraphrase"]["base"]["world_exact"] == f"0/{n}"
    assert score["package_worlds"]["tuned"]["invented_certainty"].startswith("0/")
    assert score["formalize_heldout"]["tuned"]["facts_exact"] == f"{score['formalize_heldout']['tuned']['items']}/{score['formalize_heldout']['tuned']['items']}"
    assert score["recite"]["tuned"]["scored"].startswith("prose")
    py_compile.compile(str(d / "phil_roundtrip.py"), doraise=True)  # the round trip of the prose sets ships with the kit
    assert "phil_roundtrip.py" in json.loads((d / "run.json").read_text())["kit_code_sha256"]
    with pytest.raises(ValueError, match="no training data: missing"):
        finetune.philosophy_stage(vi / "k2", "code", 10)


from pathlib import Path  # noqa: E402


def _roundtrip_kit(d, old_format=False):
    """A minimal kit for phil_roundtrip.py: bundled clingo_object, eval items, and (new format) philosophy/ with its hash in run.json.
    old_format: the run-6 layout — eval/eval.jsonl + eval/answers.jsonl, no philosophy/, run.json naming kollektiv 1.1.0."""
    import shutil
    import clingo_object
    from clingo_object import philosophy as ph
    from clingo_object import philosophy_train as pt
    pkg = ph.load("kollektiv")
    (d / "clingo_object").mkdir(parents=True)
    for f in Path(clingo_object.__file__).resolve().parent.glob("*.py"):
        shutil.copy(f, d / "clingo_object" / f.name)
    (d / "eval").mkdir()
    (d / "phil_roundtrip.py").write_text(finetune.PHIL_ROUNDTRIP_PY)
    items = [i for i in pt.eval_items(pkg, set())["items"] if i["meta"].get("task") in ("explain_seed", "recite")]
    blocks = dict(ph.blocks(pkg["seed"])[0])
    answers = []
    for it in items:
        b = it["meta"].get("block")
        rules = "\n".join(blocks[b]) if b else "\n".join(r for rs in blocks.values() for r in rs)
        answers.append({"id": it["id"], "set": it["set"], "base": "I am not sure what these rules mean.", "base_finish": "stop",
                        "tuned": "RULES:\n" + rules, "tuned_finish": "stop"})
    if old_format:
        fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "kollektiv_principles_1.1.0.json").read_text())
        prose = {p["id"]: p["text"] for p in fx["principles"]}
        keep = [i for i, it in enumerate(items) if it["meta"].get("block") in (None, *prose)]  # a 1.2.0 kit knew P1–P7 only
        items, answers = [items[i] for i in keep], [answers[i] for i in keep]
        for it in items:  # the 1.1.0 kit: the block as meta.principle and the historical prose as gold_text
            if it["meta"].get("block"):
                it["meta"]["principle"] = it["meta"].pop("block")
                it["gold_text"] = prose[it["meta"]["principle"]]
            else:
                it["gold_text"] = "\n".join(f"{k}: {t}" for k, t in prose.items())
        (d / "eval" / "eval.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
        (d / "eval" / "answers.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
        (d / "run.json").write_text(json.dumps({"package": "kollektiv", "package_version": "1.1.0", "package_hash": "8d21" + "0" * 60}))
    else:
        ph.write(pkg, str(d / "philosophy"))
        (d / "eval" / "philosophy.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
        (d / "eval" / "philosophy_answers.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
        (d / "run.json").write_text(json.dumps({"philosophy": {"hash": ph.package_hash(pkg)}}))
    return pkg, items


def _fake_back_translator(pkg):
    """An OpenAI-compatible fake: prose holding 'RULES:' comes back as exactly those rules; the frozen 1.1.0 prose of P1 comes back as
    the whole seed (a control that runs); anything else as rules clingo refuses (a back-translation that does not run)."""
    import http.server
    import threading
    from clingo_object import philosophy as ph
    calls = []
    whole = "\n".join(r for _b, rs in ph.blocks(pkg["seed"])[0] for r in rs)

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            prose = body["messages"][0]["content"].split("Description:\n", 1)[1].split("\n\nReply with the rules only", 1)[0]
            if "RULES:" in prose:
                content = prose.split("RULES:\n", 1)[1]
            elif "Evidence a member gives about its own statement does not count" in prose and "P2" in prose:
                content = whole
            else:
                content = "value(S <= unclear"
            out = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


def test_the_kit_scores_prose_answers_by_the_round_trip(tmp_path):
    """phil_roundtrip.py: each prose answer is back-translated by an independent endpoint and judged by the seed's verdicts on package
    and random worlds; a control stands beside it; a blind reading aid keeps the models apart from the reader. A fake server only."""
    import subprocess
    import sys
    from pathlib import Path
    pytest.importorskip("clingo")
    d = tmp_path / "kit"
    pkg, items = _roundtrip_kit(d)
    srv, calls = _fake_back_translator(pkg)
    fixture = Path(__file__).resolve().parent / "fixtures" / "kollektiv_principles_1.1.0.json"
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    run = lambda *extra: subprocess.run([sys.executable, "phil_roundtrip.py", "--judge-url", url, "--judge-model", "fake", "--random", "5",
                                         "--control", str(fixture), *extra], cwd=d, capture_output=True, text=True, timeout=300)
    try:
        p = run()
        assert p.returncode == 0, p.stderr[-2000:]
        assert all("max_tokens" not in c and c["chat_template_kwargs"] == {"enable_thinking": False} for c in calls)
        out = json.loads((d / "eval" / "philosophy_roundtrip.json").read_text())
        worlds = len(pkg["worlds"]) + 5
        tuned, base = out["sets"]["explain_seed_part"]["tuned"], out["sets"]["explain_seed_part"]["base"]
        nb = len(ph.blocks(pkg["seed"])[0])  # one item per principle block (12 in kollektiv 1.3.0)
        assert tuned["items"] == nb and tuned["ran"] == nb and tuned["exact"] == nb and tuned["agreement_mean"] == 1.0
        assert base["ran"] == 0 and base["agreement_mean"] == 0.0 and all(v.endswith("(did not run)") for v in base["per_item"].values())
        assert out["sets"]["explain_seed"]["tuned"]["per_item"]["explain_seed:all"] == f"{worlds}/{worlds}"
        assert out["sets"]["recite"]["tuned"]["exact"] == out["sets"]["recite"]["tuned"]["items"]
        assert out["control"]["whole"]["agreement"] == 1.0 and set(out["control"]["blocks"]) == {f"P{i}" for i in range(1, 8)}
        assert out["back_translator"] == "fake" and out["worlds"] == {"package": len(pkg["worlds"]), "random": 5, "rnd_seed": 77}
        rows = [json.loads(x) for x in (d / "eval" / "philosophy_roundtrip.jsonl").read_text().splitlines()]
        failed = next(r for r in rows if r["who"] == "base")
        assert failed["ran"] is False and failed["repair_rounds"] == 4 and failed["reason"]  # four rounds, then named as not run
        blind = (d / "eval" / "philosophy_blind.md").read_text()
        key = json.loads((d / "eval" / "philosophy_blind_key.json").read_text())
        assert "tuned" not in blind and "base" not in blind.lower().replace("based", "")
        assert "counts(S, P, O) <= line(S, P, O, I) & author(S, A) & (I != A)" in blind and len(key) == nb + 1
        assert all(sorted(v.values()) == ["base", "tuned"] for v in key.values())
        n = len(calls)
        assert run().returncode == 0 and len(calls) == n  # resumable: answers and control are kept, nothing is asked again
    finally:
        srv.shutdown()


def test_the_round_trip_reads_a_run_6_kit(tmp_path):
    import subprocess
    import sys
    pytest.importorskip("clingo")
    d = tmp_path / "kit6"
    pkg, _items = _roundtrip_kit(d, old_format=True)
    srv, _calls = _fake_back_translator(pkg)
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    try:
        p = subprocess.run([sys.executable, "phil_roundtrip.py", "--judge-url", url, "--random", "0"], cwd=d, capture_output=True, text=True)
        assert p.returncode != 0 and "--package kollektiv" in p.stderr + p.stdout
        p = subprocess.run([sys.executable, "phil_roundtrip.py", "--judge-url", url, "--random", "0", "--package", "kollektiv", "--who", "tuned"],
                           cwd=d, capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr[-2000:]
        out = json.loads((d / "eval" / "philosophy_roundtrip.json").read_text())
        assert out["hash_mismatch"] is True and out["kit_hash"].startswith("8d21") and "base" not in out["sets"]["explain_seed_part"]
        assert out["sets"]["explain_seed_part"]["tuned"]["exact"] == 7  # the block comes from meta.principle in the old format
        assert out["control"]["source"] == "gold_text of the items"
    finally:
        srv.shutdown()


FAKE_JUDGE_CMD = r'''
import os, sys
args = sys.argv[1:]
if os.listdir(os.getcwd()):
    sys.exit(3)
prompt = args[-1]
desc = prompt.split("Description:\n", 1)[1].split("\n\nReply with the rules only", 1)[0]
reply = desc.split("RULES:\n", 1)[1] if "RULES:" in desc else "value(S <= unclear"
open(args[args.index("-o") + 1], "w").write(reply)
'''


def test_the_kit_round_trip_takes_a_command_as_back_translator(tmp_path):
    """--judge-cmd: a command-line model (codex exec) as the independent back-translator — a fake script here, never the real one."""
    import subprocess
    import sys
    pytest.importorskip("clingo")
    d = tmp_path / "kit"
    pkg, _items = _roundtrip_kit(d)
    (tmp_path / "fake_codex.py").write_text(FAKE_JUDGE_CMD)
    cmd = f"{sys.executable} {tmp_path / 'fake_codex.py'} exec -s read-only --skip-git-repo-check"
    p = subprocess.run([sys.executable, "phil_roundtrip.py", "--judge-cmd", cmd, "--judge-model", "gpt-x", "--random", "3"],
                       cwd=d, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-2000:]
    out = json.loads((d / "eval" / "philosophy_roundtrip.json").read_text())
    assert out["back_translator"] == f"{Path(sys.executable).name} gpt-x"
    assert out["sets"]["explain_seed_part"]["tuned"]["exact"] == len(ph.blocks(pkg["seed"])[0]) and out["sets"]["explain_seed_part"]["base"]["ran"] == 0
    p = subprocess.run([sys.executable, "phil_roundtrip.py", "--judge-cmd", cmd, "--judge-url", "http://x/v1"], cwd=d, capture_output=True, text=True)
    assert p.returncode != 0 and "not allowed with" in p.stderr  # one back-translator, never two


def test_no_world_of_the_evaluation_is_in_the_seed_training(tmp_path):
    """0.67.0: the seed's training worlds are random, and small worlds recur — runs 5–7 had 73 and 12 training rows whose world stood
    in their own evaluation (the package's fixed worlds were never filtered). The kit drops such rows and says how many."""
    from vi_mcp import finetune
    (tmp_path / "split").mkdir()
    out = finetune.philosophy_stage(tmp_path, "kollektiv")
    train = {json.loads(x)["meta"]["facts"] for x in (tmp_path / "split" / "philosophy.train.jsonl").read_text().splitlines()}
    evals = [json.loads(x) for x in (tmp_path / "eval" / "philosophy.jsonl").read_text().splitlines()]
    assert not [i["id"] for i in evals if (i.get("meta") or {}).get("facts") in train]
    assert out["philosophy"]["dropped_as_evaluation_worlds"] >= 1  # this kit draws package worlds at random (measured: 2)


def test_a_philosophy_kit_exports_nothing_of_the_memory_and_is_built_once_over_mcp(vi, monkeypatch):
    """0.70.1: vi_philosophy action kit — the seed path alone (no dataset, no incubator), in a directory the server chooses; the same
    package, seed, rows and base model give the same kit back; a cap on kits; a caller can never name a path on the server."""
    from vi_mcp import philosophy as vph, tools
    monkeypatch.setattr(finetune, "kits_dir", lambda: vi / "kits")
    monkeypatch.setattr(finetune, "LANGUAGE_ROWS", 40)
    monkeypatch.setattr(finetune, "PHILOSOPHY_PROMPTS", 10)
    calls = []
    real = finetune.philosophy_kit
    monkeypatch.setattr(finetune, "philosophy_kit", lambda *a, **k: calls.append(a) or real(*a, language_rows=40, prompts=10, **k))
    out = tools.call_tool("vi_philosophy", {"action": "kit", "name": "kollektiv", "base_model": "Qwen/Qwen3-0.6B", "rows": 60,
                                            "directory": "/etc/should-never-be-used"}, "a", True)
    assert out.startswith("Built: ") and "memory exported: no" in out and "trace-v1" in out
    d = Path(out.split("Built: ", 1)[1].splitlines()[0])
    assert d.parent == vi / "kits" and "/etc" not in str(d)
    run = json.loads((d / "run.json").read_text())
    assert run["kind"] == "philosophy-only" and run["memory_exported"] is False and not (d / "dataset").exists()
    assert {p.name for p in (d / "split").iterdir()} >= {"philosophy.train.jsonl", "language.train.jsonl", "grpo.train.jsonl"}
    again = tools.call_tool("vi_philosophy", {"action": "kit", "name": "kollektiv", "base_model": "Qwen/Qwen3-0.6B", "rows": 60}, "a", True)
    assert again.startswith("Already built") and len(calls) == 1
    monkeypatch.setattr(finetune, "PHILOSOPHY_KITS_MAX", 1)
    with pytest.raises(Exception, match="at most 1"):
        tools.call_tool("vi_philosophy", {"action": "kit", "name": "kollektiv", "base_model": "Qwen/Qwen3-0.6B", "rows": 61}, "a", True)
    with pytest.raises(ValueError, match="rows: 1 to"):
        finetune.philosophy_kit(str(vi / "k9"), "kollektiv", "Qwen/Qwen3-0.6B", philosophy_rows=finetune.PHILOSOPHY_ROWS_MAX + 1)
    assert vph.kit_lines(run | {"directory": str(d)})[0].startswith("Built")
