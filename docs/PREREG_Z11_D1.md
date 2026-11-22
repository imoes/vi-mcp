# PREREG Z11-1, deviation 1: the generator keeps only the last position's logits

Date: 22.11.2026, 17:06–17:10 UTC (`date -u`). It changes no arm, parameter, question, rubric or hypothesis of `docs/PREREG_Z11.md`
or `docs/PREREG_Z11_A1.md`. It changes one line of the runner `scripts/z11/z11.py` after the freeze (commit cb7e2f4).

## What happened

- With the frozen script, arms B, L and K answered all 60 probe questions (15:41–17:05 UTC; budget hits B 1, L 0, K 4).
- Arms R and KR were killed at once by the 6 GB memory limit (exit 137, 17:05:59 and 17:06:36 UTC). Neither wrote an answer.
- Cause: the generator's first step (the prefill) asked the model for the logits of every prompt position. With three documents
  in the prompt that is prompt length × 151,936 × 4 bytes of float32. `tune_rag` already avoided the same problem with
  `logits_to_keep` (the PREREG records the equivalence check there).

## The change

`Generator.run` passes `logits_to_keep=1` to the model. The model then applies its output layer to the last position only. The
generator only ever used `logits[0, -1]`, so the numbers it uses do not change.

## Check (before R and KR ran)

The fixed script answered 4 B and 4 K probe questions again, the first four with finish `stop` in each arm's file. All 8 texts are
identical to the answers of the frozen script (17:07–17:09 UTC; files `check_dev1/` in the data directory). B, L and K are kept
as they are and not regenerated.

## Consequence

R and KR answer the 60 probe questions with the fixed script (started 17:09 UTC). The secondary set (A1) uses the fixed script
for all arms.
