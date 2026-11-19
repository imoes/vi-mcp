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
import re
from collections import Counter
from pathlib import Path

from . import __version__
from . import memory as g

GUIDE_VERSION = "2026-11-15d"
TEST_SHARE = 0.15
STRATIFY_MIN = 5  # a stage with at least this many groups always gets held-out groups

GUIDE = """# Fine-tuning an AI with the knowledge of a VI

## What it is
An existing open model (e.g. Qwen, Llama) stays frozen; only a small add-on is trained — a **LoRA adapter** (a few percent of the
model's size). **QLoRA** loads the frozen model in 4 bit so it fits into little GPU memory (Dettmers et al., arXiv 2305.14314). The data
stays in the house; only the base model is downloaded once.

## Training formats of `vi-mcp dataset export`
- **SFT** — `qa.jsonl`: a real question (doc2query) → knowledge with source, and the grounded question-answer pairs the server
  stored on each object (0.65.0, `vi-mcp classify --pairs`, sleep step 8i); the manifest reports evidence and question source.
  An object's text is never trained as its own question: the first production run (14.11.2026) did that for 96 % of its rows and
  learned to echo and continue documents (no gain on real questions, loops). Knowledge without stored pairs is in `documents.jsonl`;
  the kit's `synth_qa.py` writes pairs for it (`qa_synth.jsonl`). Diverse QA pairs inject knowledge better than raw text
  (arXiv 2409.07431, 2412.14964).
- **probe** — `probe.jsonl`: one stored pair per object that is never trained; after training it asks whether the model learned
  that object (knowledge probe, `probe.py`).
- **KTO** — `kto.jsonl`: an answer was good or not (binary). Exactly the VI's helped/not-helped signal (Ethayarajh et al., arXiv 2402.01306).
- **DPO** — `dpo.jsonl`: in the same situation this answer was better than that one (Rafailov et al., arXiv 2305.18290).
- **agentic** — `agentic.jsonl`: the model asks the VI with `vi_recall` in VIL and answers from what it found (tool-use SFT).
- **logic** — `logic.jsonl`: the model writes clingo-object programs for the tasks of saved rule sets and answers from the solver
  (tool-use SFT with `vi_logic`, 0.63.0 — "clingo ist die Sprache für LLMs"); wrongly rated conclusions are KTO negatives.

## The program
- **TRL** (Hugging Face) supports SFT `messages`, KTO `prompt/completion/label`, DPO `prompt/chosen/rejected`
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
2. The server stores pairs and probes while it sleeps (config `classify` with url and model); existing knowledge once with
   `vi-mcp classify --pairs --limit 25000 --workers 4` (`--dry-run` counts). Then `vi-mcp finetune kit DIR` — data, split, scripts.
   For knowledge without stored pairs: `python synth_qa.py --url http://HOST/v1 --model NAME [--limit N]` (the same definition of a
   grounded pair, qa_pairs.py; resumable; synth_report.json) and `vi-mcp finetune split DIR`. Check `run.json` → split →
   qa_question_sources and probe.
3. On the training host install its hardware-appropriate PyTorch, then `python -m pip install -r requirements-train.txt`.
   First run `python train.py --stage logic --tokenizer-only --from-base` (no model weights), then
   `python train.py --stage logic --preflight --from-base` (real trainer, one no-grad loss, zero optimizer steps).
   Repeat for the intended stages. `--cpu` is available; the model must fit in memory. `--fp32` keeps float32 on a GPU (no bf16 mixed precision),
   e.g. on AMD gfx1151 where bf16 problems are reported. Reports are `preflight-STAGE.json`.
   These checks do not train, save an adapter, change run.json or certify incubator maturity. A missing parent adapter is named in the report.
4. When explicitly ready, train SFT (`python train.py --stage sft`), then optionally agentic or logic. Later stages read only their shared train split.
   Use `--stage logic --from-adapter out/agentic` to continue the agentic stage, or `--stage dpo --from-adapter out/logic`
   to continue the logic stage; without this flag each later stage starts from out/sft. `--stage logic --from-base` explicitly starts
   program training directly on a fresh adapter without a prior QA stage. Solver-only examples and
   observational hint pairs are withheld from default program/DPO training. Checked machine examples are published explicitly with vi_machine teach.
   A philosophy: `vi-mcp finetune kit DIR --philosophy NAME` also writes the seed path, in the order "first clingo, then the seed":
   `--stage language` (clingo-object both ways, from the base), `--stage philosophy` (the seed's judge, formalize and pressure examples,
   half with the seed's rules shown; no principle prose anywhere), `--stage grpo` (the seed as reward, continues out/philosophy), and
   eval/philosophy.jsonl with `phil_answers.py` and `phil_score.py` (world_exact, values, duties, invented certainty) and
   `phil_roundtrip.py` (the prose answers by round trip: --judge-url/--judge-model, --control FILE). The GRPO stage re-solves every
   gold verdict with the bundled seed and refuses a changed package hash. The reward is +1 for a right value with its reasons and
   −1 for invented certainty; the explicit "I cannot formalize this situation." gives 0; unparseable or cut output gives −1. There is
   no length term. The generation budget is a local resource bound (twice the longest gold verdict), named in the report.
5. `convert.sh` → GGUF adapter; start llama-server with base and adapter.
6. Knowledge probe: `python probe.py answer --adapter out/sft`, `python probe.py judge --url URL --model NAME` (or a person writes
   probe/judgments.jsonl), `python probe.py summarize` → probe/probe_eval.json. Measured 15.11.2026 (Qwen3-0.6B, LoRA rank 64,
   4 epochs, 500 documents × ~5 pairs): 7 correct / 9 partial of 60 probes against the base model's 0 / 5, strict p 0.008.
   `evaluate.py` collects paired predictions on held-out objects (generalisation, which closed-book tuning does not give);
   supply independent --judgments for correctness. For program writing use
   `program_evaluate.py --base URL --tuned URL`: full solver answers on frozen held-out worlds, not word overlap.
   The kit bundles the solver's Python sources, so it works without a VI checkout. Truncated model outputs cannot count as correct.
   `heldout_loss.py --stage sft|agentic|logic` measures the held-out loss on the assistant targets, for base and adapter, with the
   same tokens as training. It shows knowledge absorption, not task success, and it is never the adoption gate.
   Adoption requires an exact one-sided sign-flip test over independent task families (clustered McNemar) at p < 0.05 with a
   positive difference. It assumes independent families and, under the null, base and tuned exchangeable within each family.
   The Hoeffding lower_95 is reported as the worst-case size bound.
7. `vi-mcp finetune record DIR` — the run becomes a model object with its lineage in the VI.

## Rules
- Never set a token cap (max_tokens) in evaluation; if answers run long, switch thinking off (`enable_thinking: false`).
- Evaluation source pages, duplicate contents and questions are excluded from export. The kit shares one split across all stages; never train from the unsplit dataset files when measuring the held-out sets.
- The kit renders tool calls before Arrow loading and learns only complete assistant targets, masking user text and tool observations.
  Every original token and mask is checked against the real trainer. No implicit 1024-token truncation is accepted: examples must fit
  the model's declared context (`--sequence-length` may set a smaller bound). Oversized episodes refuse preparation; `--skip-oversize`
  explicitly omits whole episodes with counts and reasons. Invalid templates or changed trainer tokens always refuse preparation.
- Pin a remote model/tokenizer with `--revision COMMIT`. Preflight with `--base` may probe a small fixture; the report marks the override.
  Such a probe verifies that fixture, not the intended large model, GPU or subsequent learning quality.
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
        ("preflight", "python train.py --stage logic --tokenizer-only --from-base; python train.py --stage logic --preflight --from-base",
         "install hardware-appropriate torch and requirements-train.txt first; real trainer check, no training"),
        ("train", "python train.py --stage sft   (then optionally --stage logic, --stage kto or --stage dpo)", "only on an explicit training decision; a preflight alone changes no weights"),
        ("convert", "./convert.sh", "the adapter as GGUF for llama.cpp, and the llama-server line"),
        ("probe", "python probe.py answer; python probe.py judge --url URL --model NAME; python probe.py summarize",
         "did training teach the trained knowledge? blind, never-trained questions about trained objects"),
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


TRAIN_PY = r'''"""Fine-tuning kit entry point. First run --preflight (no training); --tokenizer-only loads no model weights.
Stages: sft, agentic, logic, kto, dpo; with a kit written with --philosophy NAME also the seed path language → philosophy → grpo
(the clingo-object language from the base, the seed SFT continuing out/language, GRPO with the seed as reward continuing out/philosophy).
Use --from-adapter to continue a selected prior stage.
"""
from training_runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
'''


EVALUATE_PY = r'''"""Collect paired predictions; correctness comes from independent judgments, never keyword overlap."""
import argparse, hashlib, json
from clingo_object.agent import chat_post
from evaluation_core import summarize_judgments

a = argparse.ArgumentParser()
a.add_argument("--base", required=True)
a.add_argument("--tuned", required=True)
a.add_argument("--judgments", help="JSON list: id, group, base_correct, tuned_correct, reference")
o = a.parse_args()
rows = [json.loads(l) for l in open("split/test.jsonl", encoding="utf-8") if l.strip()]
evaluation_hash = hashlib.sha256(open("split/test.jsonl", "rb").read()).hexdigest()
if o.judgments:
    prediction_file = json.load(open("predictions.json", encoding="utf-8"))
    if prediction_file.get("evaluation_set_sha256") != evaluation_hash:
        raise ValueError("predictions do not belong to the held-out file")
    predictions = {p["id"]: p for p in prediction_file["predictions"]}

    judgments = json.load(open(o.judgments, encoding="utf-8"))
    ids = {r["meta"]["id"] + ":" + str(i) for i, r in enumerate(rows)}
    if {r["id"] for r in judgments} != ids or len(judgments) != len(rows):
        raise ValueError("judgments must cover exactly the held-out questions")
    for i, r in enumerate(rows):
        j = next(j for j in judgments if j["id"] == r["meta"]["id"] + ":" + str(i))
        j["group"] = r["meta"].get("group", r["meta"]["id"])
    if set(predictions) != ids or len(prediction_file["predictions"]) != len(rows):
        raise ValueError("predictions must cover exactly the held-out questions")
    incomplete = {"base": 0, "tuned": 0}
    for judgment in judgments:
        prediction = predictions[judgment["id"]]
        for name in ("base", "tuned"):
            if prediction.get(name + "_complete") is not True:
                judgment[name + "_correct"] = False
                incomplete[name] += 1
    summary = summarize_judgments(judgments)
    summary["incomplete_predictions"] = incomplete
    summary["predictions_sha256"] = hashlib.sha256(open("predictions.json", "rb").read()).hexdigest()
    summary["evaluation_set_sha256"] = evaluation_hash
    json.dump(summary, open("eval.json", "w", encoding="utf-8"), indent=2)
    print(json.dumps(summary, indent=2))
else:
    predictions = []
    for i, r in enumerate(rows):
        q = r["messages"][0]["content"]
        item = {"id": r["meta"]["id"] + ":" + str(i), "question": q, "reference_answer": r["messages"][1]["content"]}
        for name, url in (("base", o.base), ("tuned", o.tuned)):
            body = {"messages": [{"role": "user", "content": q}], "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
            choice = chat_post(url, body, timeout=600)["choices"][0]
            item[name] = choice["message"].get("content") or ""
            item[name + "_complete"] = choice.get("finish_reason") == "stop"
        predictions.append(item)
    json.dump({"evaluation_set_sha256": evaluation_hash, "predictions": predictions}, open("predictions.json", "w", encoding="utf-8"), indent=2)
    print("Predictions collected. Supply independent --judgments; no correctness score has been inferred.")
'''


SYNTH_QA_PY = r'''"""Question-answer pairs for documents the server has not stored pairs for (dataset/documents.jsonl -> dataset/qa_synth.jsonl).

Since 0.65.0 the server stores grounded pairs and a probe question on each knowledge object while it sleeps (`vi-mcp classify --pairs`);
the export puts them into qa.jsonl and probe.jsonl. This script fills in the rest, with the SAME definition of a good pair (qa_pairs.py,
copied from the server): self-contained question, not copied from the document's beginning, >= 80 % of the answer's words in the document.
Per document one kept pair becomes its probe (dataset/probe_synth.jsonl) unless it already has one: never trained, it measures after
training whether the model learned that document. Pairs too close to a probe or a --hold-out question are rejected. Rejections are
counted per reason. Resumable: documents already in qa_synth.jsonl or synth_rejected.jsonl are skipped. No token cap (the model ends its
own answer); thinking is switched off. Then run `vi-mcp finetune split KIT` so the pairs and probes join the shared split.
The pairs are model output checked for word overlap, not verified by a person.
"""
import argparse, concurrent.futures as cf, json, random, threading, time, urllib.request
from qa_pairs import (DOC_CHARS, PAIRS, SUPPORT_SYSTEM, apply_support, key, parse, prompt_sha256, select, split_probe, support_user,
                      system_for)


def _chat(url, model, system, user, temperature):
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]


def ask(url, model, document, system):
    choice = _chat(url, model, system, document[:DOC_CHARS], 0.3)
    return parse(choice["message"].get("content") or ""), choice.get("finish_reason")


def support(url, model, document, pairs):
    """qa-v4: the model may only reject; an incomplete answer keeps nothing (the document is retried in a later run)."""
    choice = _chat(url, model, SUPPORT_SYSTEM, support_user(document, pairs), 0)
    return apply_support(pairs, choice["message"].get("content") or "")


def rows(name):
    try:
        return [json.loads(l) for l in open(name, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--url", required=True, help="OpenAI-compatible base URL, e.g. http://host:8080/v1")
    a.add_argument("--model", required=True)
    a.add_argument("--limit", type=int, default=0, help="at most this many documents in this run (seeded random order); 0 = all")
    a.add_argument("--workers", type=int, default=4)
    a.add_argument("--seed", type=int, default=1114)
    a.add_argument("--pairs", type=int, default=PAIRS, help="pairs asked per document; more varied pairs per fact inject knowledge "
                   "better (paraphrase scaling: arXiv 2312.05934, 2411.00686)")
    a.add_argument("--more", help="file of object ids (one per line): ask these documents again for further pairs, even if done")
    a.add_argument("--hold-out", help="JSONL of {id, question} kept out of training (evaluation probes): a pair whose question is "
                   "this close (word Jaccard >= 0.5) to one of them is rejected")
    o = a.parse_args()
    system, psha = system_for(o.pairs), prompt_sha256(o.pairs)
    held = {}
    for h in rows(o.hold_out) if o.hold_out else []:
        held.setdefault(h["id"], []).append(h["question"])
    probed = set()
    for name in ("dataset/probe.jsonl", "dataset/probe_synth.jsonl"):  # the probes are held out of every later pair, too
        for h in rows(name):
            held.setdefault(h["id"], []).append(h["question"])
            probed.add(h["id"])
    asked = {}
    for r in rows("dataset/qa_synth.jsonl"):
        asked.setdefault(r["meta"]["id"], set()).add(key(r["messages"][0]["content"]))
    docs = rows("dataset/documents.jsonl")
    done = {r["meta"]["id"] for name in ("dataset/qa_synth.jsonl", "dataset/synth_rejected.jsonl") for r in rows(name)}
    again = {l.strip() for l in open(o.more, encoding="utf-8") if l.strip()} if o.more else set()
    todo = [d for d in docs if d["meta"]["id"] in again] if o.more else [d for d in docs if d["meta"]["id"] not in done]
    random.Random(o.seed).shuffle(todo)
    todo = todo[: o.limit] if o.limit else todo
    lock, stats, t0 = threading.Lock(), {"documents": 0, "pairs": 0, "probes": 0, "rejected": {}}, time.time()
    out = open("dataset/qa_synth.jsonl", "a", encoding="utf-8")
    rej = open("dataset/synth_rejected.jsonl", "a", encoding="utf-8")
    probe_f = open("dataset/probe_synth.jsonl", "a", encoding="utf-8")

    def checked(d, pairs):
        """fixed rules first (select), then the model support check, which may only reject"""
        kept, rejected = select(pairs, d["document"], held.get(d["meta"]["id"], []), set(asked.get(d["meta"]["id"], set())))
        if not kept:
            return kept, rejected, None
        try:
            kept2, rej2, complete = support(o.url, o.model, d["document"], kept)
        except Exception as e:  # noqa: BLE001
            return [], rejected, f"request failed: support {type(e).__name__}"
        if not complete:
            return [], rejected, "request failed: support check incomplete"
        for k, v in rej2.items():
            rejected[k] = rejected.get(k, 0) + v
        return kept2, rejected, None

    def one(d):
        try:
            pairs, finish = ask(o.url, o.model, d["document"], system)
        except Exception as e:  # noqa: BLE001 — a failed call is counted, never a silent gap; the next run retries it
            return d, None, {}, f"request failed: {type(e).__name__}"
        if pairs is None or finish != "stop":
            return d, [], {}, "no JSON answer" if finish == "stop" else f"finish_reason {finish}"
        kept, rejected, serr = checked(d, pairs)  # in the worker: the support check runs in parallel too
        return d, kept, rejected, serr

    with cf.ThreadPoolExecutor(o.workers) as pool:
        for d, kept, rejected, error in pool.map(one, todo):
            with lock:
                oid = d["meta"]["id"]
                stats["documents"] += 1
                kept = kept or []
                for p in kept:
                    asked.setdefault(oid, set()).add(key(p["question"]))
                probe = None
                if oid not in probed:
                    kept, probe, close = split_probe(oid, kept)
                    if close:
                        rejected["too close to the object's probe question"] = close
                if error:
                    rejected[error] = rejected.get(error, 0) + 1
                for why, n in rejected.items():
                    stats["rejected"][why] = stats["rejected"].get(why, 0) + n
                meta = {**d["meta"], "question_source": "synthetic", "generator": o.model, "prompt_sha256": psha}
                for p in kept:
                    out.write(json.dumps({"messages": [{"role": "user", "content": p["question"]},
                                                       {"role": "assistant", "content": p["answer"] + f"\n\nSource: {d['source']}"}],
                                          "meta": meta}, ensure_ascii=False) + "\n")
                if probe:
                    probed.add(oid)
                    held.setdefault(oid, []).append(probe["question"])
                    probe_f.write(json.dumps({"id": oid, **probe, "source": d["source"], "meta": {**meta, "question_source": "probe"}},
                                             ensure_ascii=False) + "\n")
                    stats["probes"] += 1
                stats["pairs"] += len(kept)
                if not kept and not (error or "").startswith("request failed"):
                    rej.write(json.dumps({"meta": {"id": oid}, "reasons": rejected}, ensure_ascii=False) + "\n")
                out.flush(); rej.flush(); probe_f.flush()
                if stats["documents"] % 20 == 0:
                    print(f"{stats['documents']}/{len(todo)} documents, {stats['pairs']} pairs, {round(time.time() - t0)} s", flush=True)
    stats.update(seconds=round(time.time() - t0), generator=o.model, prompt_sha256=psha, pairs_asked=o.pairs,
                 remaining=len([d for d in docs if d["meta"]["id"] not in done]) - (0 if o.more else len(todo)))
    json.dump(stats, open("synth_report.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
'''


PROBE_PY = r'''"""Knowledge probe: did training teach the model the knowledge it was trained on? (0.65.0)

split/probe.jsonl holds one question per TRAINED object that was never trained (a stored pair held out by the server or synth_qa.py).
A split by object cannot show this: unseen objects test generalisation, which fine-tuning does not give (measured 14.11.2026). Steps:
  python probe.py answer [--adapter out/sft]      base and base+adapter answer every probe question; written per question, resumable:
                                                  probe/answers_blind.jsonl (sides A/B in seeded random order) and probe/ab_key.jsonl
  python probe.py judge --url URL --model NAME    an OpenAI-compatible model grades A and B against the reference without the key:
                                                  probe/judgments.jsonl (a person may write the same file by hand instead)
  python probe.py summarize                       unblinds and tests: probe/probe_eval.json
Grades: correct (states the reference's key fact, nothing contradicting), partial (part of it, or right with a wrong detail), wrong
(wrong, missing, "I don't know", loop). An answer that hit the generation budget counts at most partial. The decision is the kit's
gate: one-sided sign-flip test over object groups, p < 0.05 and a positive difference, strict (correct) and lenient (correct or
partial). Measured with this procedure (14.11.2026, Qwen3-0.6B, 60 probes): run 3 tuned 7 correct / 9 partial, base 0 / 5, strict p 0.008.
Limits: the probe questions come from the same generator as the training pairs; a judge model of the same family as the generator may
favour its own wording (self-preference, arXiv 2306.05685) — the judge is recorded and named in the result.
"""
import argparse, hashlib, json, os, sys, time

SYSTEM = "Answer the question factually and concisely. If you do not know the answer, say so."
GRADES = ("correct", "partial", "wrong")
JUDGE = ("You grade answers to a question against a reference answer. For EACH of the answers A and B decide: correct = it states the "
         "reference's key fact(s) and nothing contradicting them; partial = it states part of the key facts, or the right fact with a wrong "
         "detail; wrong = wrong, missing, evasive, 'I don't know', repetitive or garbled. Judge facts, not style or length. An answer marked "
         "as cut off is at most partial. Reply with JSON only: {\"A\": \"correct|partial|wrong\", \"B\": \"correct|partial|wrong\", "
         "\"reason\": \"one sentence\"}")


def rows(name):
    try:
        return [json.loads(l) for l in open(name, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def sha(name):
    return hashlib.sha256(open(name, "rb").read()).hexdigest() if os.path.exists(name) else None


def answer(o):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base = json.load(open("run.json", encoding="utf-8"))["base_model"]
    device = "cuda" if torch.cuda.is_available() and not o.cpu else "cpu"
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float32).to(device)
    model = PeftModel.from_pretrained(model, o.adapter).eval()
    os.makedirs("probe", exist_ok=True)
    done = {r["id"] for r in rows("probe/answers_blind.jsonl")}

    def one(question):
        text = tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                                       add_generation_prompt=True, enable_thinking=False, tokenize=False)
        ids = tok(text, return_tensors="pt", add_special_tokens=False).to(device)
        with torch.no_grad():  # greedy; the budget is a resource bound against endless loops of a small model, named, never a silent cut
            out = model.generate(**ids, do_sample=False, max_new_tokens=o.budget, eos_token_id=tok.eos_token_id,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        new = out[0, ids["input_ids"].shape[1]:].tolist()
        return tok.decode(new, skip_special_tokens=True).strip(), "stop" if new and new[-1] == tok.eos_token_id else "budget"

    probes = rows("split/probe.jsonl")
    if done:  # resuming: only the same probe file and the same adapter (Codex's review 15.11.2026)
        prev = json.load(open("probe/answer_run.json", encoding="utf-8")) if os.path.exists("probe/answer_run.json") else {}
        if prev.get("probe_sha256") != sha("split/probe.jsonl") or prev.get("adapter_sha256") != sha(os.path.join(o.adapter, "adapter_model.safetensors")):
            raise SystemExit("probe/ holds answers of another probe file or adapter — move it away first")
    else:
        json.dump({"adapter": o.adapter, "adapter_sha256": sha(os.path.join(o.adapter, "adapter_model.safetensors")),
                   "probe_sha256": sha("split/probe.jsonl")}, open("probe/answer_run.json", "w", encoding="utf-8"), indent=1)
    blind, keyf, t0 = open("probe/answers_blind.jsonl", "a", encoding="utf-8"), open("probe/ab_key.jsonl", "a", encoding="utf-8"), time.time()
    for i, p in enumerate(probes):
        if p["id"] in done:
            continue
        with model.disable_adapter():
            b = one(p["question"])
        t = one(p["question"])
        tuned_first = hashlib.sha256(f"probe:{p['id']}".encode()).digest()[0] < 128  # depends only on the id: a resumed run keeps it
        x, y = (t, b) if tuned_first else (b, t)
        blind.write(json.dumps({"id": p["id"], "group": (p.get("meta") or {}).get("group") or p["id"], "question": p["question"],
                                "reference": p["answer"], "A": x[0], "A_finish": x[1], "B": y[0], "B_finish": y[1]}, ensure_ascii=False) + "\n")
        keyf.write(json.dumps({"id": p["id"], "A": "tuned" if tuned_first else "base", "B": "base" if tuned_first else "tuned"}) + "\n")
        blind.flush(); keyf.flush()
        print(f"{i + 1}/{len(probes)} {round(time.time() - t0)} s", flush=True)
    json.dump({"adapter": o.adapter, "adapter_sha256": sha(os.path.join(o.adapter, "adapter_model.safetensors")), "budget": o.budget,
               "base_model": base, "device": device, "system_prompt": SYSTEM, "probe_sha256": sha("split/probe.jsonl")},
              open("probe/answer_run.json", "w", encoding="utf-8"), indent=1)


def judge(o):
    import urllib.request
    done = {r["id"] for r in rows("probe/judgments.jsonl")}
    out = open("probe/judgments.jsonl", "a", encoding="utf-8")
    for r in rows("probe/answers_blind.jsonl"):
        if r["id"] in done:
            continue
        user = (f"Question: {r['question']}\n\nReference answer: {r['reference']}\n\nAnswer A"
                + (" (cut off at the generation budget)" if r["A_finish"] != "stop" else "") + f": {r['A']}\n\nAnswer B"
                + (" (cut off at the generation budget)" if r["B_finish"] != "stop" else "") + f": {r['B']}")
        body = {"model": o.model, "messages": [{"role": "system", "content": JUDGE}, {"role": "user", "content": user}], "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(o.url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            text = json.load(resp)["choices"][0]["message"].get("content") or ""
        import re
        m = re.search(r"\{.*\}", text, re.S)
        g = json.loads(m.group(0)) if m else {}
        if g.get("A") not in GRADES or g.get("B") not in GRADES:
            print(f"{r['id']}: judge answer outside the grades, left for a rerun or a person", file=sys.stderr)
            continue
        out.write(json.dumps({"id": r["id"], "A": g["A"], "B": g["B"], "reason": g.get("reason", ""), "judge": o.model}, ensure_ascii=False) + "\n")
        out.flush()


def summarize(o):
    from evaluation_core import summarize_judgments
    answers = {r["id"]: r for r in rows("probe/answers_blind.jsonl")}
    key = {r["id"]: r for r in rows("probe/ab_key.jsonl")}
    judged = rows("probe/judgments.jsonl")
    if not judged or any(j["id"] not in key or j["id"] not in answers for j in judged):
        raise SystemExit("judgments must belong to probe/answers_blind.jsonl and probe/ab_key.jsonl")
    # The answers must belong to TODAY's probe file (Codex's review 15.11.2026: old judgments were relabelled with the current probe hash)
    run = json.load(open("probe/answer_run.json", encoding="utf-8")) if os.path.exists("probe/answer_run.json") else {}
    current = {p["id"] for p in rows("split/probe.jsonl")}
    if run.get("probe_sha256") != sha("split/probe.jsonl") or not set(answers) <= current:
        raise SystemExit("probe/answers_blind.jsonl was made from another split/probe.jsonl — move probe/ away and run probe.py answer again")
    if len(judged) != len({j["id"] for j in judged}):
        raise SystemExit("a probe question is judged twice — keep one judgment per question")
    if {j["id"] for j in judged} != current:
        raise SystemExit(f"judgments cover {len({j['id'] for j in judged})} of {len(current)} probe questions — judge all of them first")
    sides = []
    for j in judged:
        a, k = answers[j["id"]], key[j["id"]]
        grade = {}
        for s in ("A", "B"):
            gr = j[s] if a[s + "_finish"] == "stop" or j[s] != "correct" else "partial"  # a cut answer is at most partial
            grade[k[s]] = gr
        sides.append({"id": j["id"], "group": a["group"], "reference": a["reference"], "base": grade["base"], "tuned": grade["tuned"]})
    def test(ok):
        return summarize_judgments([{"id": x["id"], "group": x["group"], "reference": x["reference"],
                                     "base_correct": x["base"] in ok, "tuned_correct": x["tuned"] in ok} for x in sides])
    result = {"metric": "knowledge_probe", "n": len(sides), "grades": {who: {g: sum(x[who] == g for x in sides) for g in GRADES}
                                                                      for who in ("base", "tuned")},
              "strict": test(("correct",)), "lenient": test(("correct", "partial")),
              "judges": sorted({j.get("judge", "person") for j in judged}),
              "generators": sorted({(p.get("meta") or {}).get("generator") or "?" for p in rows("split/probe.jsonl")}),
              "answers_sha256": sha("probe/answers_blind.jsonl"), "judgments_sha256": sha("probe/judgments.jsonl"),
              "probe_sha256": run["probe_sha256"], "answer_run": run}
    result["decision"] = bool(result["strict"]["decision"])
    if set(result["judges"]) & set(result["generators"]):
        result["warning"] = "the judge is the model that wrote the probe questions: self-preference is possible; a person or another model family should check a sample"
    json.dump(result, open("probe/probe_eval.json", "w", encoding="utf-8"), indent=2)
    print(json.dumps({k: result[k] for k in ("n", "grades", "decision")} | {"strict_p": result["strict"]["p_one_sided"],
                                                                          "lenient_p": result["lenient"]["p_one_sided"]}, indent=2))


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    u = a.add_subparsers(dest="cmd", required=True)
    x = u.add_parser("answer")
    x.add_argument("--adapter", default="out/sft")
    x.add_argument("--budget", type=int, default=2048, help="new-token resource bound against loops; reaching it is named 'budget'")
    x.add_argument("--cpu", action="store_true")
    j = u.add_parser("judge")
    j.add_argument("--url", required=True)
    j.add_argument("--model", required=True)
    u.add_parser("summarize")
    o = a.parse_args()
    {"answer": answer, "judge": judge, "summarize": summarize}[o.cmd](o)


if __name__ == "__main__":
    main()
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
    """One connected-component split across ALL stages: object, source, duplicate content and program family stay together."""
    data = {name: [json.loads(s) for s in (qa_path.parent / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
            if (qa_path.parent / f"{name}.jsonl").exists() else [] for name in ("qa", "agentic", "logic", "kto", "dpo")}
    synth = qa_path.parent / "qa_synth.jsonl"  # synth_qa.py output: QA rows like qa.jsonl, split with their source object's group
    if synth.exists():
        data["qa"] += [json.loads(s) for s in synth.read_text(encoding="utf-8").splitlines() if s.strip()]
    probes = [json.loads(s) for name in ("probe.jsonl", "probe_synth.jsonl") if (qa_path.parent / name).exists()
              for s in (qa_path.parent / name).read_text(encoding="utf-8").splitlines() if s.strip()]
    # A probe stays untrained: no training question of its object may come close to it, whatever produced the question (doc2query,
    # stored pairs, synth_qa.py) — the one place every training row passes (Codex's review 15.11.2026).
    from .qa_pairs import HOLD_OUT_JACCARD, jaccard
    held = {}
    for r in probes:
        held.setdefault(r["id"], []).append(r["question"])
    def too_close(r):
        first = next((m.get("content") or "" for m in r.get("messages") or [] if m.get("role") == "user"), "")
        return any(jaccard(first, h) >= HOLD_OUT_JACCARD for h in held.get((r.get("meta") or {}).get("id"), []))
    near = []
    for stage in ("qa", "agentic"):  # every stage that asks the object's question in plain words
        out = [r for r in data[stage] if too_close(r)]
        if out:
            gone = {id(r) for r in out}
            data[stage] = [r for r in data[stage] if id(r) not in gone]
            near += out
    parent = {}
    def root(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = root(parent[x])
        return parent[x]
    def keys(row):
        m = row.get("meta") or {}
        refs = ["id:" + str(m[k]) for k in ("id", "chosen", "rejected") if m.get(k)]
        refs += [k + ":" + str(m[k]) for k in ("group", "content_hash", "program_family") if m.get(k)]
        return refs or ["row:" + hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()]
    for rows in data.values():
        for r in rows:
            refs = keys(r)
            for x in refs[1:]:
                parent[root(x)] = root(refs[0])
    groups = sorted({root(keys(r)[0]) for rows in data.values() for r in rows})
    rnd = random.Random(seed)
    test_groups = set(rnd.sample(groups, max(1, int(len(groups) * share)))) if len(groups) > 1 else set()
    # Stratified per stage (14.11.2026): the joint sample above can miss a small stage entirely — the production kit's logic stage
    # had 14 groups and 0 test rows, so its gain was unmeasurable. Each stage with at least STRATIFY_MIN groups gets its share of
    # test groups; components stay joint across stages, so this adds held-out groups and never splits one.
    for rows in data.values():
        own = sorted({root(keys(r)[0]) for r in rows})
        if len(own) >= STRATIFY_MIN:
            want = max(1, round(len(own) * share))
            have = [x for x in own if x in test_groups]
            if len(have) < want:
                test_groups |= set(rnd.sample([x for x in own if x not in test_groups], want - len(have)))
    out_dir.mkdir(exist_ok=True)
    counts = {}
    for stage, rows in data.items():
        train = [r for r in rows if root(keys(r)[0]) not in test_groups
                 and not (stage in ("logic", "dpo") and (r.get("meta") or {}).get("validation") in ("solver_only", "observational"))]
        test = [r for r in rows if root(keys(r)[0]) in test_groups]
        for side, part in (("train", train), ("test", test)):
            path = out_dir / (f"{side}.jsonl" if stage == "qa" else f"{stage}.{side}.jsonl")
            _write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part))
        counts[stage] = {"train": len(train), "test": len(test), "withheld": len(rows) - len(train) - len(test),
                         "groups": len({root(keys(r)[0]) for r in rows}), "test_groups": len({root(keys(r)[0]) for r in test})}
        if counts[stage]["withheld"]:
            counts[stage]["reason"] = "solver-only program demonstration or observational preference; no independent task verification"
    # 0.65.0 knowledge probe: one stored pair per object, never trained (dataset/probe.jsonl from the server, probe_synth.jsonl from
    # synth_qa.py). Kept only for objects whose QA rows are on the TRAIN side — it asks whether training taught that object; a probe of a
    # test-side object would measure generalisation to unseen knowledge, which fine-tuning does not give (14.11.2026, run 2 and 3).
    trained = {r["meta"]["id"] for r in data["qa"] if root(keys(r)[0]) not in test_groups}
    kept_probes = [r for r in probes if r["id"] in trained]
    _write(out_dir / "probe.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept_probes))
    probe_counts = {"trained_objects": len(kept_probes), "objects_not_trained": len(probes) - len(kept_probes),
                    "training_rows_withheld_as_too_close": len(near)}
    test_ids = {r["meta"]["id"] for r in data["qa"] if root(keys(r)[0]) in test_groups}
    sources = {side: dict(Counter((r.get("meta") or {}).get("question_source") for r in data["qa"] if (root(keys(r)[0]) in test_groups) == (side == "test")))
               for side in ("train", "test")}
    return {**counts["qa"], "objekte_test": len(test_ids), "groups": len(groups), "test_groups": len(test_groups), "stages": counts,
            "qa_question_sources": sources, "probe": probe_counts}


def resplit(directory: str) -> dict:
    """Redo the shared split after synth_qa.py added dataset/qa_synth.jsonl; run.json records the new split and the synth file's hash."""
    d = Path(directory)
    if not (d / "run.json").exists():
        raise ValueError(f"{d}: no run.json — not a kit written by vi-mcp finetune kit")
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    run["split"] = _split(d / "dataset" / "qa.jsonl", d / "split")
    synth = d / "dataset" / "qa_synth.jsonl"
    run["qa_synth_sha256"] = hashlib.sha256(synth.read_bytes()).hexdigest() if synth.exists() else None
    probe = d / "dataset" / "probe_synth.jsonl"
    run["probe_synth_sha256"] = hashlib.sha256(probe.read_bytes()).hexdigest() if probe.exists() else None
    _write(d / "run.json", json.dumps(run, indent=2, ensure_ascii=False))
    return run["split"]


HELDOUT_LOSS_PY = r'''"""Held-out next-token loss of the base model and, optionally, a LoRA adapter on one stage's TEST split.

Same tokens and masks as training (training_runtime.prepare: assistant targets only), a seeded sample of whole held-out rows.
Lower loss on held-out rows shows that the model absorbed the VI's knowledge for that stage. It is NOT the adoption gate:
task success needs independent judgments (evaluate.py) or executable references (program_evaluate.py).
    python heldout_loss.py --stage sft [--adapter out/sft] [--base-only] [--examples 400] [--fp32]
"""
import argparse, json, math, random, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from training_runtime import prepare

FILES = {"sft": "split/test.jsonl", "agentic": "split/agentic.test.jsonl", "logic": "split/logic.test.jsonl",
         "language": "split/language.test.jsonl", "philosophy": "split/philosophy.test.jsonl"}
a = argparse.ArgumentParser()
a.add_argument("--stage", choices=sorted(FILES), default="sft")
a.add_argument("--adapter", help="LoRA adapter directory (default out/<stage>)")
a.add_argument("--base-only", action="store_true")
a.add_argument("--examples", type=int, default=400)
a.add_argument("--fp32", action="store_true", help="float32 weights (default on CPU)")
a.add_argument("--sequence-length", type=int, default=4096)
o = a.parse_args()
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float32 if (o.fp32 or device == "cpu") else "auto"
base = json.load(open("run.json", encoding="utf-8"))["base_model"]
rows = [json.loads(l) for l in open(FILES[o.stage], encoding="utf-8") if l.strip()]
if not rows:
    raise SystemExit(f"{FILES[o.stage]} is empty: no held-out rows for stage {o.stage}")
random.Random(7).shuffle(rows)
tok = AutoTokenizer.from_pretrained(base)
data, audit = prepare(rows, tok, o.stage, o.sequence_length, skip_oversize=True)
data = data[:o.examples]


def score(model):
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for ex in data:
            ids = torch.tensor([ex["input_ids"]], device=device)
            labels = torch.tensor([ex["labels"]], device=device)
            logits = model(input_ids=ids).logits[0, :-1].float()
            target = labels[0, 1:]
            mask = target != -100
            total -= float(torch.log_softmax(logits[mask], dim=-1).gather(1, target[mask].unsqueeze(1)).sum())
            count += int(mask.sum())
    return total / count, count


t0 = time.time()
model = AutoModelForCausalLM.from_pretrained(base, dtype=dtype).to(device)
base_nll, tokens = score(model)
out = {"metric": "held_out_assistant_token_nll", "stage": o.stage, "file": FILES[o.stage], "examples": len(data), "tokens": tokens,
       "sample_seed": 7, "device": device, "dtype": str(dtype), "base_nll": base_nll, "base_perplexity": math.exp(min(700, base_nll)),
       "oversize_skipped": audit["rejected"].get("oversize", 0),
       "scope": "held-out rows of this kit's split; knowledge absorption, not verified task success"}
if not o.base_only:
    from peft import PeftModel
    adapter = o.adapter or f"out/{o.stage}"
    tuned_nll, _ = score(PeftModel.from_pretrained(model, adapter))
    out.update(adapter=adapter, tuned_nll=tuned_nll, difference=tuned_nll - base_nll, tuned_perplexity=math.exp(min(700, tuned_nll)))
out["seconds"] = round(time.time() - t0, 1)
json.dump(out, open(f"heldout-loss-{o.stage}.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(out, indent=1))
'''


PROGRAM_EVALUATE_PY = r'''"""Evaluate program generation on frozen held-out tasks. No training or live tools are executed."""
import argparse, hashlib, json
from clingo_object.agent import program_of, SYSTEM, chat_post
from evaluation_core import evaluate_program, summarize_judgments

a = argparse.ArgumentParser()
a.add_argument("--base", required=True, help="base chat completions URL")
a.add_argument("--tuned", required=True, help="tuned chat completions URL")
a.add_argument("--predictions", help="optional JSON list: id, base program, tuned program (offline replay)")
o = a.parse_args()
cases = [json.loads(l) for l in open("program_eval.jsonl", encoding="utf-8") if l.strip()]
cached_rows = json.load(open(o.predictions, encoding="utf-8")) if o.predictions else []
cached = {r["id"]: r for r in cached_rows}
if o.predictions and (set(cached) != {r["id"] for r in cases} or len(cached_rows) != len(cases)):
    raise ValueError("cached predictions must cover exactly the held-out tasks")
judgments, details = [], []
for row in cases:
    outputs = {}
    for name, url in (("base", o.base), ("tuned", o.tuned)):
        if o.predictions:
            source = cached[row["id"]][name]
        else:
            q = row["question"] + "\nFrozen objects (use only these tags and filters):\n" + json.dumps(row["case"].get("input_objects", row["case"].get("objects", {})))
            body = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}],
                    "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
            choice = chat_post(url, body, timeout=600)["choices"][0]
            if choice.get("finish_reason") != "stop":
                outputs[name] = {"correct": False, "error": "incomplete_model_output", "state": "refused"}
                continue
            source = program_of(choice["message"].get("content") or "")
        outputs[name] = evaluate_program(source, row["case"])
    judgments.append({"id": row["id"], "group": row["group"], "base_correct": outputs["base"]["correct"],
                      "tuned_correct": outputs["tuned"]["correct"], "reference": row["reference"]})
    details.append({"id": row["id"], **outputs})
summary = summarize_judgments(judgments)
summary["evaluation_set_sha256"] = hashlib.sha256(open("program_eval.jsonl", "rb").read()).hexdigest()
summary["evaluation_kind"] = "program"
json.dump({**summary, "details": details}, open("program_eval_result.json", "w", encoding="utf-8"), indent=2)
print(json.dumps(summary, indent=2))
'''


def _write(p: Path, text: str, mode: int = 0o600) -> None:
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, mode)


#: GRPO prompts a kit gets with --philosophy (each solved by the seed at kit time and again before training)
PHILOSOPHY_PROMPTS = 1000
#: rows of the language stage (clingo-object both ways) and of the seed SFT stage — the sizes of run 6 (15.11.2026)
LANGUAGE_ROWS = 3000
PHILOSOPHY_ROWS = 1700
#: 0.70.9: share of clingo-object translation rows replayed inside the philosophy stage. Without it the stage overwrote the language
#: stage: run 13 (official kit13, kollektiv 1.3.0, 19.11.2026) answered "none" to all 30 language items and 12 of 13 seed explanations,
#: because 5,399 philosophy rows held no translation and 283 answered exactly "none"; the hand-built kits that kept ~36 % language rows
#: in their second stage kept the language (run 32: write 16/18). Rehearsal of the earlier stage is the standard remedy.
LANGUAGE_REPLAY_SHARE = 0.2
HELDOUT_ROWS = 40
#: what a package needs for training data, beyond what check() asks (philosophy_train: worlds drawn, facts and verdicts in words)
TRAINING_FIELDS = ("generator", "domains", "render", "render_test", "speak", "pressure", "pressure_test")

PHIL_ANSWERS_PY = r'''"""Answers of the base model and of base + adapter to eval/philosophy.jsonl, written per item (resumable).

Scored afterwards by the seed's verdict (phil_score.py), not by a judge. Greedy, thinking off, the same messages for both. The new-token
budget is a resource bound of local generation against endless loops of a small model, not an API cap: an answer that reaches it is
marked "budget" and never counts as right.
    python phil_answers.py [--adapter out/philosophy] [--budget 8192] [--fp32]
(0.70.1: 8192 — twice the longest gold answer with reasoning traces, about 3,450 tokens for a world of 10 statements (estimated as
characters / 3); 768 cut most traced answers. Greedy answers stop at the end token, so the budget costs time only for loops.)
"""
import argparse, json, time
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

a = argparse.ArgumentParser()
a.add_argument("--adapter", default="out/philosophy")
a.add_argument("--budget", type=int, default=8192)
a.add_argument("--fp32", action="store_true")
o = a.parse_args()
base = json.load(open("run.json", encoding="utf-8"))["base_model"]
device = "cuda" if torch.cuda.is_available() else "cpu"
tok = AutoTokenizer.from_pretrained(base)
model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float32 if (o.fp32 or device == "cpu") else "auto").to(device)
model = PeftModel.from_pretrained(model, o.adapter).eval()
items = [json.loads(l) for l in open("eval/philosophy.jsonl", encoding="utf-8") if l.strip()]
try:
    done = {json.loads(l)["id"] for l in open("eval/philosophy_answers.jsonl", encoding="utf-8") if l.strip()}
except FileNotFoundError:
    done = set()


def answer(messages):
    text = tok.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False, tokenize=False)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to(device)
    with torch.no_grad():
        out = model.generate(**ids, do_sample=False, max_new_tokens=o.budget, eos_token_id=tok.eos_token_id,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
    new = out[0, ids["input_ids"].shape[1]:].tolist()
    return tok.decode(new, skip_special_tokens=True).strip(), "stop" if new and new[-1] == tok.eos_token_id else "budget"


f, t0 = open("eval/philosophy_answers.jsonl", "a", encoding="utf-8"), time.time()
for i, it in enumerate(items):
    if it["id"] in done:
        continue
    with model.disable_adapter():
        b = answer(it["messages"])
    t = answer(it["messages"])
    f.write(json.dumps({"id": it["id"], "set": it["set"], "adapter": o.adapter, "budget": o.budget, "base": b[0], "base_finish": b[1],
                        "tuned": t[0], "tuned_finish": t[1]}, ensure_ascii=False) + "\n")
    f.flush()
    print(f"{i + 1}/{len(items)} {round(time.time() - t0)} s", flush=True)
'''

PHIL_SCORE_PY = r'''"""Score base and tuned answers (eval/philosophy_answers.jsonl) against the seed's verdict, per evaluation set.

The gold is the solver's verdict stored with each item; the package is the kit's philosophy/ (the one whose hash run.json names).
Judge sets: world_exact (every answer and the duties exactly the seed's), each answer predicate right/total, duties_exact,
invented_certainty (a firm value where the seed has a weaker one or none, over those statements), budget_cut. formalize: facts_exact.
explain_seed, recite and language are prose: not scored here — phil_roundtrip.py scores the prose sets by the round trip.
    python phil_score.py   -> eval/philosophy_score.json
"""
import collections, json
from clingo_object import philosophy as ph, philosophy_recipe as pr, philosophy_train as pt

pkg = ph.load("philosophy")
run = json.load(open("run.json", encoding="utf-8"))
if ph.package_hash(pkg) != (run.get("philosophy") or {}).get("hash"):
    raise SystemExit("philosophy/ differs from the hash in run.json — not the seed this kit was built for")
firm = pt.firm_values(pkg)
items = {json.loads(l)["id"]: json.loads(l) for l in open("eval/philosophy.jsonl", encoding="utf-8") if l.strip()}
answers = [json.loads(l) for l in open("eval/philosophy_answers.jsonl", encoding="utf-8") if l.strip()]
res = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for a in answers:
    it = items[a["id"]]
    task = it["meta"].get("task")
    for who in ("base", "tuned"):
        c = res[it["set"]][who]
        c["n"] += 1
        c["budget_cut"] += a[f"{who}_finish"] != "stop"
        if task in ("explain_seed", "recite", "explain_rules", "write_rules"):
            continue
        if a[f"{who}_finish"] != "stop":
            continue  # a cut answer never counts as right
        traced = it["meta"].get("format") == pr.FORMAT  # 0.70.1: numbered Facts blocks; the verdict is read without the trace
        if task == "formalize":
            gold = {l.replace(" ", "") for l in it["meta"]["facts"].splitlines() if l.strip()}
            c["facts_exact"] += gold == (pr.facts_of(a[who]) if traced else {l.replace(" ", "") for l in a[who].splitlines() if l.strip()})
            continue
        gold = it["meta"]["gold"]
        said = pt.parse_verdict(pkg, pr.verdict_part(a[who]) if traced else a[who])
        if traced:
            c["facts_exact"] += pr.facts_of(a[who]) == {l.replace(" ", "") for l in it["meta"]["facts"].splitlines() if l.strip()}
        sc = pt.score(pkg, gold, said)
        for pred, x in sc["answers"].items():
            c[f"{pred}_right"] += x["right"]
        c["duties_exact"] += sc["duties_exact"]
        c["world_exact"] += sc["duties_exact"] and all(x["wrong"] == 0 and x["missing"] == 0 for x in sc["answers"].values())
        for s in gold["subjects"]:
            for pred, fv in firm.items():
                g = (gold["answers"].get(s) or {}).get(pred)
                m = (said["answers"].get(s) or {}).get(pred)
                if g not in fv:
                    c["uncertain"] += 1
                    c["invented_certainty"] += m in fv
totals = collections.Counter()
for it in items.values():
    g = it["meta"].get("gold")
    if g:
        for s in g["subjects"]:
            for pred in pkg["answers"]:
                totals[(it["id"], pred)] += (g["answers"].get(s) or {}).get(pred) is not None
out = {"package": pkg["name"], "hash": run["philosophy"]["hash"], "sets": {}}
for st, whos in res.items():
    out["sets"][st] = {}
    for who, c in whos.items():
        n = c["n"]
        row = {"items": n, "budget_cut": c["budget_cut"]}
        task = next(it["meta"].get("task") for it in items.values() if it["set"] == st)
        if task in ("explain_seed", "recite", "explain_rules", "write_rules"):
            row["scored"] = "prose: by round trip, phil_roundtrip.py"
        elif task == "formalize":
            row["facts_exact"] = f"{c['facts_exact']}/{n}"
        else:
            for pred in pkg["answers"]:
                total = sum(v for (i, p), v in totals.items() if p == pred and items[i]["set"] == st)
                row[pred] = f"{c[pred + '_right']}/{total}"
            row.update(world_exact=f"{c['world_exact']}/{n}", duties_exact=f"{c['duties_exact']}/{n}",
                       invented_certainty=f"{c['invented_certainty']}/{c['uncertain']}")
        out["sets"][st][who] = row
json.dump(out, open("eval/philosophy_score.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(out, indent=1))
'''


PHIL_ROUNDTRIP_PY = r'''"""Score the PROSE answers of base and tuned (explain_seed, explain_seed_part, recite) by the round trip.

Prose is a translation of the seed and counts only as far as it rebuilds it: an independent back-translator (an OpenAI-compatible
endpoint, preferably another model family than the trained one) writes clingo-object from each answer, with up to 4 repair rounds fed
with clingo's messages (clingo_object/philosophy_explain.py, bundled). Agreement is the share of worlds where the rebuilt seed gives the
seed's answers AND duties: every package world plus --random worlds from the package's generator. For a block item only that block is
rebuilt; the other blocks stay the seed's. A rebuilt seed that does not run agrees with nothing and is reported as not run.
The control, back-translated by the same model, stands beside every number: --control FILE (a frozen prose, e.g. the JSON of
tests/fixtures/kollektiv_principles_1.1.0.json, or plain text), else the items' gold_text (kits of the 1.1.0 format carry the
historical prose there). Without a control, a low number may be the back-translator's limit, not the model's.
The back-translator is an endpoint (--judge-url) or a command (--judge-cmd, e.g. "codex exec -s read-only --skip-git-repo-check": it
runs in a fresh empty directory with stdin closed and gets the prompt as its last argument, the reply is read from its -o file; a
template with {prompt} {out} {dir} {model} works for any other command-line model).
Also writes a blind reading aid: per explain item the answers of both models in a random order, next to the seed's rules, with the
key in a separate file. Works on this kit (eval/philosophy.jsonl, eval/philosophy_answers.jsonl, philosophy/) and on a run-6 kit
(eval/eval.jsonl, eval/answers.jsonl, no philosophy/ directory: name the package with --package).
    python phil_roundtrip.py --judge-url URL | --judge-cmd CMD [--judge-model M] [--random 50] [--control FILE] [--package NAME|DIR] [--who tuned,base]
    -> eval/philosophy_roundtrip.jsonl (per answer, resumable), eval/philosophy_roundtrip.json, eval/philosophy_blind.md, eval/philosophy_blind_key.json
"""
import argparse, collections, json, random, sys, time
from pathlib import Path
from clingo_object import philosophy as ph, philosophy_explain as pe

a = argparse.ArgumentParser()
j = a.add_mutually_exclusive_group(required=True)
j.add_argument("--judge-url", help="back-translator: OpenAI-compatible endpoint (…/v1)")
j.add_argument("--judge-cmd", help="back-translator: a command-line model, e.g. \"codex exec -s read-only --skip-git-repo-check\"")
a.add_argument("--judge-model")
a.add_argument("--random", type=int, default=50, help="random worlds from the package's generator besides its own worlds")
a.add_argument("--rnd-seed", type=int, default=77)
a.add_argument("--control", help="a reference prose: the JSON of a frozen prose (principles: [{id, title, text}]) or plain text")
a.add_argument("--package", help="built-in name or package directory (default: this kit's philosophy/)")
a.add_argument("--items")
a.add_argument("--answers")
a.add_argument("--who", default="tuned,base")
a.add_argument("--out", default="eval/philosophy_roundtrip")
a.add_argument("--no-proxy", action="store_true")
o = a.parse_args()


def first(*names):
    return next((x for x in names if Path(x).exists()), None)


items_f = o.items or first("eval/philosophy.jsonl", "eval/eval.jsonl")
answers_f = o.answers or first("eval/philosophy_answers.jsonl", "eval/answers.jsonl")
if not items_f or not answers_f:
    raise SystemExit("no evaluation items or answers found (eval/philosophy.jsonl + eval/philosophy_answers.jsonl, or eval/eval.jsonl + eval/answers.jsonl)")
run = json.load(open("run.json", encoding="utf-8")) if Path("run.json").exists() else {}
kit_hash = (run.get("philosophy") or {}).get("hash") or run.get("package_hash")
if o.package:
    pkg = ph.load(o.package)
elif Path("philosophy/philosophy.json").exists():
    pkg = ph.load("philosophy")
    if kit_hash and ph.package_hash(pkg) != kit_hash:
        raise SystemExit("philosophy/ differs from the hash in run.json — not the seed this kit was built for")
else:
    raise SystemExit("no philosophy/ in this kit — name the package: --package kollektiv (a run-6 kit was built for kollektiv 1.1.0)")
mismatch = bool(kit_hash) and kit_hash != ph.package_hash(pkg)
if mismatch:
    print(f"grade: the kit was built for hash {kit_hash[:16]}…, scored against {pkg['name']} {pkg['version']} {ph.package_hash(pkg)[:16]}…", file=sys.stderr)
whos = [w for w in o.who.split(",") if w]
items = {json.loads(l)["id"]: json.loads(l) for l in open(items_f, encoding="utf-8") if l.strip()}
prose_items = {i: it for i, it in items.items() if (it.get("meta") or {}).get("task") in ("explain_seed", "recite")}
answers = {json.loads(l)["id"]: json.loads(l) for l in open(answers_f, encoding="utf-8") if l.strip()}


def block_of(it):
    m = it.get("meta") or {}
    return m.get("block") or m.get("principle")


blocks = dict(ph.blocks(pkg["seed"])[0])
if o.judge_cmd:
    judge, judge_name = pe.command_client(o.judge_cmd, o.judge_model), pe.command_name(o.judge_cmd, o.judge_model)
else:
    judge, judge_name = pe.chat_client(o.judge_url, o.judge_model, proxy=not o.no_proxy), o.judge_model or "model at the judge URL"
facts = pe.worlds(pkg, o.random, o.rnd_seed)
gold = [pe.verdict(pkg, f) for f in facts]


def measure(text, block):
    if not (text or "").strip():
        return {"ran": False, "reason": "empty answer", "agreement": 0.0, "same": 0, "worlds": len(facts), "repair_rounds": 0}
    if block and block not in blocks:
        return {"ran": False, "reason": f"block {block} is not in the seed", "agreement": 0.0, "same": 0, "worlds": len(facts), "repair_rounds": 0}
    bt = pe.back_translate(pkg, text, judge, block=block)
    full = pe._with_block(pkg, block, bt["seed"]) if block else bt["seed"]
    ag = pe.agreement(pkg, full, facts, gold)
    ran = not bt.get("failed") and "error" not in ag
    return {"ran": ran, **({"reason": (ag.get("error") or (bt["errors"] or ["no valid rules after the repair rounds"])[-1])[:300]} if not ran else {}),
            "agreement": ag["agreement"] if ran else 0.0, "same": ag["same"] if ran else 0, "worlds": len(facts),
            "repair_rounds": bt["rounds"], "errors": bt["errors"][:3], "rebuilt": bt["seed"]}


# the control: one whole prose and, where the reference has them, one prose per block
control_whole, control_blocks = None, {}
if o.control:
    raw = Path(o.control).read_text(encoding="utf-8")
    try:
        fx = json.loads(raw)
        control_blocks = {p["id"]: p["text"] for p in fx["principles"]}
        control_whole = "\n".join(f"{p['id']} {p.get('title', '')}: {p['text']}" for p in fx["principles"])
    except (ValueError, KeyError, TypeError):
        control_whole = raw
else:
    for it in prose_items.values():
        if it.get("gold_text"):
            if block_of(it):
                control_blocks[block_of(it)] = it["gold_text"]
            elif control_whole is None:
                control_whole = it["gold_text"]
t0 = time.time()
out_rows = Path(o.out + ".jsonl")
earlier = [json.loads(l) for l in out_rows.read_text(encoding="utf-8").splitlines() if l.strip()] if out_rows.exists() else []
done = {(r["id"], r["who"]) for r in earlier}
f = open(out_rows, "a", encoding="utf-8")


def control_row(cid, text, block):
    """The control is measured once and kept like an answer (resumable): who = control."""
    old = next((r for r in earlier if r["id"] == cid and r["who"] == "control"), None)
    if old is not None:
        return old
    r = {"id": cid, "set": "control", "who": "control", "block": block, **measure(text, block)}
    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    f.flush()
    return r


control = {"source": o.control or ("gold_text of the items" if control_whole or control_blocks else None)}
if control_whole:
    control["whole"] = control_row("control:whole", control_whole, None)
needed = {block_of(it) for it in prose_items.values() if block_of(it)}
control["blocks"] = {b: control_row(f"control:{b}", t, b) for b, t in sorted(control_blocks.items()) if b in needed}
todo = [(i, w) for i in sorted(prose_items) for w in whos if i in answers and (i, w) not in done]
for k, (i, w) in enumerate(todo):
    it, ans = prose_items[i], answers[i]
    r = {"id": i, "set": it["set"], "who": w, "block": block_of(it), "finish": ans.get(f"{w}_finish"), **measure(ans.get(w), block_of(it))}
    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    f.flush()
    print(f"{k + 1}/{len(todo)} {i} {w}: {'ran' if r['ran'] else 'did not run'} {r['same']}/{r['worlds']} ({round(time.time() - t0)} s)", flush=True)
f.close()
rows = [r for r in (json.loads(l) for l in out_rows.read_text(encoding="utf-8").splitlines() if l.strip()) if r["who"] != "control"]
summary = {"package": pkg["name"], "version": pkg["version"], "hash": ph.package_hash(pkg), "kit_hash": kit_hash, "hash_mismatch": mismatch,
           "back_translator": judge_name, "worlds": {"package": len(pkg["worlds"]), "random": len(facts) - len(pkg["worlds"]),
           "rnd_seed": o.rnd_seed}, "missing_answers": sorted(i for i in prose_items if i not in answers), "control": control, "sets": {}}
by = collections.defaultdict(list)
for r in rows:
    by[(r["set"], r["who"])].append(r)
for (st, w), rs in sorted(by.items()):
    ran = [r for r in rs if r["ran"]]
    summary["sets"].setdefault(st, {})[w] = {
        "items": len(rs), "ran": len(ran), "budget_cut": sum(r.get("finish") not in (None, "stop") for r in rs),
        "agreement_mean": round(sum(r["agreement"] for r in rs) / len(rs), 3),
        "agreement_mean_of_ran": round(sum(r["agreement"] for r in ran) / len(ran), 3) if ran else None,
        "exact": sum(r["agreement"] == 1.0 for r in rs),
        "per_item": {r["id"]: f"{r['same']}/{r['worlds']}" + ("" if r["ran"] else " (did not run)") for r in rs}}
Path(o.out + ".json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
# the blind reading aid: per explain item both models' prose, in a random order, next to the seed's rules
lines, key = ["# Blind reading: model prose next to the seed's rules", "",
              "Which model wrote which text is in philosophy_blind_key.json — open it only after reading. Judge whether each text says "
              "what the rules say: every condition and exception, nothing added.", ""], {}
code = pe.ph.blocks(pkg["seed"])[0]
for i in sorted(prose_items):
    it = prose_items[i]
    if it["meta"].get("task") != "explain_seed" or i not in answers:
        continue
    b = block_of(it)
    rules = "\n".join(blocks.get(b, [])) if b else "\n".join(f"# {x}\n" + "\n".join(r) for x, r in code)
    order = [w for w in whos if answers[i].get(w)]
    random.Random(i).shuffle(order)
    lines += [f"## {i}", "", "Rules:", "", "```", rules, "```", ""]
    for n, w in enumerate(order, 1):
        lines += [f"### Text {n}", "", answers[i][w], ""]
    key[i] = {f"Text {n}": w for n, w in enumerate(order, 1)}
Path("eval/philosophy_blind.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
Path("eval/philosophy_blind_key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "control"} | {"control": {"whole": (control.get("whole") or {}).get("agreement"),
      "blocks": {b: x["agreement"] for b, x in control["blocks"].items()}}}, indent=1, ensure_ascii=False))
'''


def _rows(path: Path, rows: list[dict]) -> str:
    _write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def philosophy_stage(d: Path, name: str, prompts: int = PHILOSOPHY_PROMPTS, seed: int = 11, language_rows: int = LANGUAGE_ROWS,
                     philosophy_rows: int = PHILOSOPHY_ROWS, heldout: int = HELDOUT_ROWS) -> dict:
    """Everything for the seed path in the same kit as the knowledge stages (one base model, one run.json lineage for `record`):
      language   split/language.{train,test}.jsonl — clingo-object both ways on rule sets that use no predicate of the package
      philosophy split/philosophy.{train,test}.jsonl — the seed's judge, formalize and pressure examples; half of the judge and
                 pressure prompts show the seed's rules (without comment lines); no principle prose anywhere; since 0.70.9 plus a
                 LANGUAGE_REPLAY_SHARE of clingo-object translation rows, so the stage does not overwrite the language stage
      grpo       split/grpo.train.jsonl — the seed as reward
      eval       eval/philosophy.jsonl with phil_answers.py, phil_score.py and phil_roundtrip.py
    Order (the user, 15.11.2026: "first teach the AI clingo, then the seed"): --stage language (from the base), --stage philosophy
    (continues out/language), --stage grpo (continues out/philosophy). The checked package goes to philosophy/, its hash to run.json."""
    from clingo_object import clingo_prose as cp
    from clingo_object import philosophy as ph
    from clingo_object import philosophy_train as pt
    try:  # 0.69.8: an installed philosophy (handed over MCP) too — built in → installed → package directory
        from . import philosophy as vph
        pkg = vph.resolve(name)
    except ph.PackageError:
        raise
    except Exception:  # noqa: BLE001 — no memory open (a kit from a directory only): the package loader alone
        pkg = ph.load(name)
    r = ph.check(pkg)
    if not r["ok"]:
        raise ValueError(f"philosophy {name} refused: " + "; ".join(r["errors"][:3]))
    missing = [k for k in TRAINING_FIELDS if k not in pkg]
    if missing:
        raise ValueError(f"philosophy {name} has no training data: missing {', '.join(missing)} (how worlds are drawn and spoken)")
    ph.write(pkg, str(d / "philosophy"))
    if ph.package_hash(ph.load(str(d / "philosophy"))) != r["hash"]:
        raise ValueError("the written philosophy package does not round-trip to its hash")
    split = d / "split"
    vocab = set(ph.vocabulary(pkg)) if hasattr(ph, "vocabulary") else set(pkg.get("vocabulary") or {})
    system = pt._system(pkg)
    lang_train = cp.examples(language_rows, seed, exclude=vocab, system=system)
    seen = {x["messages"][-2]["content"] for x in lang_train}
    lang_test = [x for x in cp.examples(heldout * 3, seed + 1, exclude=vocab, system=system) if x["messages"][-2]["content"] not in seen][:heldout]
    from clingo_object import philosophy_recipe as pr
    recipe = None
    if pr.supports(pkg):  # 0.70.1: the measured recipe — numbered reading, statement line, solver-checked traces (FINETUNING_PAPER)
        phil_train, recipe = pr.rows(pkg, philosophy_rows, seed)
        train_facts = {x["meta"]["facts"] for x in phil_train}
        phil_test, _ = pr.rows(pkg, heldout, seed + 1, test=True, avoid=train_facts)
        ev = pr.eval_items(pkg, train_facts, lang_test, seed=seed + 100)
    else:
        phil_train = pt.sft_rows(pkg, philosophy_rows, seed)
        train_facts = {x["meta"]["facts"] for x in phil_train}
        phil_test = [x for x in pt.sft_rows(pkg, heldout * 2, seed + 1, test=True) if x["meta"]["facts"] not in train_facts][:heldout]
        ev = pt.eval_items(pkg, train_facts, lang_test, seed=seed + 100)
    # 0.67.0: no world of the evaluation in training — eval_items drops judge items seen in training, but the package's fixed worlds
    # can be drawn at random too (2 of 16 in a kollektiv kit; runs 5–7 had 73 and 12 such rows). Those training rows go, counted.
    eval_facts = {i["meta"]["facts"] for i in ev["items"] if (i.get("meta") or {}).get("facts")}
    dropped_for_eval = sum(x["meta"]["facts"] in eval_facts for x in phil_train)
    phil_train = [x for x in phil_train if x["meta"]["facts"] not in eval_facts]
    # 0.70.9: language replay — translation rows (never a language test prompt, never the package's vocabulary) mixed into the stage
    held_lang = {x["messages"][-2]["content"] for x in lang_test}
    n_replay = round(len(phil_train) * LANGUAGE_REPLAY_SHARE / (1 - LANGUAGE_REPLAY_SHARE)) if LANGUAGE_REPLAY_SHARE else 0
    replay = [dict(x, meta={**(x.get("meta") or {}), "replay": "language"})
              for x in cp.examples(n_replay * 2, seed + 7, exclude=vocab, system=system) if x["messages"][-2]["content"] not in held_lang][:n_replay]
    phil_train = phil_train + replay
    random.Random(seed + 8).shuffle(phil_train)
    (d / "eval").mkdir(mode=0o700, exist_ok=True)
    out = {"name": pkg["name"], "version": pkg["version"], "hash": r["hash"], "seed": seed, "order": ["language", "philosophy", "grpo"],
           "prose_in_training": False, "seed_code_without_comments": True,
           "language": {"train": len(lang_train), "test": len(lang_test), "excluded_predicates": len(vocab),
                        "train_sha256": _rows(split / "language.train.jsonl", lang_train), "test_sha256": _rows(split / "language.test.jsonl", lang_test)},
           "philosophy": {"train": len(phil_train), "test": len(phil_test), "dropped_as_evaluation_worlds": dropped_for_eval,
                          "language_replay": len(replay), "language_replay_share": LANGUAGE_REPLAY_SHARE,
                          "tasks": dict(sorted(Counter((x.get("meta") or {}).get("task", "?") for x in phil_train).items())),
                          "seed_shown": sum(bool(x["meta"].get("seed_shown")) for x in phil_train),
                          "format": pr.FORMAT if recipe else "verdict-v1", "recipe": recipe,
                          "train_sha256": _rows(split / "philosophy.train.jsonl", phil_train),
                          "test_sha256": _rows(split / "philosophy.test.jsonl", phil_test)},
           "eval": {"items": dict(sorted(Counter(i["set"] for i in ev["items"]).items())), "dropped": ev["dropped"],
                    "sha256": _rows(d / "eval" / "philosophy.jsonl", ev["items"])}}
    pool = pt.grpo_pool(pkg, prompts, seed)
    out.update(prompts=len(pool["rows"]), labels=pool["labels"], counterfactual_pairs=pool["pairs"], short_of_balance=pool["short_of_balance"],
               reward_version=pool["reward_version"], grpo_train_sha256=_rows(split / "grpo.train.jsonl", pool["rows"]))
    _write(d / "phil_answers.py", PHIL_ANSWERS_PY, 0o700)
    _write(d / "phil_score.py", PHIL_SCORE_PY, 0o700)
    _write(d / "phil_roundtrip.py", PHIL_ROUNDTRIP_PY, 0o700)
    return out


def _training_files(d: Path) -> Path:
    """What every kit needs to train: train.py, the training runtime, pinned requirements and the bundled clingo-object (the seed's
    language and solver code for the reward and the scorers). One definition for the knowledge kit and the philosophy kit."""
    _write(d / "train.py", TRAIN_PY, 0o700)
    _write(d / "training_runtime.py", Path(__file__).with_name("training_runtime.py").read_text(encoding="utf-8"))
    _write(d / "requirements-train.txt", "transformers==5.23.0\ntrl==1.18.0\npeft==0.21.3\ndatasets==5.2.0\naccelerate==1.15.0\n")
    import clingo_object
    from clingo_object import notation
    core = d / "clingo_object"
    core.mkdir(mode=0o700, exist_ok=True)
    for source in sorted(Path(clingo_object.__file__).resolve().parent.glob("*.py")):
        _write(core / source.name, source.read_text(encoding="utf-8"))
    _write(d / "SOURCE-NOTICE.txt", f"Bundled clingo-object {clingo_object.__version__}; source: https://github.com/imoes/vi-mcp\n"
           "SPDX-License-Identifier: AGPL-3.0-or-later\nLicense: https://github.com/imoes/vi-mcp/blob/main/LICENSE\n")
    with (d / "requirements-train.txt").open("a", encoding="utf-8") as f:
        f.write(f"clingo>={notation.CLINGO_MIN}\n")
    return core


#: 0.70.1: philosophy kits built over MCP live on the server under <data directory>/kits; at most this many, then refused with the reason
PHILOSOPHY_KITS_MAX = 10
#: the most seed-stage rows one philosophy kit may ask for (a kit of 3,000 rows is about 40 MB)
PHILOSOPHY_ROWS_MAX = 20000


def kits_dir() -> Path:
    fp = g.fpath_active
    return (Path(fp).parent if fp and not str(fp).startswith("postgres") else Path("/var/lib/vi-mcp")) / "kits"


def philosophy_kit(directory: str, name: str, base_model: str | None = None, seed: int = 11,
                   philosophy_rows: int = PHILOSOPHY_ROWS, language_rows: int = LANGUAGE_ROWS, prompts: int = PHILOSOPHY_PROMPTS) -> dict:
    """0.70.1: a kit for the seed path ONLY — language, philosophy and GRPO stages with their evaluation, built from the package and a
    seed. Nothing of the memory is exported (no incubator, no dataset), so it may be built over MCP; the knowledge kit stays a person's
    command (vi-mcp finetune kit). Runs nothing: a person runs train.py on a GPU host."""
    base = base_model or _cfg().get("base_model")
    if not base:
        raise ValueError("no base model — give base_model (a Hugging Face id or directory of the model to fine-tune) or config finetune.base_model")
    if not 1 <= int(philosophy_rows) <= PHILOSOPHY_ROWS_MAX:
        raise ValueError(f"rows: 1 to {PHILOSOPHY_ROWS_MAX}")
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    core = _training_files(d)
    (d / "split").mkdir(mode=0o700, exist_ok=True)
    _write(d / "README-FINETUNE.md", GUIDE)
    phil = philosophy_stage(d, name, prompts, seed=seed, language_rows=language_rows, philosophy_rows=philosophy_rows)
    run = {"base_model": base, "kit": g.now(), "vi_mcp": __version__, "handbook": GUIDE_VERSION, "kind": "philosophy-only",
           "memory_exported": False, "philosophy": phil,
           "kit_code_sha256": {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [d / "train.py", d / "training_runtime.py", d / "phil_answers.py", d / "phil_score.py",
                                         d / "phil_roundtrip.py", *sorted(core.glob("*.py"))]}}
    _write(d / "run.json", json.dumps(run, indent=2, ensure_ascii=False))
    return {"directory": str(d), **run}


def philosophy_kit_on_server(name: str, base_model: str | None, seed: int = 11, rows: int = PHILOSOPHY_ROWS) -> tuple[dict, bool]:
    """(report, built now) — the MCP path: the server chooses the directory (a caller never names a path on the server); the same
    package hash, seed, rows and base model give the same kit back instead of building it again; at most PHILOSOPHY_KITS_MAX kits."""
    from clingo_object import philosophy as ph
    from . import philosophy as vph
    pkg = vph.resolve(name)
    base = base_model or _cfg().get("base_model")
    if not base:
        raise ValueError("no base model — give base_model (a Hugging Face id) or config finetune.base_model")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")[-60:]
    target = kits_dir() / f"{pkg['name']}-{pkg['version']}-{ph.package_hash(pkg)[:12]}-s{int(seed)}-r{int(rows)}-{slug}"
    if (target / "run.json").exists():
        return {"directory": str(target), **json.loads((target / "run.json").read_text(encoding="utf-8"))}, False
    existing = [p for p in kits_dir().glob("*") if (p / "run.json").exists()] if kits_dir().exists() else []
    if len(existing) >= PHILOSOPHY_KITS_MAX:
        raise ValueError(f"{len(existing)} kits on the server (at most {PHILOSOPHY_KITS_MAX}) — an administrator removes old ones in "
                         f"{kits_dir()} before a new one is built")
    kits_dir().mkdir(parents=True, exist_ok=True)
    return philosophy_kit(str(target), name, base, seed, rows), True


def kit(directory: str, index: str | None = None, base_model: str | None = None, force: bool = False,
        philosophy: str | None = None, philosophy_prompts: int = PHILOSOPHY_PROMPTS, language_rows: int = LANGUAGE_ROWS,
        philosophy_rows: int = PHILOSOPHY_ROWS) -> dict:
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
    core = _training_files(d)
    _write(d / "evaluate.py", EVALUATE_PY, 0o700)
    _write(d / "evaluation_core.py", Path(__file__).with_name("training_eval.py").read_text(encoding="utf-8"))
    cases, seen = [], set()
    for stage in ("logic", "kto"):
        for line in (d / "split" / f"{stage}.test.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            m = row.get("meta") or {}
            case = m.get("program_eval")
            if not case:
                continue
            ident = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()
            if ident not in seen:
                seen.add(ident)
                cases.append({"id": ident, "group": m["group"], **case, "reference": "explicit reference stored with checked execution"})
    _write(d / "program_eval.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in cases))
    _write(d / "program_evaluate.py", PROGRAM_EVALUATE_PY, 0o700)
    _write(d / "heldout_loss.py", HELDOUT_LOSS_PY, 0o700)
    _write(d / "synth_qa.py", SYNTH_QA_PY, 0o700)
    _write(d / "qa_pairs.py", Path(__file__).with_name("qa_pairs.py").read_text(encoding="utf-8"))  # one definition of a good pair
    _write(d / "probe.py", PROBE_PY, 0o700)
    _write(d / "convert.sh", CONVERT_SH, 0o700)
    _write(d / "README-FINETUNE.md", GUIDE)
    run = {"base_model": base, "kit": g.now(), "vi_mcp": __version__, "handbook": GUIDE_VERSION, "index": index,
           "dataset_manifest_sha256": hashlib.sha256((d / "dataset" / "manifest.json").read_bytes()).hexdigest(), "split": split,
           "incubator": manifest.get("inkubator"),
           "philosophy": philosophy_stage(d, philosophy, philosophy_prompts, language_rows=language_rows,
                                          philosophy_rows=philosophy_rows) if philosophy else None,
           "kit_code_sha256": {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [d / "train.py", d / "training_runtime.py", d / "evaluate.py", d / "program_evaluate.py", d / "heldout_loss.py",
                                         d / "synth_qa.py", d / "qa_pairs.py", d / "probe.py",
                                         *[x for x in (d / "phil_answers.py", d / "phil_score.py", d / "phil_roundtrip.py") if x.exists()],
                                         d / "evaluation_core.py", *sorted(core.glob("*.py"))]}}
    _write(d / "run.json", json.dumps(run, indent=2, ensure_ascii=False))
    return {"verzeichnis": str(d), **run, "eval_fragen": len(questions)}


def record(directory: str, who: str = "admin") -> g.MemoryObject:
    """A finished run as a model object with its lineage: dataset manifest, base model, adapter hash, evaluation, incubator state."""
    d = Path(directory)
    if not (d / "run.json").exists():
        raise ValueError(f"{d}: no run.json — not a kit written by vi-mcp finetune kit")
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    adapters = {}
    for stage in ("sft", "agentic", "logic", "kto", "dpo", "language", "philosophy", "grpo"):
        f = d / "out" / stage / "adapter_model.safetensors"
        if f.exists():
            adapters[stage] = hashlib.sha256(f.read_bytes()).hexdigest()
    ep = d / "program_eval_result.json" if (d / "program_eval_result.json").exists() else d / "eval.json"
    ev = json.loads(ep.read_text(encoding="utf-8")) if ep.exists() else None
    if not adapters:
        raise ValueError(f"{d}: no trained adapter under out/ — run train.py first")
    evaluation_path = d / "program_eval.jsonl" if ev and ev.get("evaluation_kind") == "program" else d / "split" / "test.jsonl"
    evaluation_hash = hashlib.sha256(evaluation_path.read_bytes()).hexdigest()
    better = bool(ev and ev.get("metric") == "verified_task_success" and ev.get("evaluation_set_sha256") == evaluation_hash
                  and ev.get("n", 0) > 0 and ev.get("decision") is True)
    verdict = ("not evaluated — run evaluate.py" if ev is None else
               f"fine-tuned {ev['tuned']} vs base {ev['base']} on {ev['n']} held-out questions ({ev['better']} better, {ev['worse']} worse)")
    # 0.65.0: the knowledge probe (probe.py) — did training teach the trained knowledge? Recorded and named; it is not the adoption gate:
    # a model that learned its facts can still answer real questions no better (runs 2 and 3, 14.11.2026).
    pp = d / "probe" / "probe_eval.json"
    probe = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None
    if probe is not None:
        probe_ok = probe.get("probe_sha256") == (hashlib.sha256((d / "split" / "probe.jsonl").read_bytes()).hexdigest()
                                                 if (d / "split" / "probe.jsonl").exists() else None)
        t, b = probe["grades"]["tuned"], probe["grades"]["base"]
        verdict += (f"; knowledge probe ({probe['n']} questions about trained objects): tuned {t['correct']} correct / {t['partial']} partial,"
                    f" base {b['correct']} / {b['partial']}, strict p {probe['strict']['p_one_sided']:.4f}"
                    + ("" if probe_ok else " — NOT for this kit's probe file"))
    oid = g.keyed_id("model", f"finetune:{run['kit'][:19].replace(':', '').replace('-', '')}")
    data = {**run, "adapter_sha256": adapters, "bewertung": ev, "wissensprobe": probe, "urteil": verdict, "erfasst": g.now()}
    text = f"Fine-tuned model on {run['base_model']} ({', '.join(adapters)}): {verdict}"
    o = g.load(oid)
    if o is None:
        return g.new_object("model", text, ["model:finetune"], data, importance=2, who=who, oid=oid, mode="active" if better else "test",
                            reason="fine-tuning run recorded", instance=g.SERVER_INSTANCE, index=run.get("index"))
    o.text, o.data, o.mode = text, data, "active" if better else "test"
    o.change(who, "fine-tuning run updated", verdict)
    return g.save(o)


def main(argv: list[str]) -> int:
    """vi-mcp finetune guide | skill [--base M] [--file] | plan [--index X] [--base M] | kit DIR [--index X] [--base M] [--force] [--philosophy NAME] | record DIR"""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp finetune", description="fine-tune an AI with what this VI learned (vi-mcp runs no training)")
    u = a.add_subparsers(dest="cmd", required=True)
    u.add_parser("guide", help="the handbook: what fine-tuning is, programs, hardware, llama.cpp, measuring")
    sk = u.add_parser("skill", help="the step-by-step runbook to fine-tune any open model (also for small models)")
    sk.add_argument("--base", help="fill in the base model")
    sk.add_argument("--file", action="store_true", help="with the header of a skill file (SKILL.md)")
    p = u.add_parser("plan", help="readiness and the steps for this server")
    k = u.add_parser("kit", help="write the training data, test split and scripts into a directory")
    r = u.add_parser("record", help="record a finished run as a model object with its lineage")
    ek = u.add_parser("embed-kit", help="write the embedding fine-tuning kit: real pairs (evaluation), confirmed negatives, scripts")
    ek.add_argument("directory")
    ek.add_argument("--days", type=float, default=60)
    s = u.add_parser("split", help="redo the kit's shared split after synth_qa.py wrote dataset/qa_synth.jsonl (needs no database)")
    s.add_argument("directory")
    for x in (p, k):
        x.add_argument("--index")
        x.add_argument("--base")
    k.add_argument("directory")
    k.add_argument("--force", action="store_true", help="also for a VI still in the incubator (the datasheet names the open criteria)")
    k.add_argument("--philosophy", help="also write GRPO prompts for this philosophy (built-in, installed in this VI, or a package directory): train.py --stage grpo")
    k.add_argument("--philosophy-prompts", type=int, default=PHILOSOPHY_PROMPTS, help="how many GRPO prompts (default %(default)s)")
    k.add_argument("--language-rows", type=int, default=LANGUAGE_ROWS, help="rows of the clingo-object language stage (default %(default)s)")
    k.add_argument("--philosophy-rows", type=int, default=PHILOSOPHY_ROWS, help="rows of the seed SFT stage (default %(default)s)")
    r.add_argument("directory")
    o = a.parse_args(argv)
    if o.cmd == "guide":
        print(GUIDE)
        return 0
    if o.cmd == "skill":
        from . import finetune_skill
        print((finetune_skill.SKILL_FILE_HEAD if o.file else "") + finetune_skill.skill(o.base), end="")
        return 0
    if o.cmd == "split":
        try:
            print(json.dumps(resplit(o.directory), indent=2, ensure_ascii=False))
        except ValueError as e:
            print(f"vi-mcp finetune: {e}")
            return 1
        return 0
    g.open_db(config.load().db)
    try:
        if o.cmd == "plan":
            print("\n".join(plan_lines(plan(o.index, o.base))))
        elif o.cmd == "embed-kit":  # 0.68.0
            from . import finetune_embed
            print(json.dumps(finetune_embed.kit(o.directory, o.days), indent=2, ensure_ascii=False))
        elif o.cmd == "kit":
            print(json.dumps(kit(o.directory, o.index, o.base, o.force, o.philosophy, o.philosophy_prompts, o.language_rows,
                                 o.philosophy_rows), indent=2, ensure_ascii=False))
        else:
            print(record(o.directory).text)
    except ValueError as e:
        print(f"vi-mcp finetune: {e}")
        return 1
    finally:
        g.close_db()
    return 0
