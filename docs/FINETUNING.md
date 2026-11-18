# Fine-tuning a model with a VI's knowledge — from zero

This guide takes a person who has a vi-mcp server and one GPU host from nothing to a measured LoRA adapter. Every number in it was
measured on 14–15.11.2026 (Qwen/Qwen3-0.6B, one AMD Strix Halo gfx1151 GPU, ROCm, fp32) unless it is marked *hypothesis*.
The agent-facing runbook with the same steps is in [AGENTS.md](../AGENTS.md#fine-tuning-runbook-an-agent-can-run-it-end-to-end);
the handbook every VI ships is `vi_finetune(action="guide")`.

**What to expect.** Closed-book fine-tuning puts facts into a model's weights. It does **not** let the model answer questions about
knowledge it never trained on, and a small model learns slowly: run 3 answered 12 % of new questions about its trained documents
fully right (base: 0 %). Measure before you deploy, and read "Limits" at the end.

## 1. Store the data right from the start (the server does it)

Knowledge becomes training-ready on the server after it is learned; nothing has to be prepared by hand later. Until the server has reached an object, its state is `none` and it is exported for synthesis.

| field on the knowledge object | what | written by |
|---|---|---|
| `inhalt`, `quelle`, `text` | the knowledge, complete, with its source | `vi_learn` (the person or agent) |
| `data.klasse.fragen` | 1–3 questions a colleague would type (doc2query) | sleep step 8f / `vi-mcp classify` |
| `data.qa.pairs` | grounded question-answer pairs about this object | sleep step 8i / `vi-mcp classify --pairs` |
| `data.qa.probe` | one more pair, **never trained**: after training it asks whether the model learned this object | same call |
| `data.qa.rejected` | rejected pairs per reason | same call |
| `data.qa.content_sha256` | the text the pairs were made from: changed knowledge makes them stale | same call |
| `data.qa.version` | generator model, prompt hash, schema `qa-v1` | same call |

One definition of a good pair is used everywhere ([`vi_mcp/qa_pairs.py`](../vi_mcp/qa_pairs.py), copied into the kit):
- the question makes sense on its own: it names the system, host or topic, and never says "the document";
- the question is not copied from the beginning of the document;
- at least 80 % of the answer's content words occur in the document (grounded). Function words do not count, and a compound
  token such as `host:dns01.example.org` also grounds its parts (qa-v2; qa-v1 kept 1 of 25 real pairs on short German findings,
  qa-v2 kept 25 pairs on 14 of 20 objects with Qwen3.6-35B, 15.11.2026);
- it is not a duplicate of another question about the same object.

- every number of the answer occurs in the document (a port, a version, a time);
- the question names the document's subject: a word of its title or one of its named tokens (qa-v3).

This check is lexical. A reversed negation ("must not" → "can") still passes. It screens; it does not verify.

Of the kept pairs, one per object becomes its probe. The choice depends only on the object id. Pairs too close to the probe
(word Jaccard ≥ 0.5) are dropped. An object with fewer than two kept pairs gets no probe: one pair is worth more as training.

**Never** is an object's own text used as its question. The first production run did that for 96 % of its rows (20,066 of 20,957).
The model learned to echo and continue Confluence pages, looped in 55 % of its answers and answered no real question better
(blind test, 14.11.2026).

### Turn it on

1. A classify model in `/etc/vi-mcp/config.json`. Sleep only labels and makes pairs with an explicit one:
   ```json
   "classify": {"url": "http://HOST:PORT/v1/chat/completions", "model": "NAME", "per_sleep": 10, "pairs_per_sleep": 5}
   ```
   The url is the complete chat-completions endpoint; a bare `/v1` answers 404. (The kit scripts below take the `/v1` base
   instead.) Any OpenAI-compatible instruction model works. Thinking is switched off and no token cap is set. Each object costs one call
   (about 40 s on a shared server, measured 13.11.2026).
2. Existing knowledge, once: `vi-mcp classify --pairs --limit 25000 --workers 4` on the server. It is resumable: objects with
   current pairs are skipped. A failed call is retried after a day.
3. Check: `vi-mcp classify --pairs --dry-run` counts objects by state (`ok`, `empty`, `error`, `none`, `other_prompt`) and the
   pairs and probes stored. After an edit of knowledge, `vi-mcp classify --pairs --stale` renews pairs of changed objects.

New knowledge gets pairs in the following sleeps, `pairs_per_sleep` objects each time, newest first.

## 2. The kit

On a copy of the database (never the live one):
```sh
# SQLite: the backup API, read-only (the sqlite3 command line tool is often not installed); PostgreSQL: pg_dump
python3 -c 'import sqlite3; s = sqlite3.connect("file:/var/lib/vi-mcp/vi.db?mode=ro", uri=True); s.backup(sqlite3.connect("/srv/ft/vi-copy.db"))'
# (/var/lib/vi-mcp/vi.db stands for the "db" of /etc/vi-mcp/config.json)
mkdir -p /srv/ft/eval && cp /var/lib/vi-mcp/eval/recall.json /srv/ft/eval/   # the fixed question set stays held out
echo '{"db": "/srv/ft/vi-copy.db"}' > /srv/ft/config.json                       # a scratch config pointing at the copy
VI_MCP_CONFIG=/srv/ft/config.json vi-mcp finetune kit /srv/ft/kit --base Qwen/Qwen3-0.6B --force
```
`--force` is needed while the VI is still in the incubator. The kit contains:

| file | what |
|---|---|
| `dataset/qa.jsonl` | doc2query rows and the stored pairs (`meta.question_source`: `doc2query` or `synthetic`) |
| `dataset/probe.jsonl` | the stored probes |
| `dataset/documents.jsonl` | knowledge without usable stored pairs (none yet, stale, failed) |
| `dataset/DATASHEET.md`, `manifest.json` | what is in it, what was left out and why, `quality.stored_pairs` |
| `split/train.jsonl`, `split/test.jsonl`, `split/<stage>.*` | one split by object for all stages |
| `split/probe.jsonl` | probes of objects whose rows are on the **train** side: the knowledge probe |
| `synth_qa.py`, `qa_pairs.py` | pairs for `documents.jsonl`, with the server's definition |
| `train.py`, `training_runtime.py` | TRL + PEFT LoRA training (`--stage sft`, `--lora-rank`, `--fp32`, `--preflight`, `--tokenizer-only`) |
| `probe.py` | the knowledge probe: answers, judgment, unblinding, test |
| `heldout_loss.py`, `evaluate.py`, `program_evaluate.py`, `convert.sh` | loss, generalization test, program test, GGUF adapter |
| `run.json` | lineage: base model, dataset hash, split, code hashes |

If the server has not stored pairs for everything yet, fill in the rest on any host that reaches an instruction model:
```sh
python synth_qa.py --url http://HOST:PORT/v1 --model NAME --limit 500 --workers 4   # resumable, synth_report.json
vi-mcp finetune split /srv/ft/kit                                                  # pairs and probes join the split
```
Measured: with Qwen3.6-35B-A3B Q4 and 4 workers, 12 documents took 38 s; 14 pairs were kept and 21 rejected. All 23,585
documents would take about 25 h. `--more FILE --pairs 8` asks chosen documents again for further, varied pairs.

Check `run.json` → `split.qa_question_sources` and `split.probe` before training.

## 3. Training environment

Use a container of its own on the GPU host:
- AMD: a `rocm/pytorch` image whose tag lists your GPU arch (gfx1151 from ROCm 7.1).
- NVIDIA: a CUDA PyTorch image.

Install `requirements-train.txt` with a constraints file holding the image's torch versions. Otherwise pip replaces the GPU torch:
```sh
pip freeze | grep -iE "^(torch|torchvision|torchaudio|pytorch-triton-rocm|triton)==" > keep.txt
pip install -c keep.txt -r requirements-train.txt
```
Run it with the GPU devices: AMD `--device /dev/kfd --device /dev/dri --group-add <video> --group-add <render> --security-opt
seccomp=unconfined`, NVIDIA `--gpus all`. Then run three smoke tests:
- `torch.cuda.is_available()` returns True, also on ROCm;
- the device name shows the arch;
- an fp32 matmul agrees with a CPU fp64 reference to about 1e-3.

On unified-memory machines, GPU memory and RAM are one pool: check `free -g`. Stop another model server only with permission and
only for the run, then restart it and probe it with a real request.

## 4. Train

In the kit directory, inside the container:
```sh
python train.py --stage sft --tokenizer-only --fp32      # token audit of every row, no weights: expect rejected {}, valid true
python train.py --stage sft --preflight --fp32           # real trainer, one no-grad loss, 0 optimizer steps
python train.py --stage sft --fp32 --lora-rank 64 --epochs 4
```
`--fp32` is needed on gfx1151, where ROCm issue 9198 lists bf16 bugs.

**The recipe that worked** (run 3, 15.11.2026):
- 500 documents with about 5 varied grounded pairs each;
- 2,558 rows;
- LoRA rank 64 / alpha 128, 4 epochs;
- 53 min.

Speed: about 310 trained tokens/s at batch 1. Run 2 used rank 16, 3 epochs and every row; it learned less (below).

## 4b. A philosophy in the model: language → seed → GRPO

The user decided the order on 15.11.2026: "first teach the AI clingo, then the seed". The seed is baked into the model, and the
solver is the teacher. One kit holds the whole path; there is no hand-made data.

```sh
vi-mcp philosophy kit kollektiv /srv/ft/kit --base Qwen/Qwen3-0.6B   # the seed path only (0.70.1) — nothing of the memory in it
#   or over MCP: vi_philosophy(action="kit", name="kollektiv", base_model="Qwen/Qwen3-0.6B") — the server picks the directory
#   (<data dir>/kits/…), returns it, and gives the same kit back for the same package, seed, rows and base model (at most 10 kits)
#   vi-mcp finetune kit DIR --base B --force --philosophy kollektiv  writes the same seed path next to the memory's knowledge stages
python train.py --stage language --fp32 --lora-rank 64        # the clingo-object language, from the base
python train.py --stage philosophy --fp32                     # the seed, continues out/language
python train.py --stage grpo --fp32                           # the seed as reward, continues out/philosophy
python phil_answers.py --adapter out/grpo --fp32              # base and tuned answers to eval/philosophy.jsonl, resumable
python phil_score.py                                          # eval/philosophy_score.json
python phil_roundtrip.py --judge-url U --judge-model M --control kollektiv_principles_1.1.0.json   # prose sets by round trip
```
Run `--tokenizer-only`, then `--preflight` for each stage first. `--from-adapter` or `--from-base` overrides a stage's parent.

**What the kit writes** with `--philosophy NAME`. A package without training data (generator, wording, pressure) is refused, and the
missing fields are named.

| file | content |
|---|---|
| `split/language.{train,test}.jsonl` | clingo-object in both directions (`clingo_prose`), on rule sets that use no predicate of the package (3,000 rows) |
| `split/philosophy.{train,test}.jsonl` | kollektiv 1.3 (0.70.1, `clingo_object.philosophy_recipe`, format `trace-v1`): judge, formalize, pressure and "which sentences state …?" rows (1,700) — a numbered situation with filler sentences as "unknown", the fact types defined in the system prompt (20 % without), and the answer Facts → Statements → the solver-checked trace (Count, Origins, Totals, Holds, Value check, Duty check; `philosophy_trace`) → the verdict; worlds of 1–10 statements with the short ones at full volume, rare cases drawn up to 4 % of the judged rows. Other packages: the earlier judge, formalize and pressure rows, half of their prompts showing the seed's rules. Test rows use held-out phrasings and pressure; no test world occurs in training |
| `split/grpo.train.jsonl` | GRPO prompts with the seed's verdict (below) |
| `eval/philosophy.jsonl` | judge on training phrasings and on held-out phrasings, held-out pressure, held-out formalize, the package worlds, explain the seed (whole and per block), recite, the held-out language; judge items whose world occurs in training are dropped and counted |
| `phil_answers.py`, `phil_score.py` | answers and the score: world_exact, every answer value, duties_exact, invented certainty, facts_exact for formalize, budget cuts |
| `phil_roundtrip.py` | the prose sets (explain the seed whole and per block, recite) of base and tuned scored by the round trip: an independent back-translator (`--judge-url/--judge-model`, or a command-line model with `--judge-cmd "codex exec -s read-only --skip-git-repo-check"`, run in a fresh empty directory with stdin closed; preferably another model family) writes clingo-object from each answer with up to 4 repair rounds; per answer the agreement of the rebuilt seed with the seed's answers and duties on the package worlds plus `--random N` worlds, the repair rounds, and whether it ran at all. A control prose (`--control FILE`, or the items' `gold_text` in a 1.1.0 kit) is back-translated alike and reported beside every number. Writes `eval/philosophy_roundtrip.{jsonl,json}` (resumable) and a blind reading aid `eval/philosophy_blind.md` with its key in `eval/philosophy_blind_key.json`. Also reads a run-6 kit (`eval/eval.jsonl`, `eval/answers.jsonl`, `--package kollektiv`) |
| `philosophy/` | the checked package; its hash is in `run.json` → `philosophy` with the counts and file hashes |

**No principle prose in training.** The user decided that only the clingo seed is stored and that prose is a translation of it. So:
- no principle text and no comment line of the seed enters any training row (a test asserts this);
- the seed is shown as rules only;
- explain_seed and recite are evaluated by the round trip: the prose is translated back to the seed, and the verdicts must match on
  the package worlds. Where a package still carries principle prose, it stands in the evaluation only as a reference.

The stages `language` and `philosophy` are new stages with SFT mechanics. They do not reuse `logic`, because the kit's logic files
are vi_logic tool-use episodes from the VI, and the seed path needs its own adapters and lineage.

### GRPO

**The data (kit option, not a separate kit).** GRPO continues from an adapter of the same kit. A separate kit would split the
lineage (base model, run.json, `record`). `--philosophy NAME` writes the following:
- the checked package to `philosophy/`;
- the prompts to `split/grpo.train.jsonl` (`--philosophy-prompts`, default 1000);
- `run.json` → `philosophy`: the package hash, labels, counterfactual pairs and the hash of the prompt file.

**The pool:**
- Prompts are drawn by the package's generator and labeled with the seed's verdict on the first statement (t, f, b, n or none).
- Prompts are interleaved round-robin by that label, and the dataset is not shuffled. So one generation batch holds every label once
  (`--prompts-per-step`, default = number of labels).
- About 30 % are **counterfactual pairs**, kept adjacent: the package's own counterfactual worlds, and random worlds with one fact
  removed that change the verdict.
- A label the generator rarely draws is reported in `short_of_balance`, not hidden.

**The reward** (`philosophy-reward-v1`, per slot, averaged, in [−1, 1]):

| | reward |
|---|---|
| right answer value with the seed's reasons | +1 |
| right value, reasons differ | +0.5 |
| missing value, or a wrong value that is not firm | −0.5 |
| a firm value (t/f, or a package's `answers.<pred>.firm`) where the seed has a weaker one or none | −1 |
| duties exactly the seed's | +1 |
| duties differ | −0.5 |
| duties differ with an invented permission (`may(...)`) | −1 |
| the explicit abstention "I cannot formalize this situation." | 0 |
| unparseable | −1 |
| cut by the generation budget | −1 (never parsed) |

- There is no length term. Padding an answer changes nothing.
- An answer that always suspends judgement scores far below the seed's verdict: a mean below 0.25 on a pool where the seed's own
  verdict scores 1.0 (tests).
- The reward follows TruthRL (arXiv 2509.25760): a ternary reward cut hallucination from 43.5 % to 19.4 %.
- It also follows FormaRL: a reward that only checks the form is gamed, so this reward compares the content with the solver.

**Guards:**
- **The seed is immutable.** The stage refuses to train when:
  - the kit's package hash differs from `run.json`;
  - a prompt carries another hash;
  - the bundled solver gives any stored gold verdict differently now (`seed_check` re-solves every prompt before weights load).
- **Generation budget.** Sampling needs `max_completion_length`. This is a resource bound of local generation, not an API token cap
  (the project rule against `max_tokens` concerns API calls). By default it is twice the longest spoken gold verdict in tokens, at
  least 64; `--max-completion-length` sets it. The report names the budget and its rule. A completion that reaches the budget gets
  −1 and is not masked, so the model learns to finish.
- **Named settings in the report:**
  - `loss_type dapo` (no length bias);
  - `beta 0` (no reference model);
  - `scale_rewards group`;
  - `mask_truncated_completions false`;
  - `shuffle_dataset false`;
  - thinking off.

**Before GRPO**, the model must already speak the verdict format. That is why GRPO continues `out/philosophy` by default. A model
that never saw the format gets −1 for everything, and the group then has no reward variance to learn from.

**Speed of the verdicts.** The seed is translated once per process, and each world is solved once (`philosophy.solve`). Measured
15.11.2026 against the double solve before:
- `messung`: pool of 200 prompts 15.9 → 4.3 s, re-solve 10.9 → 3.1 ms per prompt;
- `kollektiv`: pool 3.3 → 1.0 s, re-solve 6.8 → 2.0 ms per prompt.
The gold verdicts are identical (fingerprints compared).

## 5. Measure: the knowledge probe

```sh
python probe.py answer --adapter out/sft          # base and base+adapter, greedy, thinking off; per question, resumable
python probe.py judge --url http://HOST:PORT/v1 --model JUDGE   # or a person writes probe/judgments.jsonl
python probe.py summarize                         # unblinds, tests, writes probe/probe_eval.json
```
- `answer` writes `probe/answers_blind.jsonl` with the sides A/B in a seeded random order per question, and `probe/ab_key.jsonl`
  apart. You can judge while it is still running.
- An answer that reaches the generation budget (2,048 new tokens, against the loops of a small model) is marked `budget`. It
  counts at most as partial.
- The grades are correct, partial and wrong. "I don't know" is wrong.
- The gate is a one-sided sign-flip test over object groups, p < 0.05 with a positive difference, strict (correct only) and
  lenient (correct or partial).
- `summarize` names the judge. If the judge is the model that wrote the probes, it warns of self-preference: let a person or
  another model family check a sample.

Measured on 60 probe questions about trained documents (blind, judged before the key was opened):

| | correct | partial | wrong |
|---|---|---|---|
| base Qwen3-0.6B | 0 | 5 | 55 |
| run 2 (rank 16, 3 epochs, all rows) | 4 | 3 | 53 |
| run 3 (rank 64, 4 epochs, 500 documents × ~5 pairs) | 7 | 9 | 44 |

For run 3 against base, strict p = 0.008 and lenient p = 0.006.

The generalization test (`evaluate.py`, questions about **held-out** documents) showed no gain for run 2 (p ≈ 0.1). That is
expected: closed-book fine-tuning cannot know what it never saw. `heldout_loss.py` shows absorption (NLL 2.27 → 1.29 in run 1)
but is never the gate: run 1 had that loss drop and was useless.

## 6. Record, convert, deploy

- `vi-mcp finetune record /srv/ft/kit` stores the run as a model object with its lineage. It records the probe result too; the probe
  is evidence, not the adoption gate.
- `./convert.sh` turns the adapter into GGUF for `llama-server --lora`. Alternatively, PEFT `merge_and_unload()`, then GGUF.
- Deploy a tuned model only with the owner's approval.

## Limits (measured)

- 12 % of probe answers fully right is low.
- The tuned model never abstains: it invents hosts and IP addresses. Gekhman et al. measured this effect of training on new
  knowledge (arXiv 2405.05904).
- The probe questions come from the same generator as the training pairs, and the tuned model's answers are recognizable by their
  "Source:" line, so the blinding is weak.

## Next improvements — research 15.11.2026

These are hypotheses to measure with the probe above, one change at a time. Each figure was measured by its source on its own task;
none on a 0.6B model unless stated. Sources marked † were found by a research agent and not checked by us.

1. **Retrieval plus a fine-tuned reader instead of closed book.**
   - RAFT trains the model on a question with the right document and distractors, and reaches 35.3 on HotpotQA against 6.4 for
     fine-tuning alone (LLaMA2-7B, https://arxiv.org/abs/2403.10131).
   - Retrieval beats fine-tuning above all for rare facts (https://arxiv.org/abs/2403.01432). Internal hosts and IPs are rare facts.
   - A VI already is the retriever (`vi_recall`, `agentic.jsonl`).
   - *Hypothesis:* the largest gain for a 0.6B model.
2. **Abstention.**
   - A model's hallucinations mimic how its unfamiliar training examples were supervised (https://arxiv.org/abs/2403.05612).
   - Train "I don't know" on probe-style questions the tuned model still misses, and on questions about hosts that do not exist.
   - R-Tuning gains little at 3B (https://aclanthology.org/2024.naacl-long.394.pdf); SEAT reports better abstention without losing
     the new knowledge (https://arxiv.org/abs/2506.14387).
3. **More exposures per fact.**
   - About 1,000 exposures per fact are needed to reach 2 bits per parameter (https://arxiv.org/abs/2404.05405). Run 3 gave about
     20 (5 pairs × 4 epochs).
   - Active Reading, where the model writes its own study material per document, reached 66 % vs 48 % for synthetic QA on
     SimpleWikiQA (Llama-3.1-8B, https://arxiv.org/abs/2508.09494).
4. **QA first, then documents** (pre-instruction tuning): 48.1 vs 30.3 EM on Wiki2023 (Llama-2-7B, https://arxiv.org/abs/2402.12847).
5. **Short canonical answers.** A 2026 preprint reports 57.7 % → 85.7 % closed-book accuracy from 1–6-word answers and dropping
   trivia (https://arxiv.org/abs/2607.21861 †, one author, 15 documents).
6. **Rank and forgetting.** Higher LoRA rank learned more paraphrased facts but kept less out-of-domain ability on Qwen3 models
   (https://aclanthology.org/2026.findings-emnlp.918.pdf †). *Hypothesis:* measure general ability next to the probe before
   adopting rank 64.
7. **Cleaner probes.**
   - String decontamination misses rephrased test items (https://arxiv.org/abs/2311.04850).
   - Let another model family write the probes, and add a set of questions written by people.
   - LLM judges agree with people over 80 % of the time but prefer their own style (https://arxiv.org/abs/2306.05685).

## Storing knowledge for training and finding — the target (research 15.11.2026)

At about 25,000 objects and 200,000 derived rows, big-data tooling (Spark, Delta Lake, Iceberg, lakeFS) solves problems this memory
does not have (multi-writer, terabytes). That is a *hypothesis*, but the tools' own scope says the same. The gains come from
how each piece is prepared, not from where it is stored. Ranked; figures measured by each source on its own task, not on this
memory.

1. **Context per chunk.** Long pages (up to 200 KB) lose their subject when chunked. A 50–100-token header written from the whole
   document, indexed in both the embedding and the full text, lowered the top-20 retrieval failure rate by 49 %, and by 67 % with
   reranking (https://www.anthropic.com/news/contextual-retrieval). The VI already does hybrid search with a reranker, so this fits.
2. **Chunk along the structure** (headings, tables, code blocks), about 200–400 tokens, no overlap.
   - 200-token recursive chunks reached recall 88.1, and semantic chunking was lowest (https://www.trychroma.com/research/evaluating-chunking).
   - Element-based chunks reached 53.2 % vs 48.2 % answer accuracy on FinanceBench (https://arxiv.org/abs/2402.05131).
3. **Derived data in tables of its own.** `chunk` and `qa` tables carry provenance columns; today the pairs live in `objekt.daten`
   as JSON. Tables allow joins, filters, stale detection in SQL and export (engineering judgement, no study).
4. **A frozen snapshot per training run.** Parquet or JSONL with a manifest: hashes, row counts, database time, generator versions,
   and a dataset card or Croissant JSON-LD. Its hash is recorded next to the adapter. In an audit of 1,800 public datasets, more
   than 70 % lacked a licence (https://arxiv.org/abs/2310.16787).
5. **Near-duplicates.** Find them with MinHash, keep one object per cluster and link the others with a `dup_of` edge; never delete
   silently. Deduplicated training data made models emit memorised text 10× less often (https://arxiv.org/abs/2107.06499).
6. **Split by a stable hash of the object, never by row, and check probes against training with more than strings.** More than
   4 % of standard validation sets overlapped their training data (same source); rephrased duplicates escape string checks
   (https://arxiv.org/abs/2311.04850).
7. **RAFT-form rows with unanswerable questions.** Each row is a question, the right chunk and 4 distractors, and an answer quoting
   the right span. Some rows lack the right chunk and get "not in the documents". The reranker's wrong hits are free hard negatives.
   - RAFT: HotpotQA 35.3 vs 4.4 for domain fine-tuning plus RAG (https://arxiv.org/abs/2403.10131).
   - Unanswerable questions dropped the best SQuAD system from 86 to 66 F1 (https://arxiv.org/abs/1806.03822).
8. **Questions per chunk, filtered.** Doc2Query-- reached up to +16 % effectiveness with a 33 % smaller index
   (https://arxiv.org/abs/2301.03266); proposition indexing gave +10.1 Recall@20 (https://arxiv.org/abs/2312.06648).
9. **A quality score per object or pair.** A language model labels a sample, then a linear head on the existing bge-m3 vectors
   scores the rest, like the classification student. FineWeb-Edu: MMLU 33 → 37 (https://arxiv.org/abs/2406.17557). LIMA:
   1,000 curated examples (https://arxiv.org/abs/2305.11206).
10. **Structure at write time, KCS style:** issue in the asker's words, environment, resolution, cause, state
    (https://library.serviceinnovation.org/KCS/KCS_v6/KCS_v6_Practices_Guide/090). No controlled study shows that this alone helps
    RAG or fine-tuning; that is a hypothesis.

GraphRAG wins mainly on global "what are the themes" questions (https://arxiv.org/abs/2404.16130). Most questions here are
how/why/where lookups, and `kante` edges plus controlled `kind:value` hashtags already filter by entity: low priority.

**Target schema** (not built; each step is measured with the probe and the fixed question set before it stays):

| table | fields |
|---|---|
| `objekt` | as today, plus title ≤ 80 characters, 1–3-sentence summary, content hash, state, `dup_of`, quality score; optional KCS fields issue / environment / resolution / cause |
| `chunk` | chunk id, object id, order, heading path, text, context header, token count, character span, embedding, full text, parent content hash, generator, prompt hash |
| `qa` | qa id, object id, oracle chunk ids, question, question type, short answer, answer quoting its span, answerable yes/no/unknown, hard-negative chunk ids, role train/probe/eval, generator, prompt hash, source content hash, verified by/at |
| `snapshot` | id, time, filter, row counts, file hashes, dataset card, the training runs that used it |
| `tag` | as today, with a controlled vocabulary and an alias table |
