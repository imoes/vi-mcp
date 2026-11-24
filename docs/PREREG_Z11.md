# PREREG Z11-1: knowledge in a kNN-LM token store vs. knowledge in LoRA weights (run 3)

Status: FROZEN 22.11.2026 (date -u at commit), by `docs/PREREG_Z11.sha256`, before any arm answered a probe question. Every later change is an amendment
with date, reason and what it changes. Times are from `date -u`.

## Question

Goal Z11 (goal catalogue, user decision 22.11.2026) asks for a "virtualised LLM": knowledge and behaviour are held outside the
weights in a store that can be edited and inspected, and generation stays with an LLM. This first test asks: does knowledge
in a kNN-LM token store (Khandelwal et al., arXiv 1911.00172; `vi_mcp/knn_lm.py`) answer new questions about known documents as
well as the same knowledge trained into LoRA weights, and can it be removed without training?

## Material (fixed, hashes recorded at freeze)

- Base model: Qwen/Qwen3-0.6B, revision c1899de289a04d12100db370d81485cdf75e47ca, float32, CPU.
- Knowledge: fine-tuning run 3 of 15.11.2026 (AGENTS.md "Fine-tuning runbook" §7). `split/train.jsonl` holds 2,558 question/answer
  rows about 500 VI documents (median 5 rows per document, minimum 1, maximum 15; all questions synthetic).
- LoRA arm: the run-3 adapter `out/sft/adapter_model.safetensors` (r 64, alpha 128, 4 epochs; sha256 d6a779b4…855f92).
- Probe: the run-3 knowledge probe, 60 never-trained questions about 60 of the 500 trained documents (`probe/catalog.jsonl`),
  with the run-3 references and judgments (base 0 correct / 5 partial / 55 wrong; run 3 7 / 9 / 44; recounted 22.11.2026 11:40).
- Documents: the 500 document texts from the kit's `dataset/documents.jsonl` (1.81 M characters).
- Data stay on our own hosts and, by the user's decision of 22.11.2026 (~12:40 UTC, Z11 only), on RunPod pods created for Z11
  and deleted after use. Nothing goes to the Windows 3060 or another external model service. Claude judges as in run 3.

## Arms

All arms use the run-3 instruction (`kit4/gen_answers.py`) as the system message, thinking off, greedy decoding and a budget of
2,048 new tokens. An answer that reaches the budget is marked `budget`, is never cut silently and is graded at most partial
(run-3 rubric).

| Arm | Model | Knowledge |
|---|---|---|
| B | frozen base | none |
| L | base + run-3 LoRA adapter | in the weights |
| K | frozen base, kNN-LM | token store of the same 2,558 rows the LoRA trained on |
| R | frozen base | BM25 top-k of the 500 documents in the user message |
| KR | frozen base, kNN-LM | store of K plus the documents of R |

- **K store.** One datastore source per training row (`<document id>#<row>`). The key is the state the model has when it
  answers: prompt = the chat template with the same system message and the row's question, continuation = the row's answer plus
  `<|im_end|>`. Keys are `hidden_states[-1]` in float32 (the library's key function). Built by `scripts/z11/z11.py build` with
  the library's `Datastore.replace`. No optimizer runs. Built 22.11.2026 11:47–12:19 UTC on the CPU workstation: 2,558 sources,
  263,273 entries (1024-dim float32 keys), revision 2,558, 1.1 GB on disk, 1,956 s, core `weights_sha256` 18353784…f7b9b.
- **R retrieval.** BM25 (k1 1.5, b 0.75, lower-cased `\w+` tokens) over the 500 document texts. The documents go into the user
  message as `[Document i]` blocks before the question.
- **KR** uses K's frozen (weight, neighbours, temperature) and R's frozen top-k. Nothing is tuned for KR itself.
- **Stored run-3 answers** B3 and L3 (GPU, 15.11.2026) are judged in the same blind pass. They are not an arm. They check
  whether this judge agrees with the run-3 grades (agreement and Cohen's kappa).
- **Exploratory (descriptive only, if time allows): D**, a kNN store of the 500 document texts (prompt = empty, continuation =
  the text, in chunks within the window).

## Tuning (validation only, never the probe)

- **Validation rows (`valsplit`).** For each of the 440 non-probe documents with at least two rows, choose one row whose question
  has word Jaccard < 0.5 to every other question of that document (the probe's own hold-out rule). The choice is seeded (2211).
  The row is excluded from retrieval while it is scored. Its siblings stay in the store, as they do for a probe question.
  Drawn 22.11.2026 11:50 UTC: 374 rows (`val.jsonl`, sha256 31646783…598aecd). The other 66 non-probe documents have one row
  only, or no row far enough from its siblings.
- **kNN grid (`tune`).** Neighbours k ∈ {8, 16, 32, 64, 128}. Temperature = factor × the median squared-L2 distance to the
  nearest neighbour on the validation positions, factor ∈ {0.03, 0.1, 0.3, 1, 3}. Weight ∈ {0.1, …, 0.9}. The criterion is the
  teacher-forced NLL of the held-out reference answers (answer tokens plus `<|im_end|>`). Ties go to the smaller k, then the
  smaller weight.
- **RAG top-k (`tune_rag`).** k ∈ {1, 2, 3}, the smallest validation NLL wins. k = 0 is reported.
- The chosen values are written to `frozen_params.json` and committed before any probe answer exists.
- **kNN result (22.11.2026 12:24–12:33 UTC, 551 s):** 374 rows, 39,561 answer tokens. The median nearest squared-L2 distance is
  476.74. Base NLL 3.960; best cell k 32, temperature 476.74 (factor 1), weight 0.8, NLL 1.333. The neighbouring cells are close
  (k 16: 1.343, k 128: 1.334; factor 0.3: 1.370; factor 3: 1.417), so the choice is not a sharp optimum.
- **RAG result (22.11.2026 12:34–15:40 UTC, `tune_rag.json`):** validation NLL k 0: 3.960, k 1: 0.797, k 2: 0.764, k 3: 0.740.
  The own document was among the retrieved ones for 336 / 349 / 357 of 374 rows. Chosen: k 3. The NLL still falls at the edge of
  the grid fixed in advance; the grid is not extended (a longer prompt also costs time on CPU), and this is a named limit.
- **Frozen parameters** (`frozen_params.json`, written 15:41 UTC, sha256 1242b7bc…b89ede2): k 32, temperature 476.7373046875,
  weight 0.8, rag_k 3. Input hashes: `tune_store_qa.json` a2dcbf57…bd2b921, `tune_rag.json` 4f025077…20477de5, `val.jsonl`
  31646783…598aecd, `probe/catalog.jsonl` 8a0b9f83…b5e54d3f, `split/train.jsonl` 15c580b3…5215cf, adapter d6a779b4…af855f92.

## Outcomes

**Primary:** the number of strictly correct answers per arm on the 60 probe questions, graded blind.

**Judging.**
- The rubric is `rubric_probe.md` with `rubric_probe3.md`, unchanged. Grades: correct, partial, wrong (an abstention counts as
  wrong and is flagged; `budget` is at most partial).
- The judge sees the question, the run-3 reference answer and the reference document. All answers to a question appear together,
  in a seeded random order (seed `z11:<id>`), labelled only by letter. The key stays in a separate file, which is opened only
  after all grades are written.
- The judges are fresh Claude subagents, one per block of 20 questions. They know nothing about the arms or the hypotheses.
  Claude was also the run-3 judge, so the VI documents reach no new service. The probes were written by Qwen3.6-35B, not by the
  judge.

**Hypotheses** (exact one-sided sign test on the discordant pairs for strict correct, α 0.05):
- **H1:** K > B. The token store carries knowledge at all.
- **H2 (the Z11 goal criterion, goal catalogue):** K correct ≥ L correct (point estimate), and the edit test below passes.
  The two-sided exact sign test K vs. L is reported with it.
- **H3:** KR > R. Token memory adds to retrieval in the prompt.
- Reported descriptively: R vs. L, R vs. K, the graded score (correct 1, partial 0.5) of every arm, abstentions, invented
  hosts/IPs flagged by the judge, and budget hits.

**Detectable difference (stated before the run).** With 60 paired questions and a baseline of 7 correct, a one-sided exact sign
test at α 0.05 needs a net lead of about 6–8 questions (8 discordant pairs: 7 wins; 16 discordant pairs: 12 wins). Simulated
power against LoRA at 7/60: 0.53 if an arm is correct on 25 % of the questions, 0.74 at 30 %, 0.89 at 35 %. "K is as good as L"
therefore cannot be shown as equivalence with n = 60. H2 is a point-estimate goal criterion, not an equivalence test, and the
report says so.

**Secondary:**
- Teacher-forced NLL and perplexity of the 60 probe reference answers per arm (`nll`; for K the frozen kNN mixture).
- Latency per answer and per generated token, store entries and bytes, build time (against run 3's 53 min of GPU training).
- Search check (`verify`): the in-memory float32 search against `Datastore.distribution` (float64). Before the freeze: the same
  argmax on every checked query and the largest probability difference recorded. Done 22.11.2026 12:20–12:23 UTC: 40 of 40
  queries (20 seeded rows × (k 8, T 1) and (k 64, T 100)) give the same argmax, and the largest probability difference is 2.2e-5.
  The KV-cache generator produced text identical to `KNNLanguageModel.generate` on 3 of 3 prompts (24 steps, weight 0.5, k 8).

## Edit test (the part LoRA cannot do without training)

1. **Forget.** F = the probe questions on which K is graded correct or partial. Snapshot the store, then forget every source of
   F's documents in one revision (`Datastore.forget`, reason "Z11 edit test") and answer all 60 questions again with K.
   - The edited answers to F are judged in a second blind pass, mixed with the same number of unedited K answers drawn by seed.
   - Passes if at least 80 % of F's edited answers are graded wrong, **and** at least 90 % of the K answers to questions outside
     F are textually identical to before (locality).
2. **Restore.** Answer the F questions from the snapshot taken before step 1. Passes if every answer is textually identical to
   the original K answer.
3. **Weights.** `weights_sha256` of the core is identical before and after.
4. **Replace (exploratory).** For up to 10 questions in F with a single named value in the reference (a number, path, name or
   setting), replace that value in the document's rows with a counterfactual value fixed before generation
   (`Datastore.replace`), and report whether the new answer states the new value.

**LoRA comparison.** The adapter cannot forget a document without new training. Run 3 cost 53 min of GPU training for the
whole set. This is stated, not measured again.

## Decision

- **H1 and H2 hold:** the first step of Z11 is reached. Knowledge for answering lives in an editable store at least as well as in
  the run-3 weights. Next step: scale the store (more documents) and serve it through `knn serve`.
- **H1 holds, H2 fails on the point estimate:** the store carries knowledge but less than training does. Report the gap. If
  KR > L, retrieval plus token memory is the virtualised form to pursue.
- **H1 fails:** the token store at this scale does not carry document knowledge to new questions. The report names the
  measured neighbour distances and NLL as the reason.

## Larger secondary question set (deferred)

Never-trained questions about the other 440 documents would raise n. They are written before any arm answers and get their own
amendment: `docs/PREREG_Z11_A1.md` (297 questions), frozen in the same commit as this file. On 22.11.2026 the user allowed RunPod for all of Z11, VI documents included (decision ~12:40 UTC, Z11 only), so the
generator runs on a rented GPU instead of waiting for our own hosts.

## Limits named in advance

- B and L are regenerated on CPU and may differ from the GPU answers of run 3. The text agreement with B3/L3 is reported.
- The runner decodes with a KV cache and searches in float32. This is checked against the library (`verify`), not assumed.
- One judge family (Claude). Position bias and style leaks are limits. Every judge block shows all arms of a question at once,
  so a recognisable arm style could leak; the order is shuffled per question.
- n = 60 (see the detectable difference above).
