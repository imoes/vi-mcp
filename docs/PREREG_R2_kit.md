# PREREG kit R2 — the consolidated Qwen3-0.6B kit of plan R2 (draft 21.11.2026 ~01:50 UTC, amended ~01:55 UTC — distractor padding — still before any R2-small Part B/C result was read)

Plan: `docs/PLAN_R2.md` step 3. One kit, both ways, the arms as columns of the data, not separate runs (rule "consolidate").
Written before any result of R2-small Part B (10 seeds) or Part C was read; the two places that depend on them are fixed here as
rules, not left open.

## Data (all built and checked on the CPU host, synthetic or public 2Wiki/Wikidata only; token counts with the Qwen3 tokenizer)
| component | source | rows available | used | tokens used (≈) |
|---|---|---|---|---|
| Way A synthetic, fresh symbols | `gen_rules.py`, minimality-checked, 8 families × 2,000 | 16,000 | 6 trained families × 1,000 | 4.7 M |
| Way A kinship, names + fresh twin | `gen_kin_rules.py` from 2Wiki TRAIN, teacher = train-selected Popper rule, unique-minimal check | 3,622 (1,811 tasks × 2 arms) | all | 2.5 M |
| Way B 2Wiki derivations | `trace_2wiki.py` → `check_trace.py` → `add_distractors.py --pad 15,55` → `unique_check.py` | 21,579 (21,499 with distractors) | 8,000 (stratified by type) | 5.7 M |
| Way B synthetic depth | `gen_traces_synth.py` (rule decided by Part B/C, below) | 30,000 | 3,000 | ≈ 0.6 M |
| Reading replay R1d | kitR1d (demonym-aware), read + write rows | 30,150 | 10,000 | 2.3 M |
| Cycle rows | `build_cycle.py` | 15,075 | 5,000 | 1.2 M |
Total ≈ 17.0 M tokens per epoch. Replay share (R1d + cycle) ≈ 21 % of tokens — 13R showed 20 % replay prevents forgetting
(language_heldout 30/30 vs 0/30, paired, one seed).

**Way B distractors.** The 2Wiki traces carry the facts a reader would return: the kit-R1d facts and every 2Wiki train evidence
triple about the ten context paragraphs (reader relations only), minus facts that fill a gold slot (same linked subject and
relation). Those alone gave only median 5 distractors (p95 12), while the union reader returns p10 18 / p50 29 / p90 54 facts per
dev question; so each prompt is padded to a count drawn uniformly from 15–55 with facts of other paragraphs (never one that fills a
gold slot) → p10 19 / p50 35 / p90 52 facts. The oracle gives a different answer with the distractors in 57 rows (0.26 %), which
keep their plain prompt. Every gold target passes `check_trace.check` on its new prompt. Data sha256 prefixes: way B
3d5648b7…, kin train d3eee77c…, kin dev b954f6cd…, way-B dev eval (union reads, variants read / gold+read) 0e79227d….

## Held-out (never trained)
- Way A families **chain3** and **join** (shapes composed from trained pieces: a longer chain; a conjunction on one pair).
- Way A kinship tasks from 2Wiki DEV questions (`kinA_dev.jsonl`, 736 rows, both arms).
- Way B: 2Wiki dev questions (step-3 set of 400 and the full dev with gold facts); synthetic depth 4–5.

## Rules fixed now, decided by R2-small
- **Rules in the prompt (Way B synthetic arm):** if H-B1 holds (ctx > mem on depth 4–5), the synthetic Way B rows give the rules in
  the prompt; otherwise half carry the rules and half rely on the library seen in training, so the kit measures both.
- **Step index:** if H-C1 or H-C2 holds, every Way B target (synthetic and 2Wiki) carries `step k:` lines; otherwise none does.

## Training
Qwen3-0.6B, LoRA r64, fp32 (Ampere/Ada card, never Blackwell), one SFT stage over the mix, 1 epoch first; seed 42.
Throughput is measured on the first 200 steps (estimate from 13R on the 3060: ≈ 400 tokens/s — a hypothesis, not a number to plan
on); the run is stopped and re-planned if one epoch would exceed 10 h. No max_new_tokens in generation; a loop detector stops
repeated lines (`stopped_repetition` counted).

## Measures and targets
1. Way A: exact rules (clingo: derives exactly the positives in both worlds) on held-in synthetic families, held-out chain3/join,
   kinship dev — per arm (names vs fresh). solve@1 greedy and solve@8 (temperature 0.8).
2. Way B: faithful trace rate (`check_trace`: every step valid and the answer follows) and correct answer, on 2Wiki dev with gold
   facts + distractors from dev reads, and synthetic depth 1–3 / 4–5.
3. Reading not forgotten: R1d read accuracy and the step-3 pipeline (EM on the 400 questions with the kit model as reader, goal
   from the templates) — no worse than R1-full (paired McNemar, two-sided, α 0.05).
**Primary contrast:** kit R2 vs the base model on Way A kinship dev (exact rules, paired by task, McNemar one-sided α 0.05) and on
Way B 2Wiki dev faithful rate (paired, one-sided). **Named limits:** one seed first; synthetic shapes; 2Wiki labels have noise
(founder: founded by vs has part).

## Addendum 1 (21.11.2026 ~02:10 UTC) — measurements, no change to hypotheses or gates
- Dry build (`build_kit_r2.py --wayb-synth-arm both`, Part C still open): 35,622 rows, 18.52 M tokens (estimate above 17.0 M;
  derive_synth 1.53 M instead of 0.6 M). Token audit (`train.py --tokenizer-only --fp32`): valid, 0 rows rejected.
- Throughput probe on an RTX 3070 (fp32, LoRA r64, batch 1, 0.01 epoch = 356 steps): 139.8 s, **2.55 rows/s ≈ 1,300 tokens/s**
  (the 13R-based estimate of 400 tokens/s was 3× too low). One epoch ≈ 3.9 h on the 3070 → the run goes to the internal RTX 3070
  host, no RunPod cost; well inside the 10 h gate.
- The scorer (`score_kit_r2.py`) passes every gold rule (300/300 held-in, 200/200 held-out, 736/736 kinship dev) after three fixes
  found by that check: '~' parsing, recursion (target in the body), and 90 ill-posed names-arm items whose target shared a fact
  predicate's name (father/mother/child → `inferred_<rel>`).

## Addendum 2 (21.11.2026 ~03:05 UTC, before any Part C result) — order of runs, decision rule unchanged
Part C is delayed (OOM, now ≈ 08:30–09:00 UTC) while the internal RTX 3070 is idle. **Run 1** (seed 42) trains the variant WITHOUT
step index now (`--wayb-synth-arm both`). If H-C1 or H-C2 holds, **run 2** trains the step-index variant (same seed, same mix
otherwise); run 2 is then the pre-registered kit and run 1 its paired ablation (does the step index help Qwen? same items, McNemar
two-sided, descriptive). If neither holds, run 1 is the kit and no run 2 is trained. Fixed now so that the choice cannot follow the
results.

## Addendum 3 (21.11.2026 ~04:10 UTC, before any result of run 1) — expert-iteration stage for way A (PLAN_R2 step 3)
After the SFT run that is the kit (run 1 or run 2 per addendum 2): the tuned model samples K = 8 rule sets at T 0.8 per task on
1,800 FRESH way-A tasks (`gen_rules.py --seed 20`, the six trained families × 300, no prompt shared with SFT or evaluation; sha256
of the prompts 49a75fef…), with `ei_sample.py` (no token cap; per-row stop at EOS or a 3rd repeated line). `ei_build.py` keeps per
task the clingo-exact sample with the fewest body literals. Next round: continue from the SFT adapter for 1 epoch on the EI rows plus
a 20 % replay sample of the SFT mix (same seed). **Measures:** solve@1 (greedy) on way-A held-in, held-out (chain3/join) and kinship
dev, before vs after EI, paired by task (McNemar, one-sided "after > before", α 0.05 per set); solve@8 before EI is reported as the
ceiling the EI round can reach. If the SFT model solves fewer than 50 of the 1,800 tasks at k = 8, the EI round is not run (too few
self-proposals; Part A of R2-small then points to Popper/gp2 as proposer) and that is reported.

## Addendum 4 (21.11.2026 ~06:10 UTC, before any answer of run 1 exists) — the synthetic way-B set was missing from the build
Measure 2 names synthetic depth 1–3 / 4–5, but `build_kit_r2.py` wrote only the 2Wiki way-B evaluation set. Added: 600 items from
R2-small's test files (arms ctx and mem, 60 per depth 1–5, seeded sample, prompts sha256 91dc17ea…), scored with the R2-small checker
(`gen_traces_synth.check`, gold targets 600/600 faithful). Tuned and base answers are produced on the same RTX 3070 after the base
answers (`run_synth_eval.sh`). Also before any answer: the answer scripts and the reader now stop a loop inside one line
(a block of 8–2,000 characters repeated three times at the end), found when one base answer ran 3 h on the 3060; still no token cap.

## Addendum 5 (21.11.2026 ~07:35 UTC, after run 1's way-A answers and Part C were read, before any EI sample exists)
Run 1 writes the right rule shape but chooses predicates at random (held-in 17/300 exact; shape-exact with clingo binding 145/300,
exploratory). Part C failed (no step index), so run 1 is the kit. The EI stage of addendum 3 runs unchanged; its reading is fixed now:
it tests whether training on the model's own verified samples teaches the data-driven predicate choice (exact solve@1 after EI vs
before, paired, as registered). **Added measure (evaluation only, no training):** solver calls to an exact rule on held-in, held-out
and the random-fresh kinship set, for (a) the model's greedy shape with clingo binding, then its K = 8 sampled shapes in order, vs
(b) every trained shape in a fixed order (chain2, inverse, disj, filter, neg, recursion) with the same binding; reported as solved
share and mean calls per solved task, before and after EI. A model is worth keeping as proposer only where (a) needs fewer calls
than (b) at the same solved share.
