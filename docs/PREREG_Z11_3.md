# PREREG Z11-3: a larger forget-by-document test (E1) on new questions the store answers correctly

Date: 23.11.2026. This file is frozen with the sha256 in `PREREG_Z11_3.sha256` **before any Z11-3 question is written**. All times
are UTC from `date -u`. Nothing here changes a Z11-1 or Z11-2 result.

## Why

Z11-2 ([RESULTS_Z11_2.md](RESULTS_Z11_2.md)) found that forgetting by document (E1) is clean and local on the questions the
store answers correctly:
- forget 25/26 = 96.2 % (95 % CI 80.4–99.9);
- locality 24/26 = 92.3 % (95 % CI 74.9–99.1).

With 26 questions per side, every interval reaches below its threshold. Z11-1 and Z11-2 can supply no more questions: their pool
of 52 is every question K answered correctly. Z11-3 writes new questions with the same method, so that the same test runs at
about 60 or more questions per side.

**Hypothesis H6.** On new questions about the trained documents that K answers correctly, forgetting the F documents' store
sources on a copy of the store satisfies all four of:
- at least 80 % of F questions are graded wrong;
- at least 90 % of Kp questions are kept;
- restore from the unedited store is text-identical on 100 % of F;
- the weights hash is unchanged.

## Literature read before freezing (23.11.2026, finished before 13:19 UTC)

**How the sources were read.** Each arXiv HTML full text was fetched and searched in full for set sizes, tests, intervals, seeds
and power, with targeted reading passes. No paper was read cover to cover. Where a paper leaves its split sizes out, they were taken
from the authors' Hugging Face dataset; this is said per case.

- **TOFU** (Maini et al., arXiv 2401.06121, "TOFU: A Task of Fictitious Unlearning for LLMs").
  - Forget sets of 2, 10 and 20 authors with 20 QA pairs each. The dataset splits `locuslab/TOFU` are forget01/05/10 = 40/200/400.
  - Forget quality is a KS-test p-value against a retain model (§2.2.3). The text gives no power analysis, seeds or intervals.
  - **What it predicts for us.** Our ~60 per side is above TOFU's smallest forget set. TOFU gives no precedent for a pass/fail
    threshold with an interval.
- **MUSE** (Shi et al., arXiv 2407.06460, "MUSE: Machine Unlearning Six-Way Evaluation for Language Models").
  - Knowledge memorization uses 100 forget and 100 retain QA pairs. These counts come from the `muse-bench` datasets; the paper
    text gives no counts.
  - The paper reports bootstrap 95 % intervals with 9,999 resamples (App. C.1). At n = 100 they are about 13 points wide.
  - **What it predicts for us.** At n = 60, intervals are wider still. Our table below says the same.
- **WMDP** (Li et al., arXiv 2403.03218, "The WMDP Benchmark: Measuring and Reducing Malicious Use With Unlearning").
  - 3,668 multiple-choice questions (bio 1,273, cyber 1,987, chem 408), reported as point accuracies against 25 % chance.
  - A full-text search found no intervals or seeds.
  - The second half of the page was covered only by keyword search, because the fetch tool's summarizer refused it.
  - **What it predicts for us.** Nothing about n ≈ 60.
- **Thaker et al.** (arXiv 2410.02879, "Position: LLM Unlearning Benchmarks are Weak Measures of Progress").
  - The paper shows that small, non-adversarial changes to benchmark queries can contradict reported unlearning claims.
  - A keyword filter scores 1.0 forget and 1.0 retain on TOFU forget 1 % and 5 %, because the test queries are built from the
    forget data (§V-A, Table I).
  - **What it predicts for us.** Our questions are written from the documents. A pass shows that the store no longer supplies
    those answers to those questions. It does **not** show that the knowledge is unreachable by other queries. This is a named
    limit below.
- **Scholten et al.** (arXiv 2410.03523, "A Probabilistic Perspective on Unlearning and Alignment for LLMs").
  - Deterministic point estimates from greedy decoding give inaccurate estimates of leakage.
  - The paper proposes Clopper–Pearson bounds on the leakage probability (§4.1).
  - **What it predicts for us.** It supports our Clopper–Pearson reporting. It also says that greedy-only answers can understate
    leakage under sampling. This is a named limit below.
- **Lynch et al.** (arXiv 2402.16835, "Eight Methods to Evaluate Robust Unlearning in LLMs").
  - Evaluation sets of 1,239 trivia questions and 45–50 completions per domain. A full-text search found no intervals or
    discussion of sample size.
  - **What it predicts for us.** It points to robustness probes (paraphrase, other formats) as the stronger test. Z11-3 does not run
    them.
- **Not read:** papers found by search that apply power analyses to unlearning (e.g. arXiv 2609.12808, 2609.32103). Nothing here
  relies on them.

**Consequence for this design.**
- None of these sources sets a sample-size standard. A point threshold at n ≈ 60 leaves intervals about ±10 points wide.
- So the pass criteria stay **point criteria**, as in Z11-2. That was the coordinator's instruction: thresholds as in Z11-2.
- Whether each Clopper–Pearson lower bound clears its threshold is reported as well, as a stricter reading that decides nothing.
- For a lower bound to clear the threshold at n = 60, 55/60 forgotten are needed for 80 % and 59/60 kept for 90 %.

## Fixed setup (identical to Z11-2)

The following carry over from Z11-2 unchanged:
- the base model and float32 CPU path;
- `scripts/z11/z11.py answer --arm K`, with greedy decoding and the 2,048-token budget;
- `frozen_params.json`: k 32, temperature 476.7373046875, weight 0.8;
- the store `store_qa` at revision 2558 (263,273 entries). Its manifest sha256 is recorded before the first step and must be
  the same after the last one.

The edit (E1 only), the hardlink copy, the restore and the weights check are those of Z11-2 (`scripts/z11/edit3.py`, which
imports Z11-2's interval, hash and text-layout functions).

## Step 1: new questions (before any Z11-3 answer)

`scripts/z11/probe3.py` follows amendment 1's method ([PREREG_Z11_A1.md](PREREG_Z11_A1.md)):
- **Prompt, body and checks.** These are the run-3 kit's own (`kit4/synth_qa.py`, sha256 b78258af…, imported unchanged; prompt
  sha256 92cb18b7…):
  - 3 pairs per request, temperature 0.3, thinking off, no token cap;
  - `check()`: grounded in the document, names its subject, not copied from the document's beginning.
- **Documents.** All 500 trained documents.
- **Jaccard rule.** A candidate is kept only if its question has word Jaccard below 0.5 (`synth_qa.jaccard`) to each of:
  - every trained question of its document;
  - the document's primary probe question and secondary question, if it has them;
  - a new question already kept for the document.
- **Quota.** At most 2 new questions are kept per document. A document is asked at most 3 times, and no more once it has 2. The
  candidates of one answer are taken in their order.
- **Ids and references.** The ids are `probe3:<document>:<1|2>`. The reference is the writer's answer plus the document
  (amendment 1). Questions and references are written to separate files; only the questions reach the answering arm.
- **Writer (deviation from "the workstation only").** The writer is the run-3 generator file, Qwen3.6-35B-A3B UD-Q4_K_XL. It is
  served by the production llama.cpp server on our own GPU host and used as a client only: the run never stops, restarts or
  reconfigures that server.
  - The run starts after 16:00 UTC (after working hours), with at most 2 parallel requests.
  - **Guard.** Before the first request and every 60 s, the server's `/health` is timed and its restart count and start time are
    read. A probe slower than 10 s, a failed probe or a changed restart state stops the run: no new requests are sent.
  - **If the guard stops the run,** the questions written until then are the set, and the report names the stop. The run is not
    restarted the same evening.
  - No document leaves our hosts. The documents come from the same internal memory server.
  - Unlike amendment 1's writer on a rented GPU, this is the exact file run 3 used. Its host details are in the local,
    unpublished notes.

## Step 2: before answers, pool judging, stop rule

1. **Order and batches.** `edit3.py order` sorts every new question by `sha256("z11-3:order:" + id)` and cuts batches of 200.
2. **Before answers.** K answers batch by batch from the unedited store on the CPU workstation, with MemoryMax 6 GB, 4 threads
   and a free-memory gate of at least 8 GB.
   - Once the other project's two workers on that host have ended (checked with pgrep) and at least 16 GB are free, two K
     processes may run at once. Each has the same limits and writes its own file. The answers are byte-for-byte the same either
     way: greedy decoding, the same store, the same weights.
3. **Pool judging, blind and pointwise.** Each answered batch is packed into blocks of 40 questions, one K answer per question
   (`edit3.py poolpack`). The references are the writer's answer plus the document.
   - Fresh subagents grade each block with the Z11-1 judge prompt and rubric, unchanged except for one line: each question has
     one answer.
   - The key, a separate file, maps the letter to the before answer.
4. **Stop rule.**
   - Answering stops after the batch in whose judging the cumulative number of K-correct questions reaches **124**. A batch
     already being answered at that moment is finished and judged too.
   - If the questions run out first, the pool is whatever was reached.
   - The pool is every pool-judged **correct** question among all answered ones. Partial and wrong answers are not in the pool.
5. **Split by document.** The pool's documents are sorted, shuffled with `random.Random("z11-3:split")`, and the first ⌈n/2⌉
   form F; the rest form Kp. The split is written to `z11_3_split.json`, with its sha256, before the edit. Because a document
   can carry 2 questions, the two sides may differ in size.
6. **Minimum.** If either side has fewer than **30** questions, there is no edit run; the report gives the pool and stops there.
   The target is **at least 60 per side**.

## Step 3: edit, after answers, restore

These steps follow Z11-2:
1. The weights hash is taken before the first before answer.
2. **E1.** On a hardlink copy (`store_z3e1`) of `store_qa`, every store source of F's documents is forgotten, with reason
   "Z11-3 E1". The disk guard of at least 3 GiB free applies.
3. **After answers.** K answers every F and Kp question from the copy. The copy is deleted as soon as those answers exist, and
   each deletion is logged with `df -B1 /home`.
4. **Restore.** K answers every F question from the unedited `store_qa`.
5. The weights hash is taken again.

## Step 4: final judging (after all answers exist)

- `edit3.py judgepack` makes blocks of 20 questions. Each question shows its before and E1 answers under seeded letters
  (`random.Random("z11-3:judge:" + id)`), with the key in a separate file. The text is wrapped at 180 characters, as in Z11-2.
- Fresh subagents grade the blocks with the Z11-1 judge prompt and rubric, unchanged except for the layout line used in Z11-2.
- The key is opened only after every block is graded.

## Measures and thresholds (identical to Z11-2)

- **Forget:** the share of F questions graded wrong after E1 must be at least 80 %.
- **Locality:** the share of Kp questions kept must be at least 90 %. A question counts as kept if its after answer is
  text-identical to its before answer, or changed and graded correct.
- **Restore:** 100 % of F restore answers are text-identical to the before answers.
- **Weights:** the hash before equals the hash after.

H6 holds if all four hold. The thresholds are point criteria, as in Z11-2, and are not tests against a null. Clopper–Pearson 95 %
intervals are reported for forget and locality.

Reported but deciding nothing:
- a lenient locality: kept also when the after grade is not below the before grade of the final pass;
- the before answers' grades in the final pass compared with their pool grades (judge agreement);
- the forget share among F answers that are not text-identical;
- the stores' `nearest_documents` of every F answer that is not wrong after E1.

### Expected precision (computed before any data, exact binomial)

| n per side | forget CI if 96.2 % observed | locality CI if 92.3 % observed | P(locality passes) if the true rate is 92.3 % / 95 % / 85 % |
|---|---|---|---|
| 26 (Z11-2) | 80.4–99.9 | 74.9–99.1 | 0.68 / 0.86 / 0.23 |
| 60 | 88.5–99.6 | 81.6–97.2 | 0.82 / 0.97 / 0.19 |
| 80 | 89.4–99.2 | 84.4–97.2 | 0.84 / 0.98 / 0.13 |

At 60 per side, the forget interval lies above 80 % if the Z11-2 rate holds. The locality interval still reaches below 90 % at
the Z11-2 rate: a point criterion with n = 60 cannot separate 92 % from 90 %. That is stated now, so it is not discovered
afterwards.

## Named limits (stated now)

- **Single-system pool judging.** The pool judging shows one answer per question. The judge cannot compare systems, and is also
  not blind to the fact that only one system answered. The final pass re-grades the before answers next to the after answers,
  and the agreement is reported.
- **Selection by the pool.** The pool keeps only questions K answers correctly. A wrong "correct" grade puts a question in the
  pool that the store does not really answer. Such a question is likely to look forgotten, which inflates forget. The final
  pass's before grades measure this.
- **One writer, one model, one store, one host for answers.** The writer also wrote the references.
- **"Base knows" is not measured.** No base-model answers are produced for the new questions. In Z11-2 that class changed no
  share.
- **Queries from the forget data (Thaker et al.).** The questions are written from the documents. A pass says that the store
  stops supplying these answers to these questions, not that no other query can reach the knowledge. No paraphrase or
  format-shifted probes are run.
- **Greedy decoding only (Scholten et al.).** Leakage under sampling is not measured.
- **Several questions per document.** Questions on one document are not independent. The intervals treat them as independent,
  so they are too narrow if the outcome clusters by document. The number of documents per side is reported.
