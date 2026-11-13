"""Fine-tuning an AI with what a VI learned (0.62.0) — the VI knows how, and an AI on vi-mcp is told "I want to fine-tune".

The user (13.11.2026): "Die VI ist noch nicht fertig gebrütet, aber die VI muss wissen, wie man fine-tuned, und wenn man den
vi-mcp-Server benutzt, soll man dem LLM einfach sagen, dass man fine-tunen will." and "Es soll eine direkte Schnittstelle für das
Fine-Tuning geben."

vi-mcp trains no model by itself. This module is the interface a person uses through their AI (tool `vi_finetune`) or the command line:
  guide    the handbook below — what fine-tuning is, which program, which hardware, how back into llama.cpp, how to measure
  plan     this VI's readiness (incubator) and the concrete steps for this server
  kit      a ready directory: the training data (incubator hatch), a test split, train.py (TRL + LoRA), convert.sh (GGUF adapter),
           evaluate.py (base against fine-tuned on held-out questions), README — written, never run by vi-mcp
  record   after a run: a model object with its lineage — dataset manifest, base model, adapter hash, evaluation, incubator state
Research behind the handbook (13.11.2026, primary sources named in it).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

from . import __version__
from . import memory as g

GUIDE_VERSION = "2026-11-13"
TEST_SHARE = 0.15

GUIDE = """# Fine-tuning an AI with the knowledge of a VI

## What it is
An existing open model (e.g. Qwen, Llama) stays frozen; only a small add-on is trained — a **LoRA adapter** (a few percent of the
model's size). **QLoRA** loads the frozen model in 4 bit so it fits into little GPU memory (Dettmers et al., arXiv 2305.14314). The data
stays in the house; only the base model is downloaded once.

## Three ways to learn, three files of `vi-mcp dataset export`
- **SFT** — `qa.jsonl`: question → right answer with source. The model learns the knowledge.
- **KTO** — `kto.jsonl`: an answer was good or not (binary). Exactly the VI's helped/not-helped signal (Ethayarajh et al., arXiv 2402.01306).
- **DPO** — `dpo.jsonl`: in the same situation this answer was better than that one (Rafailov et al., arXiv 2305.18290).
- **agentic** — `agentic.jsonl`: the model asks the VI with `vi_recall` in VIL and answers from what it found (tool-use SFT).
- **logic** — `logic.jsonl`: the model writes clingo-object programs for the tasks of saved rule sets and answers from the solver
  (tool-use SFT with `vi_logic`, 0.63.0 — "clingo ist die Sprache für LLMs"); wrongly rated conclusions are KTO negatives.

## The program
- **TRL** (Hugging Face) reads all formats unchanged: SFT `messages`, KTO `prompt/completion/label`, DPO `prompt/chosen/rejected`
  (https://huggingface.co/docs/trl/main/en/dataset_formats). KTO: learning rate 5e-7 … 5e-6, desirable:undesirable between 1:1 and 4:3
  (https://huggingface.co/docs/trl/main/en/kto_trainer).
- **Unsloth** builds on TRL: "2× faster with 70% less VRAM", supports AMD/ROCm incl. gfx1151 (https://github.com/unslothai/unsloth,
  https://unsloth.ai/docs/basics/amd). **LLaMA-Factory** has a web UI (KTO needs the column `label` mapped to `kto_tag`).
  **torchtune** is no longer maintained.

## Hardware (minimum per Unsloth, https://unsloth.ai/docs/get-started/beginner-start-here/unsloth-requirements)
| model | QLoRA 4 bit | LoRA 16 bit |
|---|---|---|
| 3B | 3.5 GB | 8 GB |
| 7–8B | 5–6 GB | 19–22 GB |
| 14B | 8.5 GB | 33 GB |
An 8 GB card: QLoRA up to ~8B with short sequences. A 96 GB unified-memory APU: LoRA in 16 bit up to 14B — test first whether PyTorch
sees the GPU (`torch.cuda.is_available()` on ROCm).

## Back into llama.cpp
Keep the adapter separate: `python convert_lora_to_gguf.py ADAPTER_DIR --base HF_BASE_DIR --outtype f16`, then
`llama-server -m base.gguf --lora adapter.gguf` (switchable at runtime with `--lora-init-without-apply` and `POST /lora-adapters`)
(https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Or merge in 16 bit, `convert_hf_to_gguf.py`, `llama-quantize`.

## The steps
1. The VI is mature enough: `vi-mcp incubator status` (a run before is a trial).
2. `vi-mcp finetune kit DIR` — data, test split, scripts.
3. Train SFT (`train.py --stage sft`), then on top of it `--stage agentic` (searching the VI with vi_recall in VIL), `--stage logic`
   (writing clingo-object programs), and
   optionally KTO or DPO (`--stage kto|dpo`).
4. `convert.sh` → GGUF adapter; start llama-server with base and adapter.
5. `evaluate.py` — base and fine-tuned get the same held-out questions; adopt only what is measurably better.
6. `vi-mcp finetune record DIR` — the run becomes a model object with its lineage in the VI.

## Rules
- Never set a token cap (max_tokens) in evaluation; if answers run long, switch thinking off (`enable_thinking: false`).
- The evaluation questions are held out of the training data (the export guarantees it) — never train on them.
- Internal data: the files carry company knowledge unanonymised.
"""


def _cfg() -> dict:
    from . import config
    try:
        return config.read_raw(config.fpath()).get("finetune") or {}
    except Exception:  # noqa: BLE001
        return {}


def plan(index: str | None = None, base_model: str | None = None) -> dict:
    """Readiness and the concrete steps for this server."""
    from . import incubator
    st = incubator.status(index)
    base = base_model or _cfg().get("base_model")
    steps = [
        ("readiness", "vi-mcp incubator status" + (f" --index {index}" if index else ""),
         "mature" if st["zustand"] == "reif" else f"not mature — a run now is a trial; open: {', '.join(st['offen'])}"),
        ("kit", f"vi-mcp finetune kit /srv/vi-finetune{(' --index ' + index) if index else ''}{(' --base ' + base) if base else ''}"
                + ("" if st["zustand"] == "reif" else " --force"), "training data, test split and scripts, nothing is run"),
        ("train", "python train.py --stage sft   (then optionally --stage kto or --stage dpo)", "on the GPU host, in a venv with torch, trl, peft"),
        ("convert", "./convert.sh", "the adapter as GGUF for llama.cpp, and the llama-server line"),
        ("evaluate", "python evaluate.py --base URL --tuned URL", "same held-out questions to both; adopt only if better"),
        ("record", "vi-mcp finetune record /srv/vi-finetune", "the run as a model object with its lineage"),
    ]
    missing = [] if base else ["base_model (config finetune.base_model or --base, e.g. a Hugging Face id of the model already served)"]
    return {"zustand": st["zustand"], "offen": st["offen"], "grundmodell": base, "fehlt": missing, "schritte": steps, "handbuch": GUIDE_VERSION}


def plan_lines(p: dict) -> list[str]:
    head = ("This VI is mature: its training data can fine-tune an AI." if p["zustand"] == "reif"
            else f"This VI is still in the incubator (open: {', '.join(p['offen'])}) — a fine-tuning now is a trial run.")
    out = [head, f"Base model: {p['grundmodell'] or '— not set'}" + (f" · needed: {'; '.join(p['fehlt'])}" if p["fehlt"] else ""), "Steps:"]
    out += [f"  {i}. {name}: {cmd}  — {why}" for i, (name, cmd, why) in enumerate(p["schritte"], 1)]
    out.append("vi_finetune(action='guide') explains fine-tuning; the kit is written on the server by a person (vi-mcp finetune kit).")
    return out


TRAIN_PY = r'''"""Fine-tune with TRL + LoRA — written by vi-mcp finetune kit; run it on the GPU host. Stages: sft (qa.jsonl), then on top of it
agentic (agentic.jsonl: searching the VI with vi_recall), logic (logic.jsonl: clingo-object programs), kto or dpo."""
import argparse, json, pathlib

a = argparse.ArgumentParser()
a.add_argument("--stage", choices=["sft", "agentic", "logic", "kto", "dpo"], default="sft")
a.add_argument("--base", default=json.load(open("run.json"))["base_model"])
a.add_argument("--qlora", action="store_true", help="load the base in 4 bit (small GPUs)")
a.add_argument("--epochs", type=float, default=2)
a.add_argument("--lr", type=float, default=None)
o = a.parse_args()

from datasets import load_dataset
from peft import LoraConfig, AutoPeftModelForCausalLM
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

tok = AutoTokenizer.from_pretrained(o.base)
quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4") if o.qlora else None
lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
out = pathlib.Path("out") / o.stage
if o.stage == "sft":
    from trl import SFTConfig, SFTTrainer
    model = AutoModelForCausalLM.from_pretrained(o.base, quantization_config=quant, torch_dtype="auto")
    ds = load_dataset("json", data_files="split/train.jsonl")["train"].remove_columns(["meta"])
    t = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, peft_config=lora,
                   args=SFTConfig(output_dir=str(out), num_train_epochs=o.epochs, learning_rate=o.lr or 2e-4, logging_steps=10))
else:
    model = AutoPeftModelForCausalLM.from_pretrained("out/sft", is_trainable=True, quantization_config=quant, torch_dtype="auto")
    if o.stage in ("agentic", "logic"):  # tool use: vi_recall in VIL, or vi_logic with clingo-object (rendered by the chat template)
        from trl import SFTConfig, SFTTrainer
        ds = load_dataset("json", data_files=f"dataset/{o.stage}.jsonl")["train"].remove_columns(["meta"])
        t = SFTTrainer(model=model, processing_class=tok, train_dataset=ds,
                       args=SFTConfig(output_dir=str(out), num_train_epochs=o.epochs, learning_rate=o.lr or 1e-4, logging_steps=10))
    elif o.stage == "kto":
        from trl import KTOConfig, KTOTrainer
        ds = load_dataset("json", data_files="dataset/kto.jsonl")["train"].remove_columns(["meta"])
        t = KTOTrainer(model=model, processing_class=tok, train_dataset=ds,
                       args=KTOConfig(output_dir=str(out), num_train_epochs=o.epochs, learning_rate=o.lr or 5e-6, per_device_train_batch_size=4))
    else:
        from trl import DPOConfig, DPOTrainer
        ds = load_dataset("json", data_files="dataset/dpo.jsonl")["train"].remove_columns(["meta"])
        t = DPOTrainer(model=model, processing_class=tok, train_dataset=ds,
                       args=DPOConfig(output_dir=str(out), num_train_epochs=o.epochs, learning_rate=o.lr or 5e-6))
t.train()
t.save_model(str(out))
json.dump({**json.load(open("run.json")), f"trained_{o.stage}": str(out)}, open("run.json", "w"), indent=2)
print("adapter written to", out)
'''

EVALUATE_PY = r'''"""Base against fine-tuned on held-out questions — written by vi-mcp finetune kit. Both are OpenAI-compatible endpoints (llama-server).
Score per question: share of the expected keywords in the answer. No max_tokens (project rule); thinking off."""
import argparse, json, re, urllib.request

a = argparse.ArgumentParser()
a.add_argument("--base", required=True, help="chat completions URL of the base model")
a.add_argument("--tuned", required=True, help="chat completions URL of base + adapter")
o = a.parse_args()


def ask(url, q):
    body = {"messages": [{"role": "user", "content": q}], "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def words(t):
    return {w for w in re.findall(r"\w{4,}", (t or "").lower())}


rows = [json.loads(l) for l in open("split/test.jsonl")]
qs = [(r["messages"][0]["content"], words(r["messages"][1]["content"])) for r in rows]
qs += [(q["frage"], words(q["stichworte"])) for q in json.load(open("eval_questions.json"))]
res = {"base": [], "tuned": []}
for q, expect in qs:
    for name, url in (("base", o.base), ("tuned", o.tuned)):
        got = words(ask(url, q))
        res[name].append(len(got & expect) / len(expect) if expect else 0.0)
summary = {k: round(sum(v) / len(v), 4) if v else None for k, v in res.items()}
summary["n"] = len(qs)
summary["better"] = sum(1 for b, t in zip(res["base"], res["tuned"]) if t > b)
summary["worse"] = sum(1 for b, t in zip(res["base"], res["tuned"]) if t < b)
json.dump(summary, open("eval.json", "w"), indent=2)
print(json.dumps(summary, indent=2))
'''

CONVERT_SH = """#!/bin/sh
# The adapter as GGUF for llama.cpp — written by vi-mcp finetune kit. LLAMA_CPP = a checkout of llama.cpp, BASE_HF = the base model's
# Hugging Face directory (the same one train.py used).
set -e
: "${LLAMA_CPP:?set LLAMA_CPP to your llama.cpp checkout}"
: "${BASE_HF:?set BASE_HF to the base model directory}"
STAGE="${1:-sft}"
python "$LLAMA_CPP/convert_lora_to_gguf.py" "out/$STAGE" --base "$BASE_HF" --outtype f16 --outfile "adapter-$STAGE.gguf"
echo "serve: llama-server -m BASE.gguf --lora adapter-$STAGE.gguf   (switchable: --lora-init-without-apply, POST /lora-adapters)"
"""


def _split(qa_path: Path, out_dir: Path, share: float = TEST_SHARE, seed: int = 7) -> dict:
    """Test split by object (all questions of one object on the same side), deterministic."""
    rows = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = sorted({r["meta"]["id"] for r in rows})
    rnd = random.Random(seed)
    test_ids = set(rnd.sample(ids, max(1, int(len(ids) * share)))) if len(ids) > 1 else set()
    out_dir.mkdir(exist_ok=True)
    train = [r for r in rows if r["meta"]["id"] not in test_ids]
    test = [r for r in rows if r["meta"]["id"] in test_ids]
    for name, part in (("train", train), ("test", test)):
        _write(out_dir / f"{name}.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part))
    return {"train": len(train), "test": len(test), "objekte_test": len(test_ids)}


def _write(p: Path, text: str, mode: int = 0o600) -> None:
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, mode)


def kit(directory: str, index: str | None = None, base_model: str | None = None, force: bool = False) -> dict:
    """Write the fine-tuning kit. Runs nothing; a person runs the scripts on the GPU host."""
    from . import evaluation, incubator
    base = base_model or _cfg().get("base_model")
    if not base:
        raise ValueError("no base model — give --base (a Hugging Face id or directory of the model to fine-tune) or config finetune.base_model")
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    manifest = incubator.hatch(str(d / "dataset"), index, force)
    split = _split(d / "dataset" / "qa.jsonl", d / "split")
    qp = evaluation.eval_dir() / "recall.json"
    questions = [{"frage": q["frage"], "stichworte": q["stichworte"]} for q in evaluation.load_questions(qp)] if qp.exists() else []
    _write(d / "eval_questions.json", json.dumps(questions, ensure_ascii=False, indent=1))
    _write(d / "train.py", TRAIN_PY, 0o700)
    _write(d / "evaluate.py", EVALUATE_PY, 0o700)
    _write(d / "convert.sh", CONVERT_SH, 0o700)
    _write(d / "README-FINETUNE.md", GUIDE)
    run = {"base_model": base, "kit": g.now(), "vi_mcp": __version__, "handbook": GUIDE_VERSION, "index": index,
           "dataset_manifest_sha256": hashlib.sha256((d / "dataset" / "manifest.json").read_bytes()).hexdigest(), "split": split,
           "incubator": manifest.get("inkubator")}
    _write(d / "run.json", json.dumps(run, indent=2, ensure_ascii=False))
    return {"verzeichnis": str(d), **run, "eval_fragen": len(questions)}


def record(directory: str, who: str = "admin") -> g.MemoryObject:
    """A finished run as a model object with its lineage: dataset manifest, base model, adapter hash, evaluation, incubator state."""
    d = Path(directory)
    if not (d / "run.json").exists():
        raise ValueError(f"{d}: no run.json — not a kit written by vi-mcp finetune kit")
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    adapters = {}
    for stage in ("sft", "agentic", "logic", "kto", "dpo"):
        f = d / "out" / stage / "adapter_model.safetensors"
        if f.exists():
            adapters[stage] = hashlib.sha256(f.read_bytes()).hexdigest()
    ev = json.loads((d / "eval.json").read_text(encoding="utf-8")) if (d / "eval.json").exists() else None
    if not adapters:
        raise ValueError(f"{d}: no trained adapter under out/ — run train.py first")
    better = ev is not None and ev.get("tuned") is not None and ev.get("base") is not None and ev["tuned"] > ev["base"]
    verdict = ("not evaluated — run evaluate.py" if ev is None else
               f"fine-tuned {ev['tuned']} vs base {ev['base']} on {ev['n']} held-out questions ({ev['better']} better, {ev['worse']} worse)")
    oid = f"modell:finetune:{run['kit'][:19].replace(':', '').replace('-', '')}"
    data = {**run, "adapter_sha256": adapters, "bewertung": ev, "urteil": verdict, "erfasst": g.now()}
    text = f"Fine-tuned model on {run['base_model']} ({', '.join(adapters)}): {verdict}"
    o = g.load(oid)
    if o is None:
        return g.new_object("modell", text, ["modell:finetune"], data, importance=2, who=who, oid=oid, mode="aktiv" if better else "test",
                            reason="fine-tuning run recorded", instance=g.SERVER_INSTANCE, index=run.get("index"))
    o.text, o.data, o.mode = text, data, "aktiv" if better else "test"
    o.change(who, "fine-tuning run updated", verdict)
    return g.save(o)


def main(argv: list[str]) -> int:
    """vi-mcp finetune guide | plan [--index X] [--base M] | kit DIR [--index X] [--base M] [--force] | record DIR"""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp finetune", description="fine-tune an AI with what this VI learned (vi-mcp runs no training)")
    u = a.add_subparsers(dest="cmd", required=True)
    u.add_parser("guide", help="the handbook: what fine-tuning is, programs, hardware, llama.cpp, measuring")
    p = u.add_parser("plan", help="readiness and the steps for this server")
    k = u.add_parser("kit", help="write the training data, test split and scripts into a directory")
    r = u.add_parser("record", help="record a finished run as a model object with its lineage")
    for x in (p, k):
        x.add_argument("--index")
        x.add_argument("--base")
    k.add_argument("directory")
    k.add_argument("--force", action="store_true", help="also for a VI still in the incubator (the datasheet names the open criteria)")
    r.add_argument("directory")
    o = a.parse_args(argv)
    if o.cmd == "guide":
        print(GUIDE)
        return 0
    g.open_db(config.load().db)
    try:
        if o.cmd == "plan":
            print("\n".join(plan_lines(plan(o.index, o.base))))
        elif o.cmd == "kit":
            print(json.dumps(kit(o.directory, o.index, o.base, o.force), indent=2, ensure_ascii=False))
        else:
            print(record(o.directory).text)
    except ValueError as e:
        print(f"vi-mcp finetune: {e}")
        return 1
    finally:
        g.close_db()
    return 0
