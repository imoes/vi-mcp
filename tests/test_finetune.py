"""0.62.0: fine-tuning an AI with what a VI learned — the VI knows how; vi-mcp writes the kit and records the run, it trains nothing."""
import json
import py_compile

import pytest

from vi_mcp import evaluation, finetune, tools
from vi_mcp import memory as g


@pytest.fixture()
def vi(gd, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVAL_DIR", tmp_path / "eval")
    for i in range(12):
        g.new_object("erkenntnis", f"knowledge {i}: how to deploy service {i}", ["thema:deploy"],
                     {"quelle": "t", "inhalt": f"step one, step two for {i}", "klasse": {"fragen": [f"how to deploy {i}?", f"deploy {i} steps?"]}},
                     visibility="intern", instance="a")
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
              "README-FINETUNE.md", "run.json", "eval_questions.json"):
        assert (d / f).exists(), f
    train = {json.loads(x)["meta"]["id"] for x in (d / "split/train.jsonl").read_text().splitlines()}
    test = {json.loads(x)["meta"]["id"] for x in (d / "split/test.jsonl").read_text().splitlines()}
    assert train and test and not (train & test)  # split by object: no object on both sides
    assert r["split"]["train"] + r["split"]["test"] == 24 and r["eval_fragen"] == 1
    for f in ("train.py", "evaluate.py"):
        py_compile.compile(str(d / f), doraise=True)
        assert '"max_tokens"' not in (d / f).read_text() and "max_new_tokens" not in (d / f).read_text() and (d / f).stat().st_mode & 0o777 == 0o700
    assert (d / "run.json").stat().st_mode & 0o077 == 0 and json.loads((d / "run.json").read_text())["base_model"] == "Qwen/Qwen3-4B"


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
    assert o.mode == "aktiv" and "fine-tuned 0.52 vs base 0.31 on 25 held-out questions" in o.text
    assert o.data["dataset_manifest_sha256"] and o.data["incubator"]["zustand"] == "im_inkubator"
