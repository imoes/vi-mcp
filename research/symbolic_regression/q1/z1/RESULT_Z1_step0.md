# Z1 step 0 result — sampled reads with an answer vote (MBR-READ) on spent fresh4 (25.11.2026, development probe)

Plan: PLAN_Z1_step0.md, frozen 09:01:28 UTC (commit 8b9158f, PLAN_Z1_step0.sha256) before any sampled GPU read.

**Run:**
- RTX 3070 slot (coordinator), reads 12:00:11–12:27:02 UTC, 198 of 198 questions, exit 0.
- Input hashes checked against expected.sha256.
- samples_step0.jsonl sha256 b3e25adf…44fe.
- Vision server stopped 12:00:11 and restored 12:27:02; probe "12:27:17Z vision chat probe OK: 'OK' stop".
- Analysis: the frozen eval_step0.py (c64c9c61…), 12:28:13–12:28:43 UTC.

## Result by the frozen rule: NO-GO for MBR-READ as step 1; the teacher path is proposed (coverage < 30 %)
| measure | value | threshold |
|---|---|---|
| gain on the 98 PREF-wrong questions | **10** right after the vote | — |
| harm on the 100 PREF-right questions | **1** wrong after the vote | ≤ 3 per 100 → holds |
| extrapolated net per 400 (gain scaled to 98, minus harm rate × 302) | **+6.98** (75.5 → about 77.2 %, an estimate) | ≥ +12 → **fails** |
| coverage: unread stated gold facts present in ≥ 1 sample | **9 of 42 = 21.4 %** | < 30 % → **teacher path** |

**Descriptive** (named in the plan):
- **"Any sample right"** (ceiling of a perfect vote): 23 of 98 wrong questions, and 100 of 100 right ones.
- **Vote margin vs correctness:**
  - unanimous (9 of 9 voters): 87 of 123 right;
  - every answer empty (margin 0): 0 of 29;
  - margins 5–8: 15 of 37.
- **Where the vote changed the answer:** in 17 questions it chose a sample over greedy. That gave 10 gains and 1 harm; by type,
  compositional 6, inference 4, comparison 1.
- **Speed:** 462 batched calls of K = 8, mean 3.47 s, median 2.95 s, max 13.29 s. A greedy single read on the peer's 3060 took
  3.78 s on average. So K = 8 sampled reads cost about one greedy read on this GPU. The GPUs differ, so this is a comparison, not
  a controlled measurement.
- **Loop-guard stops:** 0 of 3,696 reads.

## Reading (interpretation, not a test)
- Sampling plus a clingo answer vote helps, and it helps cleanly: 10 gains to 1 harm on development data, at almost no read cost.
  It is not big enough for Z1. At about +7 per 400, the 80 % goal would need roughly as much again.
- **Sampling rarely produces a fact that neither greedy reader wrote** (21 % of 42). Most of the gain comes from choosing between
  values the samples already disagree on, not from new facts.
  - This agrees with the diagnosis: the missing facts are mostly not in the 0.6B reader's distribution, so they need a stronger
    source.
- **Next, as fixed in the plan:** the teacher path.
  - Before 45 GPU hours of teacher reads, a step-0b probe of the same kind is proposed: a ≤ 9B teacher reads the paragraphs of the
    same 198 questions, and coverage of the 42 unread facts is measured.
  - That needs 462 paragraph reads, minutes on the 3070, and the coordinator's or the user's go.
- MBR-READ stays an option to combine with a better reader. It is not adopted, and nothing is deployed.

## Limits
- fresh4 is spent, so this is development evidence; the extrapolation is an estimate from 198 questions.
- One sampling setting (T 0.7, top_p 0.8, top_k 20), not tuned.
- The base reads were not resampled.
- One seed.
