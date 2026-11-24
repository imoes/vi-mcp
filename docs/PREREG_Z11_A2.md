# PREREG Z11-1, amendment 2 (exploratory): is KR's failure the untuned mixture weight?

Status: written 22.11.2026 after the primary score (20:12:55 UTC) and before any KR answer text was read. Only the counts of the
primary are known (KR 1 correct, R 41). Everything here is **exploratory**. It changes nothing in the primary result: H3
(KR > R) failed as pre-registered and stays failed.

## Hypothesis

KR uses K's frozen weight 0.8. That weight was tuned on validation prompts **without** documents. With documents in the prompt,
the model can copy the answer from the context. At weight 0.8 the store's distribution, built from prompts without documents,
outweighs that copying.

Prediction if the hypothesis is right: a weight tuned on validation prompts **with** the documents is much smaller than 0.8, and
KR with that weight is close to R.

Observation that would refute it: the tuned weight stays high (≥ 0.5), or KR with the tuned weight stays far below R (fewer than
30 correct of 60).

## Procedure

1. **Tuning (validation only).** Use the same 374 validation rows, the same BM25 top-3 documents in the prompt as `tune_rag`, and
   the same exclusion of the row's own source. Fix k 32 and temperature 476.74 from the primary. Grid: weight ∈ {0, 0.05, 0.1,
   0.2, …, 0.9}. Criterion: teacher-forced NLL of the reference answers. Ties go to the smaller weight. The result is written to
   `frozen_params_A2.json` before any probe answer of this arm exists.
2. **Arm KR\*.** The arm is KR with the tuned weight. If the tuned weight is 0, KR\* is R, and that is reported without a new run.
3. **Judging.** KR\* answers are judged blind in a separate pass. Each question shows the KR\* answer next to the R answer and the
   original KR answer, in seeded order, with the same rubric.
4. **Report.** Counts, the KR\* vs R and KR\* vs KR sign tests (two-sided, exploratory) and the tuned weight with the validation
   NLL curve.

## Hardware

The same CPU workstation as the primary, or a RunPod GPU, with all KR\* steps on one hardware.
