# Z11-1 results: kNN-LM token store vs. LoRA vs. RAG on the run-3 knowledge probe

Status: primary and edit test final (22.11.2026). The secondary set (amendment 1) and amendment 2 are still running. Their sections
are filled in when they are judged.

Pre-registration: [PREREG_Z11.md](PREREG_Z11.md) (frozen 15:41 UTC), amendments [A1](PREREG_Z11_A1.md),
[A2](PREREG_Z11_A2.md) and [A3](PREREG_Z11_A3.md), deviations [D1](PREREG_Z11_D1.md), [D2](PREREG_Z11_D2.md) and
[D3](PREREG_Z11_D3.md). Each has a sha256 file next to it. All times are UTC from `date -u`.

## Question

Can the knowledge that LoRA run 3 put into the weights instead live in an editable token store next to frozen weights (kNN-LM,
Khandelwal et al. 2019, arXiv:1911.00172), so that it can be forgotten and restored without training?

## Setup

- **Base model:** Qwen/Qwen3-0.6B at a pinned revision, float32, greedy decoding, decoding budget 2,048 tokens (as in run 3). The
  same system instruction is used for every arm.
- **Store:** `vi_mcp.knn_lm.Datastore` built from the 2,558 training rows of run 3: 263,273 entries, 1.08 GB of float32 keys, at
  revision 2558.
- **Arms:**
  - B: the base model.
  - L: LoRA run 3, rank 64, 4 epochs.
  - K: kNN-LM.
  - R: BM25 top-3 documents in the prompt.
  - KR: K and R together.
- **Frozen parameters**, chosen on 374 validation rows from documents outside the probe (`frozen_params.json`, sha256 1242b7bc…):
  - k = 32;
  - temperature 476.74 (a factor of 0.1 on the median nearest squared L2 distance);
  - weight 0.8;
  - RAG top-3.
- **Questions:** the 60 never-trained knowledge-probe questions about trained documents (run 3).
- **Judging:** a blind pointwise grade against the reference and the source document: correct, partial or wrong.
  - The letter order is seeded per question, and the key is kept in a separate file.
  - The judges are fresh subagents that read only the block file.
  - Exact sign tests.
- **Judge check:** the base and LoRA answers are identical to run 3's, 60/60 each. The judges agree with the run-3 grades on
  98.3 % (κ 0.88 for B, κ 0.96 for L).

## Primary result (scored 22.11.2026 20:12:55)

| Arm | correct | partial | wrong | graded score (1 / 0.5) |
|---|---|---|---|---|
| B | 0 | 4 | 56 | 2.0 |
| L | 7 | 8 | 45 | 11.0 |
| K | 8 | 6 | 46 | 11.0 |
| R | 41 | 11 | 8 | 46.5 |
| KR | 1 | 17 | 42 | 9.5 |

| Hypothesis | Test (wins:losses, exact sign test) | Verdict |
|---|---|---|
| H1 K > B | 8:0, p = 0.0039 one-sided | **holds** |
| H2 K ≥ L (point estimate) **and** edit test passes | 8 ≥ 7 (5:4, p = 1.0 two-sided); edit test below | **fails** (edit test) |
| H3 KR > R | 0:40 | **fails** |

Descriptive comparisons:
- R > L: 35:1;
- R > K: 35:2;
- L > B: 7:0;
- KR vs. L: 0:6.

### Secondary measures on the probe

| Arm | NLL of the reference answers (2,464 tokens) | perplexity | median s per answer (CPU, 4 threads) | budget hits |
|---|---|---|---|---|
| B | 3.019 | 20.5 | 6.2 | 1 |
| L | 3.172 | 23.9 | 16.8 | 0 |
| K | 2.370 | 10.7 | 19.9 | 4 |
| R | 0.982 | 2.67 | 24.2 | 0 |
| KR | 1.355 | 3.88 | 43.1 | 9 |

- L has a higher NLL than B even though L answers more questions correctly. The references were written by run 3's generator
  model. Hypothesis: the adapter learned its own answer style and is penalised on text worded by another model.
- KR is close to R in NLL but far below R in generated answers (1 vs. 41 correct). NLL measures how likely the model finds a given
  answer, not what it generates.

## Edit test (pre-registered; run 20:45–21:46, blind pass 2 scored 21:48:40)

F is the set of 14 probe questions on which K was graded correct or partial. All 95 store sources of their 14 documents were
forgotten in one batch, which moved the store from revision 2558 to 2653 and left 253,207 entries.

| Part | Criterion | Result | Verdict |
|---|---|---|---|
| Forget | ≥ 80 % of F's edited answers graded wrong | 11/14 = 78.6 % (11 wrong, 2 partial, 1 correct) | **fail** (by one answer) |
| Locality | ≥ 90 % of the answers outside F textually identical | 26/46 = 56.5 % | **fail** |
| Restore | every F answer from the snapshot identical | 14/14 | pass |
| Weights | weights hash identical before and after | identical | pass |

- **Forget.** Two of the three edited answers that were not graded wrong are about facts the base model or general knowledge also
  supplies; in the primary, the base model was partial on one of them. The fact asked by the third occurs in 8 of the 500 training
  documents, and only F's documents were forgotten.
  - Hypothesis: the fact survives through the other documents' entries. A per-source forget is then working as designed, and the
    test should forget by fact, not by document.
- **Controls.** The 14 unedited control answers came back 13 wrong and 1 partial. By construction they are questions K did not get
  right, so they check that the judge is stable. They are not a contrast.
- **Locality, exploratory (amendment 3; scored 21:49:31).** The 20 changed answers outside F were judged blind as before/after
  pairs.
  - Before: 19 wrong, 1 partial. After: 20 wrong.
  - Pair verdicts: 9 same facts, 10 different (but equally wrong) facts, 1 after worse.
  - Outside F the store had no knowledge to lose, so the textual-identity criterion measured drift among invented answers.
    Removing 3.8 % of the entries changes the neighbour sets, and greedy decoding amplifies small shifts in probability.
  - This cannot rescue H2.

## Reading

- **The store carries document knowledge to new questions (H1).** At this scale, it does so about as well as LoRA run 3: 8 vs. 7
  correct, with an equal graded score of 11.0.
- **Retrieval in the prompt is far ahead of both.** R gets 41/60 correct.
- **Mixing the store into a prompt that already has documents hurts.** KR got 1 correct. Its weight of 0.8 was tuned without
  documents. Amendment 2 tests whether this weight is the cause.
- **The forget is not yet clean, and not local in text.** Restore and frozen weights work exactly as designed.
- **What the next design needs:**
  1. Forget by fact, not only by source.
  2. Measure locality on questions the store answers correctly outside the forgotten documents.
  3. Mix in the store only when the retrieval is confident.

## Secondary set (amendment 1) and amendment 2

Pending. They run on a rented CPU host (deviation 3; the cross-host check gave 9/9 identical texts).

## Named limits

- n = 60. H2 is a point estimate, not an equivalence test.
- One model family judges: Claude subagents, the same family as the session that ran the experiment. Each judge saw only the
  blinded block.
- Duplicate question pairs occur in each primary block.
- The decoding budget was reached in 4 K answers and 9 KR answers. Those answers count as at most partial.
