# Z11-3 results: a larger forget-by-document test (E1)

Status: **running**. Pre-registration: [PREREG_Z11_3.md](PREREG_Z11_3.md), sha256 0ec74f07…, frozen 23.11.2026 13:20:08 UTC
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
