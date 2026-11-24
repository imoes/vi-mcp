# PREREG Z11-3 amendment R1: a clean re-measurement of E1 after a defective answer process

Date: 24.11.2026. This file is frozen with the sha256 in `PREREG_Z11_3_R1.sha256` **before any R1 answer exists**. All times are
UTC from `date -u`. It amends [PREREG_Z11_3.md](PREREG_Z11_3.md). Z11-3's own verdict stays on record, unchanged:
- H6 fails on locality;
- forget 31/32, locality 17/33 (score of 03:21:01, `z11_3_SCORE.json` sha256 7f8db16b…).

## Why

Z11-4 ([RESULTS_Z11_4.md](RESULTS_Z11_4.md)) found that Z11-3's two parallel after processes, started together at 00:26:59 on
the fresh store revision 2747, raced on the key cache.
- **The mechanism.** `z11.Memory` wrote the cache file in place. A process opening it a few seconds after another had started
  writing silently computed zero norms for the unwritten entries. This was reproduced: 159,109 / 92,155 / 28,265 zero norms of
  263,273 at a 1 / 2 / 3 s offset.
- **Where the losses were.** All 16 Kp answers counted as not kept, and the one F answer graded not wrong, came from the second
  process (`z11_3_answers_E1_b.jsonl`).
- **Where the preview fails.** An exact preview of E1 agrees with the first process 33/33 and with Z11-2's single-process runs
  104/104. It fails on the second process 14 times on identity.
- **The fix** (commit edfee3a): each builder writes a temporary file and publishes it with `os.replace`. Verified with 8
  processes started 0–3 s apart.

**Decision.** The user decided "ja, mache a und b", relayed by the coordinator session. Here (a) is this re-measurement and (b)
is the audit of earlier runs.
- The relay gives the time as "~09:57 UTC". That time lies after the `date -u` reading taken when the relay was received
  (09:52:37). The decision was therefore received before 09:52:37, and the relayed time is an estimate.
- The coordinator's conditions:
  - a short prereg amendment written before the run;
  - the same rubric and fresh blind judges;
  - H6 re-scored as a named re-measurement;
  - the original verdict kept on record.

## What is re-measured

- **The edit.** E1 is repeated exactly: the same 189 sources (`z11_3_split.json` → `forget_sources`), forgotten on a new
  hardlink copy `store_z3r1` of `store_qa`, with reason "Z11-3 R1" (`rerun3.py forget`).
  - The result must match Z11-3's edit: revision 2747, 2,369 live sources and 244,991 live entries (`same_as_z11_3`).
  - If it does not, the run stops and the mismatch is reported.
- **The after answers.** All 65 Z11-3 questions are answered by K from `store_z3r1` in **one** process, with the fixed code.
  - The second process's 32 questions come first, then the first process's 33 (`z11_3r1_q.jsonl`).
  - The first process's 33 are a control. They are expected to be text-identical to Z11-3's, because that process had a
    correct search (preview 33/33).
- **Fixed as in Z11-3:** greedy decoding, the 2,048-token budget, `frozen_params.json` (k 32, temperature 476.737, weight 0.8),
  MemoryMax 6G, MemorySwapMax 0, 4 threads, a free-memory gate of at least 8 GB and the 3 GiB disk guard.
- **Cleanup.** The copy is deleted once all 65 answers exist, and `df -B1 /home` is logged.
- **Carried over from Z11-3, measured there and untouched by the defect:** restore (32/32 text-identical, answered from the
  unedited `store_qa` in one process) and the weights hash (equal).

## Judging

- **Grade carry-over.** An R1 answer that is text-identical to its Z11-3 after answer (same text and finish) keeps its Z11-3
  final-pass grade: the same text was already judged blind.
- **Fresh judging.** Every other R1 answer is judged fresh (`rerun3.py judgepack`).
  - Each question shows its before answer and its R1 answer under letters seeded with `"z11-3r1:judge:" + id`. The references
    are Z11-3's, the layout is Z11-3's, and there are 20 questions per block.
  - The key goes to a separate file, `judge_z11_3r1_KEY.jsonl`.
- **The judges.** Fresh general-purpose subagents (Claude Opus), one per block. Each uses Z11-3's final judge prompt and rubric,
  verbatim, with only the block and grade file paths changed.
- **Hashing.** The grade files' sha256 are written to `judge_z11_3r1_grades.sha256` before `score` opens the key.

## H6-R1 (named re-measurement)

The same four criteria as H6, on the R1 after answers of all 65 questions:
- **Forget:** at least 80 % of the 32 F answers are graded wrong.
- **Locality:** at least 90 % of the 33 Kp answers are kept. Kept means text-identical to the before answer, or changed and
  graded correct.
- **Restore:** 100 % (carried over).
- **Weights:** equal (carried over).

H6-R1 holds if all four hold. These are point criteria, with Clopper–Pearson 95 % intervals and the lower-bound reading reported
as in Z11-3.

**Reported, deciding nothing:**
- the result per Z11-3 process half;
- how many first-half answers reproduce Z11-3's;
- agreement with the Z11-4 preview;
- the budget hits;
- the judges' before grades.

**Known before the run, stated so it is not mistaken for a finding:**
- The Z11-4 preview predicts that, of the second half's 16 Kp answers, 14 stay text-identical and 2 change, and that all 16 of
  its F answers change.
- The first half's Z11-3 result was forget 16/16 and locality 17/17.
- If R1 reproduces the first half and the preview holds, locality is 31 to 33 of 33, depending on how the 2 changed Kp answers
  are graded. Forget depends on the 16 second-half F answers, which are judged fresh.

## What R1 does not change

- Z11-3's verdict and its score file stay on record, with the correction note in its results.
- H6-R1 is reported beside it, never in its place.
- Z11-3's other named limits still apply: one writer, one model, one store, greedy decoding only, several questions per document.
