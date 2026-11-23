# PREREG Z11-1, amendment 4: KR\* on the secondary set (exploratory)

Status: FROZEN 23.11.2026 (date -u at commit), by `docs/PREREG_Z11_A4.sha256`, before any KR\* answer to the secondary set
existed. It changes no earlier result. The primary pre-registration ([PREREG_Z11.md](PREREG_Z11.md)), amendment 1 (the secondary
set, [PREREG_Z11_A1.md](PREREG_Z11_A1.md)) and amendment 2 (KR\*, [PREREG_Z11_A2.md](PREREG_Z11_A2.md)) stay as they are.

## Why

Amendment 2 found KR\* (KR with the weight 0.1, tuned with documents in the prompt) level with R on the 60 probe questions
(42 vs 41 correct, 1:0). With n = 60 that is weak evidence that the store adds nothing on top of retrieval. The 297-question
secondary set (amendment 1) has R and KR answers already. This amendment adds the KR\* answers.

## What runs

- **Arm.** KR\*, exactly as in amendment 2: `scripts/z11/z11.py answer --arm KRs`. The parameters come from
  `frozen_params_A2.json` (sha256 7a36e183…, weight 0.1, k 32, temperature 476.7373046875, BM25 top 3). The store is
  `store_qa` at revision 2558, float32, with greedy decoding and the 2,048-token budget.
- **Questions.** `secondary_questions.jsonl` (sha256 8436b156…88e37bf5c), all 297, in file order.
- **Hardware.** The CPU workstation of the primary, with 4 threads in a 6 GB memory scope and one heavy process at a time. A free-memory
  gate of at least 8 GB is checked before each step. The other secondary arms ran on a rented host (amendment 1, deviation 3).
- **Cross-host check, before KR\*.** Arm R answers 10 secondary questions on the workstation. They are the first 10 ids in
  order of `sha256("z11-A4:xhost:" + id)`. Their texts are compared with the rented host's R answers
  (`secondary/answers_R.jsonl`, sha256 a04e2c49…).
  - **10 of 10 identical:** the comparison runs as planned.
  - **Fewer than 10:** the comparison still runs, and the report names the host difference as a limit of KR\* vs R and KR\* vs KR.
  - Supporting evidence from Z11-2: all 44 secondary K answers the Z11-1 judges graded correct came out text-identical on the
    workstation.

## Judging

The procedure is that of the secondary set and amendment 2:
- **Packing.** `z11.py judgepack --arms KRs,R,KR --questions secondary_questions.jsonl --refs secondary_refs.jsonl --out
  judge_A4` makes 15 blocks of 20 questions. Each question shows the KR\*, R and KR answers in a seeded order under letters, and
  the key is a separate file.
- **Judges.** Fresh subagents grade each block with the primary's prompt and rubric verbatim. Each judge reads only its block
  file.
- **Opening the key.** The key is opened only after all 297 questions are graded (`z11.py score --out judge_A4`).

## Comparisons (exploratory)

These are exact sign tests on strict correct, **two-sided**, reported with wins:losses and p. They decide no goal criterion.
- KR\* vs R;
- KR\* vs KR.

Descriptive measures:
- correct, partial and wrong per arm, and the graded score;
- budget hits, abstentions and invented hosts;
- the number of KR\* answers text-identical to R;
- a judge check: this pass's R and KR grades against the secondary set's grades of the same answers (agreement on strict
  correct, and the full 3-way agreement).

## Expectation, stated before the run

From amendment 2, KR\* is expected to be about level with R, within a few questions, and far above KR. Results that would
contradict amendment 2's reading:
- KR\* significantly below R (two-sided p < 0.05 with more losses than wins): the store would hurt even at the tuned weight;
- KR\* significantly above R: the store would add something after all.

Either result would be reported as such. No threshold here is a pass or fail criterion.

## Named limits

- KR\* runs on a different host from R and KR. The cross-host check above measures this.
- One model family judges.
- The kNN parameters were tuned on validation rows from the same documents (amendment 1). Those were rows, not these questions.
