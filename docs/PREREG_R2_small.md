# PREREG R2-small — the small from-scratch model before any Qwen run of plan R2 (fixed 20.11.2026, before any run of it)

Plan: `docs/PLAN_R2.md`. Rule "small model first": a training hypothesis is first tested on a from-scratch tiny model with 10 seeds.

## Part A — way A (the model writes the rule): consolidated into H13s g3, plus one secondary measure
H13s g3 (`PREREG_H13s.md`, Amendment 3) already trains a tiny GPT to induce rule sets from worlds, with dose arms p100/p90/p50/p0
for name binding and test classes never trained (T2). No second way-A small-model run is started (rule "consolidate").
**Added secondary measure, no influence on any H13 gate — written before any g3 result was read by this session:**
- **solve@k:** for the final checkpoints of g3 seeds 2–9 (seeds 0–1 finished before their checkpoints could be kept;
  `ckpt_keep.sh` copies them, read-only towards the runs), every T2 item is decoded k = 16 times at temperature 0.8 (plus the greedy
  output); an item counts as solved@k when ANY of the first k samples is a correct rule set by the H13 scorer (clingo, the same check
  as greedy). Reported per arm for k = 1, 4, 16 with seed means.
- Question: does search + verification (the model proposes, the solver decides) find correct rules for NEW classes that greedy
  decoding misses? Test: per arm, solve@16 vs greedy accuracy on T2, paired over seeds (Wilcoxon signed-rank, one-sided, α 0.05).
- Reading: if solve@16 ≫ greedy in p0, the way-A kit trains with sampling + verification (expert iteration) and the agent samples;
  if solve@16 ≈ greedy ≈ 0, the tiny model has no usable proposal distribution for new classes and way A relies on Popper/gp2 as the
  proposer with the model only ranking.

## Part B — way B (the model applies given rules): a new small experiment
**Data** (`gen_traces_synth.py`, fixed seeds, generated before training): base facts over fresh symbols p1…p6 (binary), q1…q2
(unary), 8 entities; a rule library of derived predicates in layers — each rule is a chain2, filter or two-clause disjunction over base
or lower-layer predicates — so a query of depth d needs d nested rule applications. Item = query `rD(e3, Y)?` with exactly one answer;
target = one-step derivations (`use rK: body ⇒ head` in dependency order) and the answer. Steps are checked by clingo (every `use` is a
ground instance of the stated rule over given or earlier derived facts).
**Arms (the only difference):**
- **ctx:** every item carries its rules in the prompt, with fresh predicate names per item (names carry nothing).
- **mem:** one fixed library of 12 rules with fixed names; the prompt carries no rules — the model must recall them.
Both arms see the same rule semantics and the same worlds; only where the rule comes from differs.
**Splits:** train depth 1–3 (30,000 items); test I: depth 1–3, new worlds (600); test D: depth 4–5, new worlds (600) — compositions
never trained in either arm.
**Model:** `gpt.py` of H13 (pre-LN, RoPE, d 128, 4 layers, 4 heads), the H13 trainer settings (AdamW 2e-3, cosine, batch 32, 20,000
steps), greedy decoding; 10 seeds per arm; GPU (RunPod, synthetic data only) or the AMD host after g3.
**Measures (unit = seed):** faithful accuracy (all steps valid AND the answer follows AND it is the gold answer) on test I and D;
answer-only accuracy; per-depth curve.
**Hypotheses:**
- **H-B1 (primary):** on test D (depth 4–5) faithful accuracy ctx > mem. One-sided Mann-Whitney U over the 10 + 10 seed means, α 0.05.
- **H-B2:** on test I ctx ≥ mem − 5 points (non-inferiority: 95 % bootstrap CI of the seed-mean difference above −5).
- Descriptive: depth curve 1–5 per arm; the gap answer-only − faithful (answers without a valid derivation).
**Decision for kit R2:** H-B1 holds → way B gives the rules in the prompt (retrieved from the library) and trains application;
H-B1 fails → rules are trained as memorised competence and the solver applies them in the agent (the trace is then explanation,
not mechanism). Either way the solver stays the fallback.
**Named limits:** synthetic worlds with fresh symbols, not natural language; one model size; depth 4–5 is a short extrapolation.

## Note 1 (20.11.2026 ~21:00 UTC, after the runs started, before any result was read) — a named confound, descriptive only
Depth 4–5 targets are longer than every training target (≤ 3 use lines). A test-D failure in both arms could be length/position
extrapolation (RoPE), not rule application (cf. Dziri et al. 2023, arXiv 2305.18654; arXiv 2511.07378 on length generalisation with
explicit steps). Added descriptive analysis, no gate: on test D, the share of items whose FIRST THREE use lines are all valid, per arm.
The hypotheses, tests and decision above are unchanged (the hash in PREREG_R2_small.sha256 covers the text above this note).
