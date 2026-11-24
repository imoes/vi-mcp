# Z11-3 results: a larger forget-by-document test (E1)

Status: **scored 24.11.2026 03:21:01 UTC — H6 fails on locality** (forget 31/32, locality 17/33). Pre-registration: [PREREG_Z11_3.md](PREREG_Z11_3.md), sha256 0ec74f07…, frozen 23.11.2026 13:20:08 UTC

> **Correction, 24.11.2026 09:45 UTC: half of this measurement is invalid.** Z11-4 ([RESULTS_Z11_4.md](RESULTS_Z11_4.md))
> found a defect in the two parallel after processes of 00:26:59.
> - **Cause.** `z11.Memory` wrote its key cache for the fresh store revision 2747 in place. A process that opens the file while
>   another is still writing it silently computes zero norms for the unwritten entries. Z11-4 reproduced this: 159,109 / 92,155 /
>   28,265 zero norms at a 1 / 2 / 3 s offset.
> - **What it explains.** All 16 Kp answers counted as not kept, and the one F answer graded not wrong, came from the second
>   process (`z11_3_answers_E1_b.jsonl`).
>   - On the 33 questions of the first process, an exact preview of E1 (masking the forgotten sources) agrees with the real after
>     answers 33 of 33 times. On the second process's 32 it fails 14 times on identity and 7 times on the divergence point.
>   - Against Z11-2's single-process runs, the preview is exact on 104 of 104 pairs.
> - **The clean half** (first process): forget 16/16 wrong (95 % CI 79.4–100), locality 17/17 kept (95 % CI 80.5–100).
> - **The defective half.** The preview says 14 of its 16 Kp answers would stay text-identical, which would put locality at 31 to
>   33 of 33. That is a preview, not a measured and judged answer. A clean re-run has not been made.
> - **The verdict as scored stays on record:** H6 fails on locality, 17/33. It is a verdict on a defective measurement, not on
>   the store.
>   - The reading below ("on new questions it is not local"), the exploratory loop finding (17/65 budget hits) and hypotheses
>     (a)–(c) all rest on the defective half. They are withdrawn as statements about the store.
>   - The fix is atomic publication of the cache: a temporary file and `os.replace`. Verified with 8 processes started 0–3 s
>     apart.
before any question was written. All times are UTC from `date -u`.

## Diary

- **13:19:54.** First freeze, sha256 a3ceffc0…, commit 7e9ffee.
- **13:20:08. Re-frozen, sha256 0ec74f07…, commit 522e4d4.**
  - **Correction.** The heading of the literature section had stated a reading time of "13:2x–13:4x UTC". That was a guess,
    and it lay in the future. The reading ended before 13:19 UTC.
  - Only that line changed. The old commit was amended before any Z11-3 question or answer existed, so no data saw either
    version.
- **13:20.** The chain was started on the CPU workstation. It waits until 16:00 UTC before the first writer request.
- Writer file check: the served file is 22,853,663,008 bytes. Amendment 1 gives that size for the file run 3 used.
- **16:00:16.** The writer started as a client with 2 workers. The guard probes the server's health every 60 s. Every probe so far
  answered in 0.01 s, and the server's restart count and start time have not changed. At 16:10:25, after 175 of 500 documents in
  pass 1, 86 questions had been kept.
- **17:09:50. The writer ended normally (exit 0); the guard never stopped it.** Every probe answered in 0.01 s, and the restart
  state stayed at count 0 with the start time of 06:50:00 UTC.
  - **Yield:** 494 questions from 3 passes in 4,172 s. Of the 500 documents, 168 have 2 questions, 158 have 1 and 174 have none.
  - **Prompt:** the prompt sha256 is 92cb18b7…, identical to amendment 1. `synth_qa.py` sha256 b78258af….
  - **Rejected candidates:** 2,019 not grounded in the document; 1,311 too close to an existing question (Jaccard ≥ 0.5); 36
    whose document already had 2; 27 that refer to the document instead of its subject.
  - 35 requests failed with a JSON decode error. A failed request does not count as an attempt; its document was asked again in
    the next pass.
  - `z11_3_questions.jsonl` sha256 2ded7bef…, `z11_3_refs.jsonl` sha256 d2455b7f….
  - **Limit, named:** the 174 documents without a question are not in the test, so the set leans towards documents from which
    the writer could draw grounded new questions.
- **17:09:58.** The order put the questions into batches of 200, 200 and 94. The weights hash before was 18353784…. K started
  batch 0 as 1 process: the other project's workers were still running.
- **Forecast before any pool grade (an estimate, not a result).** In Z11-1, K was correct on 8 of 60 probe and 44 of 297
  secondary questions: 52 of 357, 14.6 %.
  - At that rate the 494 questions give about 72 K-correct. The stop rule at 124 would then never trigger, and every batch is
    answered.
  - The split would give about 36 per side. That is above the minimum of 30 but below the target of 60.
  - Expected precision from the table above, at n ≈ 36: the locality interval at the Z11-2 rate would reach well below 90 %.
- **20:33:37.** Batch 0's before answers ended: 200 questions in 12,219 s, 61 s per answer on average. Batch 1 started as 2
  processes; the other project's workers had ended and at least 16 GB were free.
- **20:36:24. Pool judging of batch 0 finished:** 30 correct, 30 partial and 140 wrong, so the stop rule is not met.
  - The judges were 5 fresh subagents, each grading one block of 40 questions with one answer per question.
  - K was correct on 15.0 %, close to the forecast's 14.6 %.
  - Judges noted two calls, both outside the pool decision:
    - A host name that appears only in an answer's source line was flagged as invented.
    - A subnet was flagged as an invented address.
  - Grade hashes are in `judge_z11_3_pool_grades.sha256`.
- **22:41:06.** Batch 1's before answers ended: 200 questions in 7,649 s with 2 processes, about 76 s per answer per process.
  Batch 2 (94 questions) started as 2 processes.
- **22:46:13. Pool judging of batch 1 finished** (blocks 5–9, 5 fresh subagents, the batch-0 prompt with only the block and
  grades paths changed): 25 correct, 36 partial and 139 wrong, so K is correct on 12.5 %.
  - Pool so far: 55 correct, 66 partial and 279 wrong of 400 (13.75 %). The stop rule is not met.
  - **Projection (an estimate):** at 13.75 % the 94 questions of batch 2 add about 13, which gives about 68 K-correct and about 34
    per side. That is above the minimum of 30 and well below the target of 60.
  - **Discrepancy, named:** the judge of block 5 reported 6 correct and 9 partial in its reply. Its grade file holds 5 correct
    and 8 partial. The count uses the file, never a reply.
- **00:23:01 (24.11.).** Batch 2's before answers ended: 94 questions in 6,115 s with 2 processes, about 130 s per answer per
  process. **Correction:** I had estimated the end at about 23:45 UTC; it came 38 minutes later.
- **00:26:19. Pool judging finished** (blocks 10–12, 3 fresh subagents, the same prompt). Batch 2: 10 correct, 21 partial and
  63 wrong.
  - **Whole pool: 65 correct, 87 partial and 342 wrong of 494 (13.2 %).** The stop rule (124) was never met, so every question
    was answered and judged. The forecast before any grade had been about 72.
  - The judge of block 10 named one call: for n 407 the reference lists a team that the document's table does not mark. It
    followed the document and graded the answer correct. The rubric allows that ("matches the reference or the document").
  - The judge of block 11 corrected its own count in its reply; the file is what counts.
  - Grade hashes are in `judge_z11_3_pool_grades.sha256`.
- **00:26:29. Split** (`edit3.py split`, seeded by document): 65 pool questions from 60 documents. **F = 32 questions, Kp = 33**,
  so both sides reach the minimum of 30 and the edit runs. The target of 60 per side is not met.
  - 189 store sources belong to F's documents. Store revision 2558. `z11_3_split.json` sha256 0a99b348….
- **00:26:56. E1 forget** on the hardlink copy `store_z3e1`: revision 2558 → 2747, 189 sources forgotten, 189 tombstones with
  reason "Z11-3 E1", 2,369 live sources and 244,991 live entries left. `store_qa`'s manifest is unchanged.
- **00:26:59.** The after answers started as 2 processes (65 questions, from `store_z3e1`). The restore answers follow them as one
  process, because the coordinator allows at most 2 of my K processes at a time. `df -B1 /home`: 73 %.
- **03:06:17. The after answers ended:** 65 questions in 9,558 s with 2 processes. 17 of the 65 reached the decoding budget of
  2048 tokens (48 stopped), which explains most of the time.
  - The copy `store_z3e1` was deleted at once (`edit3.py cleanup`: answers complete, answers sha256 2ecbd5f4…). `df -B1 /home`:
    74 % before and 73 % after the deletion.
- **03:06:17–03:16:59. Restore:** K answered the 32 F questions from the unedited `store_qa` (revision 2558).
- **03:17:05. Weights after:** 18353784… — identical to the hash before.
- **Compare** (`edit3.py compare`):
  - Restore: **32 of 32** F answers are text-identical to the before answers, so the restore criterion holds.
  - E1: 0 of 32 F answers and 14 of 33 Kp answers are text-identical to the before answers. Locality therefore depends on the
    judging for 19 Kp questions.
- **Judgepack:** 4 blocks (20, 20, 20, 5), the before and E1 answers under seeded letters; key sha256 8f5d3fe1…. Four fresh
  subagents grade them with the Z11-2 final prompt. Only the path, the letters (two answers instead of three) and the file size
  were changed.
- **03:21:01. Score.** All 65 questions were graded. The four grade files were hashed into `judge_z11_3_grades.sha256` before the
  key was opened, and then `edit3.py score` was run. `z11_3_SCORE.json` sha256 7f8db16b….
  - Judges named three calls:
    - n 47 (final) = n 407 (pool): the answer matched the document, which lists fewer teams than the reference, and was graded
      correct. The rubric allows that.
    - The judge of block 2 ran one `grep` on its block file to find section markers, against the instruction "do not run code on
      the data". It says no grade depended on it. **Named deviation.**
    - The judges flagged `invented_host` inconsistently: some flagged host names that appear only in source lines, others did
      not. `invented_host` decides nothing.

## Result

| Criterion (PREREG_Z11_3) | Measured | 95 % CI (Clopper–Pearson) | Threshold | Holds |
|---|---|---|---|---|
| Forget: F graded wrong after E1 | 31/32 = **96.9 %** | 83.8–99.9 | ≥ 80 % | yes (lower bound clears too) |
| Locality: Kp kept | 17/33 = **51.5 %** | 33.5–69.2 | ≥ 90 % | **no** (upper bound below 90 %) |
| Restore: F text-identical from `store_qa` | 32/32 | — | 100 % | yes |
| Weights hash before = after | 18353784… = 18353784… | — | equal | yes |

**H6 fails.** Forgetting by document removes the answers it should remove, but on these new questions it also changes about
half of the answers it should leave alone. Even the upper bound of the locality interval, 69.2 %, lies far below 90 %.

This **does not replicate Z11-2's E1 locality** of 24/26 = 92.3 %. The two 95 % intervals do not overlap: Z11-2 is 74.9–99.1
and Z11-3 is 33.5–69.2. Z11-2's statement "forgetting by document is
clean and local" therefore holds only for its 26 questions. See the correction in CHANGELOG.md.

Reported, deciding nothing (as pre-registered):
- **Lenient locality** (kept if the after grade is not below the before grade of this pass): 17/33, the same.
- **Judge agreement:** the before answers in the final pass were graded 61 correct and 4 partial. In the pool pass all 65 were
  correct, so the two passes agree on 61 of 65 (93.8 %).
  - The 4 differences can inflate forget: a "correct" question that is not really answered looks forgotten. At most 4 of the 31
    count that way, and 27/32 would still clear 80 %.
  - Of the 16 Kp questions not kept, the before answer was graded correct in 15 of them and partial in 1. Judge noise does not
    explain the locality failure.
- **Forget among changed F answers:** 31/32. No F answer is text-identical after E1.
- **F answer not wrong after E1:** one, graded partial. Its nearest store documents after E1 are three documents outside F
  (1,438, 488 and 15 neighbours).
- **Clustering:** each side has 30 documents. The 16 Kp questions not kept come from 15 documents, so the failure does not
  cluster in a few documents.

### Exploratory, after the key was opened (`z11_3_EXPLORE.json`; not pre-registered, decides nothing)

- **Retrieval plays no part.** Arm K retrieves nothing (`retrieved` is empty in every answer). The change comes from the kNN
  store alone.
- **Nearest documents do not predict loss.** Whether an F document was among a Kp answer's nearest documents before E1 is not
  associated with keeping: 2 kept and 1 not kept with, 15 and 15 without.
- **Loops at the budget.** Before E1, all 65 answers stopped normally. After E1, 17 of 65 ran into the 2,048-token budget: 8 on
  F and 9 on Kp. All 9 Kp budget hits are among the 16 not kept: 8 graded wrong and 1 partial. The other 7 not kept stopped
  normally: 6 graded wrong and 1 partial. In Z11-2, none of the 52 E1 answers reached the budget.
- **Changed Kp answers rarely stay correct.** In Z11-2, 10 Kp answers changed and 8 of them were still correct. Here 19 changed
  and 3 of them were still correct.
- **The size of the edit is similar.** Z11-2 forgot 170 sources and left 247,275 live entries. Z11-3 forgot 189 sources and left
  244,991.
- **Hypotheses, not tested.**
  - (a) With weight 0.8, the kNN part decides most tokens, including generic ones. Removing about 7 % of the entries changes the
    neighbours of tokens far from F's subject. Greedy decoding then carries the first changed token through the rest of the
    answer, and sometimes into a loop.
  - (b) The new questions may need longer answers than Z11-2's, giving more steps at which a changed neighbour can tip the
    answer.
  - (c) Z11-2's 26 Kp questions may simply have been a lucky sample. Its interval reached down to 74.9 %.
  - A test would measure the token step of the first divergence and its kNN share. It would repeat E1 at a lower weight, such
    as 0.1 from amendment 2, where K adds little.

### What this does not show

- It does not show that forgetting by document is never local. It shows that, at weight 0.8 on these 33 questions, locality is
  about 50 %, not 90 %.
- **Selection.** The pool kept 65 of 494 questions, about 13 %: those K happened to answer correctly. These may be the answers
  that depend most on a few store neighbours.
- All limits named in the pre-registration still apply:
  - one writer, one model, one store and one host;
  - greedy decoding only;
  - queries written from the forget data;
  - questions per document not independent.
