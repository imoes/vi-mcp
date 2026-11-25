# PLAN Z1 step 0 — sampled reads with an answer vote (MBR-READ), development probe on spent fresh4

Frozen by PLAN_Z1_step0.sha256 before any sampled read on a GPU exists. The only sampled read so far is a CPU smoke test: 1 question,
K = 2, deleted from the analysis. Coordinator OK on 25.11.2026 for step 0 only: no training, spent data. Step 1 and the teacher path
need the user's go.

**Why** (DIAGNOSIS_Z1.md, PROPOSAL_Z1.md): no pipeline step over today's two greedy reads reaches +18 questions.
- A perfect gold arbiter gives +0.25 (fresh4) and +2.0 (fresh3).
- 31 of 44 missed gold facts are in neither read.

Sampling could produce new candidates, and a vote on the clingo-derived answer could pick among them without gold. Literature:
Self-Consistency (Wang et al. 2023 §3.5); MBR-EXEC (Shi et al. 2022 Table 2: Spider greedy 50.8 → 63.6; checked in the PDF).

**Questions** (files hashed below):
- All 98 questions that PREF gets wrong on fresh4.
- 100 questions drawn from the 302 it gets right, by `random.Random("z1-step0-2026-11-25").sample`.
- They are read in one shuffled order (ids_step0.json), so a run cut by the slot end keeps both groups in proportion.

**Reader:** `q1_read_sample.py`, q1_read_v2.py (5c6e9c6d) changed only as its docstring lists.
- R3r adapter (kitR3r/out/sft, sha f94be8b9… as in PREREG_R3m), 0-shot.
- K = 8 samples per paragraph in one batched call.
- temperature 0.7, top_p 0.8, top_k 20, sample seed 20261125. Per-paragraph torch seed = sha256(seed|id|title).
- Thinking off, no token cap, the same per-row loop detector.
- The base reads are the greedy fresh4 base reads (c1d032ee…); they are not resampled.

**Analysis** (`eval_step0.py`):
- Per sample k, R3r sample k is merged primary-first with greedy base (reader_merge.py b4964509) and answered by the frozen
  official_score.py (7f9170e9, `--title-anchor --tiebreak shortest`). k = 0 is greedy PREF.
- **MBR-READ** = the majority answer over k = 0..8 by official normalisation. Empty answers do not vote. Ties go to k = 0 if it is
  tied, else to the smallest tied k.
- **Coverage** = among the stated gold facts of the read questions that neither greedy reader has (stated_recall logic), the share
  that appears in at least one sample.
- Self-test passed: greedy reads given as K = 2 "samples" reproduce PREF on 198/198 questions (gain 0, harm 0).

**Go/no-go (fixed now):**
- **GO for step 1** (PREREG_Z1s on fresh5, proposed to the user) if both hold:
  - extrapolated net gain ≥ +12 questions per 400 = gain on the read wrong ones scaled to 98, minus the harm rate on the read right
    ones × 302;
  - harm ≤ 3 per 100 right questions.
- **NO-GO, teacher path proposed** if coverage < 30 %: sampling does not produce the missing facts.
- **NO-GO** otherwise.
- If the slot ends before all 198 are read, the rule is applied to the read part. It is valid only if ≥ 40 questions of each group
  are read; otherwise the result is "undetermined", and step 0 is repeated in a later slot from where it stopped (the reader
  resumes).

**Descriptive:**
- "any sample right" per group: the ceiling of a perfect vote;
- vote margin vs correctness;
- seconds per batched call;
- loop-guard stops.

**Hardware:** RTX 3070 slot 25.11.2026 12:00–13:30 UTC (coordinator), the usual rules.
- Before the start: no other claude-* container except the ones on the ignore list, and the vision server answers a chat probe.
- Stop the vision server; run the reader with a timeout so that it ends by 13:25.
- EXIT trap: restart the vision server and log a chat probe.

**Limits:**
- fresh4 is spent, so this is development evidence only.
- One sampling setting; the sampling parameters are fixed here, not tuned.
- 198 of 400 questions, with the extrapolation stated as an estimate.
- Sampled reads are reproducible only up to GPU nondeterminism; the seeds are logged.

**Hashes (sha256):**
- q1_read_sample.py: see PLAN_Z1_step0.sha256.
- eval_step0.py: see PLAN_Z1_step0.sha256.
- groups.json: 819110bbab8a822c…
- ids_step0.json: 0ccba9b0dbd71066…
