# Z11-4 results: can the store's provenance be read?

Status: **scored 24.11.2026 09:38:56 UTC — H7 holds (provenance readable by rule and by an AI); H8 fails as
pre-registered, because of a defect it exposed in Z11-3.** Pre-registration: [PREREG_Z11_4.md](PREREG_Z11_4.md) (sha256 793b2871…, commit 42c45db), frozen 24.11.2026 08:58 UTC
before any readout of a test item existed. All times are UTC from `date -u`.

## Diary

- **08:44 (about)** The user approves the read test and names its goal. The user's words: "das war das Ziel: Eine KI kann daran
  nur ablesen, aus welchem Dokument er stammt. Ja mache den Ablese-Test".
- **08:45–08:50** Primary sources read: Khandelwal et al., SILO, Wang et al., Drozdov et al., Xu et al., TRAK and attributed QA.
  Findings are in the prereg.
- **08:49:02** The count of other documents that contain an answer, made before any readout: 9 of 117 items. The file is
  `z11_4_alt_sources.json` (sha256 46a47593…).
- **08:52:35–08:53:07, pilot v1.** Teacher-forced replay of the re-encoded text. One answer did not reproduce from token 39,
  because re-tokenization differs from generation.
- **08:55:39, pilot v2.** Replay step by step, as generation does.
  - Both answers reproduced.
  - The preview was exact on both: "identical" for the unchanged one; for the changed one, divergence at character 110 against a
    real common prefix of 111.
- **08:58:54** Prereg frozen and committed (42c45db). The coordinator reviewed the design beforehand, and its six points are in the
  prereg.
- **08:59:27** The run starts: `chain_z11_4.sh` on the CPU workstation, one process, 6 GB scope, 4 threads.
- **09:16:08** Readout of the 52 Z11-2 items done. All 52 reproduced the generation exactly.
- **09:36:43** Readout of the 65 Z11-3 items done. All 65 reproduced. `rules` (sha256 c59d3fc6…) and `cards` followed:
  - 117 cards in 12 blocks of 97–109 kB;
  - the key is `judge_z11_4_KEY.jsonl` (sha256 ebf3f1d5…);
  - the cards were checked to contain no `erkenntnis:`, `insight:` or `probe` id: 0 matches.
- **09:38** Twelve fresh blind readers start, one per block (general-purpose subagents, Opus). Each may only Read its block and
  Write its grades file.
- **09:38:43** All 12 grade files exist: 117 lines for 117 cards.
- **09:38:55** The grade files are hashed (`judge_z11_4_grades.sha256`, sha256 d3f50d31…).
- **09:38:56** `score`: the key is opened. `z11_4_SCORE.json` has sha256 28e17b18….
- **09:39–09:44, exploratory diagnosis.** All 14 H8 misses lie in one Z11-3 after process.
  - **Race probe** (scratch `race_probe.py`, on a hardlink copy of `store_qa` without its key cache).
    - Two processes started at once: the second crashed with "mmap length is greater than file size".
    - Second process started 1 / 2 / 3 / 5 s later: it silently computed 159,109 / 92,155 / 28,265 / 0 zero norms of 263,273,
      and read a different key tail.
  - **Fix** in `z11.Memory`: write to a temporary file, then `os.replace`. With 8 processes started 0–3 s apart, all got the
    reference norms (sha 8c3bf081…).
  - The copy was removed. `store_qa`'s manifest is unchanged (a541c4c6…).

## Result

### H7: provenance (primary) — holds

| Reader | strict top-1 | 95 % CI | lenient top-1 | strict top-3 | Z11-2 | Z11-3 |
|---|---|---|---|---|---|---|
| M0 nearest document | 111/117 = 94.9 % | 89.2–98.1 | 111 | 111 | 51/52 | 60/65 |
| **M1 credit rule** | **110/117 = 94.0 %** | 88.1–97.6 | 110 | 113 | 51/52 | 59/65 |
| M1s (store-decided tokens) | 110/117 = 94.0 % | 88.1–97.6 | 110 | 114 | 51/52 | 59/65 |
| **AI reader (blind)** | **110/117 = 94.0 %** | 88.1–97.6 | 110 | 116 | 50/52 | 60/65 |

- **Chance.** An answer's neighbour lists hold a median of 184 candidate documents. The mean of 1/candidates is 0.52 %, and the
  global level is 0.2 %.
- **Sign tests** (two-sided, exact): M1 vs. M0 0:1, p 1.0; reader vs. M1 1:1, p 1.0.
- **Decision** (fixed table): M1 ≥ 80 % and reader ≥ 80 % → provenance is readable, by rule and by an AI. The user's goal is
  met for answers the store answered correctly. Both lower bounds also clear 80 % (88.1 %).
- **Lenient truth.** The documents that also contain the answer change nothing: every lenient count equals the strict one.
- Of the 11,693 replayed tokens (the 11,576 generated plus one end token per answer), the store decided 7,240: the base model
  alone would have chosen another token. The median share of an answer's credit held by its own document is 0.46.

**The seven M1 misses (exploratory).** In each, the own document ranks 2nd to 9th and holds 1–18 % of the credit; the top
document holds 4–45 %. None has an alternative document by the 6-gram count.
- One of the seven is the Z11-3 F answer that stayed not wrong after E1 (`probe3:…af4db8288889542218009275:1`): its own document
  ranks 7th with 4 % of the credit. The readout explains why forgetting its document did not remove the answer: the answer was
  carried by other documents. That is the same mechanism Z11-2 observed for its one surviving answer.
- The reader disagreed with M1 on 3 of the 7: it got one right and two still wrong. Its top 3 contains the own document in 116
  of 117.
- How the readers ranked (from their reports): first place to the document carrying the content tokens (marked S); places 2 and
  3 mostly from the shares on the answers' "Source:" lines, which are spread over many documents.

### H8: edit preview (secondary) — fails as pre-registered

| Edit | pairs | identity agrees | first divergence exact (both changed) |
|---|---|---|---|
| Z11-2 E1 | 52 | 52/52 | 36/36 |
| Z11-2 E2 | 52 | 52/52 | 41/42 |
| Z11-3 E1, after process a | 33 | 33/33 | 19/19 |
| Z11-3 E1, after process b | 32 | 18/32 | 11/18 |
| **all (pre-registered)** | 169 | **155/169 = 91.7 %** (86.5–95.4; criterion 95 %) | **107/115 = 93.0 %** (86.8–97.0; criterion 90 %) |

- All 169 pairs were evaluable: every readout reproduced the generation exactly. H8 fails on identity.
- **Every miss is in one process.** All 14 identity misses and 7 of the 8 divergence misses come from Z11-3's second after
  process.
  - Excluding it, the preview agrees on 137 of 137 pairs (95 % CI 97.3–100) and hits the first divergent character on 96 of 97.
  - The one remaining miss is off by two characters (predicted 3, real 5).
- **Diagnosis (exploratory, reproduced).** Z11-3 started both after processes at 00:26:59 on the fresh revision 2747, whose
  key cache did not exist yet.
  - `z11.Memory` wrote the cache in place. A process opening it while the other was still writing computed zero norms for the
    unwritten entries, without an error (diary 09:39–09:44).
  - Z11-2 ran one process per edit. The before answers ran on `store_qa`, whose cache already existed.
  - The defect fits all observations: process b's answers diverge within the first 0–30 characters; 8 of its 14 mispredicted Kp
    answers loop to the budget; their nearest document is the own document in 1 of 14 (process a's Kp answers: 16 of 17).
  - It is not proven that process b had zero norms: its memory is gone. The reproduction shows the mechanism, and the
    preview's 137/137 shows that a correctly working process matches it.
- **Kept prediction on Z11-3 Kp** (pre-registered baselines): majority 17/33, nearest-document rule 16/33, preview rule 16/33.
  The preview rule's 16/33 is computed against outcomes that the defect produced, so it measures nothing about the preview.
- **At the first divergence** (96 exact divergences from correctly working processes): 84 fall on a store-decided token (S). At
  78 of them the forgotten documents held more than half of the token's probability, and at 6 they held none. The divergence
  is where the forgotten entries supplied the token, which is the coordinator's first-divergent-token question. The tokens are
  often an answer's first word ("Das", "Die", "This").

## What this means

- **The read half of weight-space programming works for this store.**
  - From the entries behind an answer, a rule and a blind AI both name the source document 94 % of the time, against 0.5 %
    chance.
  - The store tells, before an edit is made, exactly which answers a forget will change and at which character (137/137,
    96/97). For weights, the same counterfactual has to be estimated with retrained models (TRAK §2.1).
- **Reading the store found a defect in our own measurement.** The preview disagreed with Z11-3, and the disagreement led to a
  race in the key cache. Every answer Z11-3 counted as not kept came from the process the race can have corrupted.
  - On the clean half of Z11-3, forget is 16/16 and locality 17/17. That agrees with Z11-2.
  - A clean re-run of the defective half is needed before H6 can be re-scored. It is not approved yet.
- **What it does not show.**
  - Provenance was read only for correct answers.
  - "Source" means the document whose training rows wrote the entries, not a fact-level attribution.
  - One model, one store, one host. The readers are Claude, the family of the session that built the cards.
  - The defect's exact state inside Z11-3's process b is inferred, not observed.

## Named limits

The prereg's limits stand. In addition:
- **The diagnosis is exploratory.** It came after the score and decides nothing about H7 or H8.
- **Which earlier runs started two store processes at once on a fresh revision** has not been checked for every run. Unaffected:
  - the 117 before answers (reproduced exactly);
  - Z11-2's after answers (one process per edit, preview 104/104).

## Audit of earlier runs (user decision b, 24.11.2026)

**Question.** Which earlier Z11 runs had more than one process opening the same store directory at the same revision while that
revision's key cache did not exist yet? Only such a start can hit the race. A process that finds the cache already complete reads
correct keys.

**Sources:**
- the run logs (`run_times_*.log` in the data directory);
- the key cache's file birth time (`stat`): `store_qa`'s current revision-2558 cache was created 23.11.2026 08:11:51 UTC;
- the session transcript for the deviation-2 check and the rented host;
- the run scripts (`chain_*.sh`, `pod_run.sh`).

| Run (UTC) | Store, revision | Cache at start | Processes on it at once | Race possible | Evidence | Affected |
|---|---|---|---|---|---|---|
| Z11-1 B, L, R arms (22.11) | none (no store) | – | – | no | – | no |
| Z11-1 K and KR until deviation 2 (22.11, before 18:05) | `store_qa` 2558 | no cache code yet: keys in memory | – | no | – | no |
| Deviation-2 check, then KR resumed (22.11, ~18:02) | `store_qa` 2558 | built by the check | the check's K and KR processes | only inside the check | the check regenerated 2 K and 3 KR answers identical to the pre-cache ones (5/5); KR resumed with the cache complete | no |
| Z11-1 edit test (22.11, 20:45–21:46) | `store_qa` 2653, then `store_snap` 2558 | built by the one answering process | 1 (the chain runs forget → answers → restore in turn) | no | chain script | no |
| Secondary set on the rented host (22.11 evening) | `store_qa` 2558, uploaded without `*.f32` | built at 21:53:31 by one process, before the shards started | 3 K + 8 KR shards + `tune_kr` | no: the cache was complete | transcript: "build the key cache on the pod", 21:53:31 UTC; `pod_run.sh` launched afterwards | no |
| A2 `tune_kr` → KR\* (23.11, 08:11–10:13) | `store_qa` 2558 | built 08:11:51 by `tune_kr` (file birth time) | 1 (sequential chain) | no | `run_times_hal.log` | no |
| Z11-2 before, E1, E2, restore (23.11, 10:13–11:15) | `store_qa`; `store_e1` 2728 and `store_e2` 2982 fresh | built by the one answering process | 1 per step | no | `run_times_z11_2.log`; preview 104/104 | no |
| A4 KR\* secondary (23.11, 13:16–16:06) | `store_qa` 2558 | complete | 1 | no | `run_times_a4.log` | no |
| Z11-3 before answers, batches 0–2 (23.11 17:09 – 24.11 00:23) | `store_qa` 2558 | complete (since 08:11:51) | 1, then 2 | no | Z11-4 replayed all 65 pool-correct answers exactly | no |
| **Z11-3 E1 after answers (24.11, 00:26:59–03:06)** | **`store_z3e1` 2747, fresh** | **none** | **2, started together** | **yes** | preview 33/33 for process a, 18/32 for process b | **yes: process b's 32 answers** |
| Z11-3 restore, weights (24.11, 03:06–03:17) | `store_qa` 2558 | complete | 1 | no | – | no |
| Z11-4 readouts (24.11, 08:59–09:36) | `store_qa` 2558 | complete | 1 | no | 117/117 reproduced | no |

**Result.**
- **One run qualifies:** Z11-3's E1 after answers. Its result is already corrected (RESULTS_Z11_3.md) and is being re-measured
  (R1).
- **No other Z11 result is affected.**
  - The deviation-2 check is the only other moment when two processes could have met a missing cache. Its regenerated answers
    were identical to the pre-cache ones, and everything after it found the cache complete.
  - The rented host built its cache in one process before launching the shards.
- **Limit.** The rented host's logs were not kept locally. Its order rests on the session transcript (the cache-build call at
  21:53:31 UTC precedes the launch call). The cross-host checks support it: 9/9 and 10/10 texts identical with the workstation,
  and the 44 correct secondary K answers reproduced on the workstation (Z11-2 host check).
