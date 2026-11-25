# PREREG R3r — a dedicated reader for the Q1 pipeline (frozen 21.11.2026 20:06 UTC by PREREG_R3r.sha256, before any R3r training or any fresh2 read exists)

**How it came about (all on the development 400 or the spent fresh 400, research log 21.11 18:32–20:05 UTC).** With gold facts the
pipeline answers 94.0 % of the fresh 400, with the model's reads 70.75 %; 76 of the 98 reading-loss questions are attainable. On the
development 400, single readers give 62.0 % (base 2-shot), 58.75 % (R1-full), 57.75 % (kit R2); the union R1-full + base gives
72.5 %. R1-full omits countries (its targets lacked demonyms), kit R2 repairs countries but loses father (83 → 53/97), every reader
confuses kin roles. Three symbolic object-link rules gave no gain (rejected on dev).

**Kit R3r** (`build_r3r.py`, sha 6c7e4440d98052e2…; data split/train.jsonl sha cc3671af255ad0b3…, 16,125
rows): READ rows only, built like R1 from 2Wiki TRAIN paragraphs with every Wikidata claim whose value is stated in the text, demonyms
as surface forms of country values, every paragraph (no sample), paragraphs with ≥ 2 kin roles written three times (525). Dev
paragraphs and the D0 entities held out. Training as R1-full: Qwen3-0.6B, LoRA r 64, fp32, 2 epochs, default lr, seed 42, one RTX
3070 (RunPod; R1-full was trained on the 3070 of the CPU/GPU host — same GPU type).

**Test set fresh2:** `dev_fresh2_400.json` (sha c6aaddd2…), 100 questions per type from the 2Wiki dev set, disjoint from the fresh 400,
the development 400 and every earlier read (random.Random("q1-fresh2-2026-11-21")). Gold paragraphs read with `q1_read_v2.py`
(sha 5c6e9c6d…, unchanged): base 2-shot and R1-full 0-shot on the 3070 host (queued), R3r 0-shot on the pod.

**Arms:** OLD = union(R1-full, base 2-shot) — the current Q1 reader; NEW = union(R3r, base 2-shot); the SAME base read file in both.
Answers by the frozen `official_score.py` (sha 7f9170e9…) with `--title-anchor --tiebreak shortest`, official alias EM.

**Hypotheses (unit = question, n = 400, α 0.05):**
- **H-R3r1 (primary):** EM(NEW) > EM(OLD) — one-sided exact McNemar (`mcnemar_levers.test` logic: b = right only in NEW).
- Descriptive: R3r alone vs R1-full alone vs base alone; EM per type; `stated_recall.py` recall and conflicts per relation for each
  read file; the gold-facts ceiling on fresh2.

**Decision:** H-R3r1 holds → kit R3's reader rows are the R3r rows (and the deployed Q1 reader becomes R3r + base). It fails → the
current union stays; R3 adds no reader rows until a reader beats it on a fresh set.

**Named limits:** R3r and the base reads come from two RTX 3070s (pod / host; greedy decoding, fp32); one training seed; 2Wiki gold
is incomplete for precision; the reader prompt is fixed (d0_docs).

## Amendment 1 (21:32 UTC, before any fresh2 read or R3r output exists) — analysis script fixed
`score_r3r.py` (sha256 db326200f19b597b…): `union` builds OLD = R1-full reads then base reads and NEW = R3r
reads then base reads per question (the Q1 union order); `test` runs the one-sided exact McNemar on official_score.py's per-question
files and reports single-reader EM and EM per type. Dry run on the spent fresh 400: the union equals read_fresh_union.jsonl on 400 / 400
questions (line order differs, irrelevant to scoring), and the McNemar part reproduces PREREG_Q1_levers' 14 vs 1, p 0.000488.

## Amendment 2 (22:25 UTC, no R3r output read) — training interrupted by a full disk, resumed
The run stopped at step 19,000 of 32,250 at 22:21:19 UTC: the pod's 20 GB /workspace filled with a checkpoint every 500 steps
(the kit's trainer keeps all of them). checkpoint-19000 is incomplete (no trainer_state, scheduler, RNG state); checkpoint-18500 is
complete. The training resumes from checkpoint-18500 with the same settings through `resume_r3r.py`, a wrapper that leaves
training_runtime.py unchanged and only (1) passes resume_from_checkpoint to the trainer, which restores optimizer, scheduler, RNG
and data position, and (2) keeps at most 2 checkpoints. All other checkpoints are deleted first. Hypothesis, test set, arms and
analysis are unchanged; the interruption is named as a limit.

## Amendment 3 (22:34 UTC, before any fresh2 read exists) — one descriptive arm, nothing confirmatory changed
Also reported, descriptive only: OLD and NEW scored with `official_score_v2.py --grounded` (sha256 2611c76ad9d30d8a…; = v1 + optional levers, of
which only --grounded is used here: an entity-relation fact is kept only if every name token of its object occurs in the paragraph it
was read from). On the development 400 it gave 72.5 → 73.0 % (3 gained, 1 lost). The primary test H-R3r1 stays on the frozen v1 scorer.
