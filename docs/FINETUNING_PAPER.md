# Teaching a 0.6B Model to Work by a Philosophical Seed: Thirty Fine-Tuning Runs, Measured by a Solver

*Working paper, vi-mcp project, 16.11.2026, updated 18.11.2026 (runs 27 and 30, §5.18–5.22). Companion to [PAPER.md](PAPER.md) section 6 and the guide [FINETUNING.md](FINETUNING.md).
Every number below was measured in this project unless it carries a reference; every reference was read for this work (the PDFs are kept
with the experiment files). What is not measured is marked as hypothesis or estimate.*

## Abstract

A philosophy package of vi-mcp states the principles of an AI collective only as a checked clingo-object rule set — the *seed*, here
`kollektiv` 1.2.0 with 7 blocks and about 35 rules over default negation, four-valued answers, acceptance levels and deontic duties. A
memory server runs the seed with a solver. We asked whether a small model can carry the seed in its weights and work by it *without* a
solver: judge situations described in English, resist pressure, translate the seed into prose and back, and recite it. We trained
Qwen3-0.6B (and twice Qwen3-1.7B) with LoRA in nineteen runs and scored every answer with the solver, never with a judge model.

Five results carry the paper. (1) **Output format decided more than any other factor**: a chain of thought that first lists the parsed
facts raised exact verdicts on held-out worlds from 18/40 to 29/40 (paired sign test p = 0.013); enumerating every evidence line with the
reason it counts or not raised them to 39/40, and to 154/160 on 160 further worlds, with no invented certainty. (2) **A model recites only
what was a training target**: the seed was a target in 5 of 7,700 rows, and the model answered "Duties: none."; with 360 recitation rows
it recited the seed exactly (46/46 worlds for the whole seed and for every block) while its prose explanations still followed
counterfactual programs, i.e. stayed translation. (3) **Reading unseen phrasings was the bottleneck, and its cause was omission**: the
same model that solved 39/40 worlds with training phrasings solved 3/40 with held-out phrasings; most errors were sentences silently
skipped, and voting over samples did not help (the errors were systematic). Numbering the sentences, one output line per sentence with a
trained *unknown* class, type definitions and phrasings from several generator families (run 19) raised exact fact lists on held-out
phrasings from 11/40 to 40/40, verdicts from 24/40 to 37/40 (p = 0.0002), pressure from 16/30 to 25/30 and formalization from 5/20 to
19/20. (4) **The model explains what its language stage could express**: three prose errors that survived four runs came from rule forms
the generator never produced (shuffled head variables, constants in heads, several heads on one body); adding them brought six of seven
blocks to a perfect round trip (296/322 worlds, run 15: 259). (5) **GRPO sharpened, it did not teach**: +6/146 worlds (p = 0.15) with
entropy near 0.02. The paper lists what is still open, and the measurement errors we made and corrected on the way.

The update of 18.11.2026 adds three results. (6) **Length must be trained**: worlds with 7–8 statements were 0/40 for run 27 although
every fact was read — its per-statement lists stopped at the longest trained world (6); training worlds of 1–10 statements made them
35/40 and 39/40 in two arms (run 30). (7) **What is left is skipped steps, not misreadings**: with the facts right, the remaining wrong
worlds lack a line of the written trace that exists only because of a fact (a source, a foreign statement); forcing exactly that line
repairs 25 of 26 such worlds without training (free: 12 of 26; 26 of 43 answered so far), and the model continues the trace correctly. The skips concentrate where the training
mix thinned out (short worlds: 34 % of the relevant statements in one arm, 6 % in long worlds, run 27: 7 %). (8) **Two runs with the same
data slip in different places** (one invents a predicate for a held-out phrasing, the other skips a different trace line), as
fine-tuning runs are known to differ out of distribution [52] — a format question cannot be decided from one pair of runs.

## 1 Goal and targets

The targets were set before the runs (one run must meet all at once, on clean held-out worlds):

| target | threshold |
|---|---|
| language: random rule sets ↔ English, both directions | ≥ 95 % |
| judge worlds with training phrasings, exact (all answers and duties) | ≥ 80 %, invented certainty ≤ 5 % |
| judge worlds with held-out phrasings ("paraphrase") | ≥ 70 % |
| judge under pressure (the question claims a wrong rule) | ≥ 80 % |
| formalize: held-out sentences → the seed's facts, exact | ≥ 80 % |
| the seed in prose: every block in prose; round trip ≥ the control | control 74 % |
| counterfactual programs: the prose follows the given program, not the memorised seed | followed |

*Invented certainty* is a firm value (true/false) where the seed says unknown, both, or gives no verdict — the error a solver-less model
must not make (cf. AbstentionBench [1]: reasoning-only training erodes abstention).

## 2 Setup

**Seed and worlds.** `kollektiv` 1.2.0 (package hash fixed per run): P1 independent lines (an author's own evidence does not count), P2
support and opposition, P3 four values over a closed view (default negation only in closure rules), P4 reasons, P5 acceptance, P6 duties,
P7 verified sources. A *world* is 5–20 ground facts (`author`, `line`, `closed`, `peer_offers`, `foreign`, `unreviewed`, `source`,
`verified`); the solver gives the gold verdict. Each fact type has 2–3 training phrasings and held-out test phrasings (`render_test`)
that never occur in training.

**Model and training.** Qwen/Qwen3-0.6B, LoRA rank 64 on all linear layers (runs 1–2: rank 16), fp32, batch 1, TRL SFT with loss on
the completion only. Two stages: A (language: rule sets ↔ English) and B (the seed: judge, formalize, pressure, and from run 7 on a replay
of 1,000 stage-A rows), 2 epochs each, stage B with lr 2e-4. GRPO with TRL's GRPOTrainer (loss `dapo`, β = 0). Hardware: an NVIDIA RTX 3070
(8 GB) and an AMD Strix Halo APU (gfx1151, ROCm), each run in its own container; fp32 on both (measured: bf16 brought no speed-up for this
model on the RTX 3070, 46.4 s vs 43.6 s per 240 steps; bf16 has known problems on gfx1151).

**Evaluation.** Greedy decoding, thinking off, a token budget against loops whose reaching is recorded ("budget"), never a silent cut.
Sets: `judge_same` 40 worlds (training phrasings), `judge_paraphrase` 40 (held-out phrasings), `pressure_heldout` 30, `formalize_heldout`
20, `package_worlds` 16, from run 15 `judge_more` 160, plus tagged copies; prose items: the whole seed, each block, five counterfactual
programs; recitation. Verdicts are parsed and scored against the solver (`phil_score.py`), never judged by a model. No evaluation world
occurs in training (checked by assertion since run 8; runs 5–7 had leaks, §5.15).

**Round trip.** Prose is translated back into clingo-object *literally* — only what is written, nothing completed from knowledge of the
seed — and the rebuilt rules are run on 46 worlds (16 package + 30 random) with the other blocks given; agreement = same answers, duties
and violation status. The back-translator for runs 8 onwards is the author (Claude); because the author knows the seed, the
counterfactual programs are the check: a back-translation from memory would agree with the seed, not with the counterfactual program.

**Statistics.** Same items across runs, so runs are compared paired (exact two-sided sign test on the worlds where they differ); where
noted, Fisher's exact test. With n = 40 the 95 % interval of a proportion near 0.7 is about ±15 points (Wilson): differences of 2–3
worlds are noise.

## 3 The runs

| run | what changed | main result (tuned model; the base model scores 0 on every set) |
|---|---|---|
| 1 | SFT on the memory export, 0.25 epoch | held-out NLL 2.27 → 1.29, but useless: 96 % of rows used an object's own text as the question; the model echoed pages, loops in 55 % |
| 2 | rank 16, 3 epochs, all rows | no gain on questions about held-out documents (p ≈ 0.1) |
| 3 | 500 documents × ~5 grounded question pairs, rank 64, 4 epochs | knowledge probe (new questions on trained documents): 7 correct / 9 partial of 60 vs base 0/5, sign-flip p = 0.008; never abstains, invents hosts |
| 5 | first seed run: formalize, judge, pressure | clean: judge 20/38, paraphrase 18/37, pressure 15/26, formalize 13/20 (no P7 facts in its eval, not comparable to later runs) |
| 6 | stage A language (3,000 random rule sets), then seed stage without language rows | **catastrophic forgetting**: random rules translated 8/8 after A, 0/8 after B |
| 7 | as 6 + 1,000 replayed language rows in stage B | language back (12/12); judge 19/40, paraphrase 4/37; seed prose still in verdict format |
| 8b | language stage extended to the seed's forms (arity 3–4, constants, nested duties), task tags, a distractor philosophy | seed blocks in prose 6/7; round trip 185/276 (old measure) |
| 8 | as 8b + the seed's *vocabulary* (never its rules) in translation tasks | every explain item in prose; blocks 220/322 (corrected measure); whole seed cut off after P3 |
| 9 | as 8 + reading practice (situation → facts) in stage A | paraphrase 7/40, judge 14/40 |
| 10 | as 9 + ~50 verified LLM paraphrases per fact type | paraphrase 11/40, formalize 8/20, judge 16/40, pressure 9/30 |
| 11 | as 8 + long programs (10–40 rules) in stage A | whole seed explained to the end for the first time (2/46); blocks 281/322 |
| 12 | as 8 + **facts-first** chain of thought | judge **29/40** (vs 18/40, +14/−3, p = 0.013), invented certainty 0/40; paraphrase 7/40 |
| 13 | as 10 + a flat solver trace (all derived atoms) | judge 26/40, **paraphrase 16/40** (vs run 12: +10/−1), package 15/16 |
| 14 | GRPO on run 10 (G = 4, lr 5e-6, 240 steps) | +6/146 verdict worlds (+9/−3, p = 0.15); entropy ≈ 0.02 |
| 15 | as 12 + **enumerated count trace** + the seed as **recitation target** (code only) + long programs | judge **39/40**, judge_more **154/160**, package 16/16, invented certainty 0/213; **recite 46/46**; paraphrase 3/40, pressure 2/30, formalize 1/20; blocks 259/322, whole seed 8/46 |
| 16 | kit 12 unchanged, **Qwen3-1.7B** (AMD host) | paraphrase 16/40 (vs 7/40, +12/−3, McNemar p = 0.035), judge 25/40, pressure 12/30, formalize 4/20 |
| 17 | GRPO v2 on run 12 (prompts in SFT form, paraphrase + pressure prompts, abstention −0.5, ε_high 0.28) | out of memory at step 1 on 8 GB (≈ 4.7 GB of fp32 logits alone); postponed |
| 18 | run 15 + training paraphrases + 2,000 per-sentence reading rows + reading practice | paraphrase **24/40** (vs 15: +21/−0, p < 0.001), pressure 16/30 (+15/−1, p = 0.0005), judge 36/40, judge_more 144/160, formalize 5/20; fact list fully right in 11/40 paraphrase worlds; blocks 244/322; recite P5 19/46 |
| vote | inference only, run 15's adapter: 8 samples per world, majority per fact (T 0.7 and 1.0), LoRA scaled ×0.5 | facts exact greedy 4/40, majority 3/40 (both T), LoRA×0.5 0/40; at least one sample exact 9/40 at T 1.0 (pass@8) — errors systematic for voting, a signal left for RL |
| 18b | kit 18 on Qwen3-1.7B (AMD host) | vs run 18 (0.6B, same kit): judge_more **158/160** (+15/−1, p = 0.0005), paraphrase **31/40** (+9/−2), pressure **23/30** (+8/−1, p = 0.039), formalize 10/20 (+6/−1), judge 37/40; all world sets +37/−5 — size helps, but run 19's and 20's recipe on 0.6B is ahead (paraphrase 37/40, pressure 27/30) |
| 19 | run 18 + **numbered sentences, one line per sentence, trained *unknown* class**, type definitions with rotating examples, multi-generator phrasings, anchored recitation, 600 language rows with the seed's missing rule forms | paraphrase **37/40** (vs 18: +13/−0, p = 0.0002), facts **40/40**; pressure **25/30** (+12/−3, p = 0.035), facts 30/30; formalize **19/20**; judge 34/40 (ns), judge_more 147/160, package 16/16, invented certainty 0/400; **recite 46/46 for every block**; blocks **296/322**, 6/7 perfect, counterfactuals 5/5 |
| 20 | run 19 + **duty trace** (solver-checked), negative type queries, guideline dropout | judge **39/40** (vs 19: +6/−1), tagged **20/20** (+4/−0), judge_more **150/160** (+11/−8), pressure **27/30** (+5/−3), formalize **20/20**, paraphrase 37/40 (+3/−3), package 15/16; all sets pooled +29/−16 worlds (sign test p = 0.07); invented certainty **3/433** (run 19: 0/400) |
| 21 | run 20 + standalone near-topic negatives (codex) + two-fact sentences | stopped after stage A start: replaced by 21b after the minimal pairs of run 20 and the negation research (contrast pairs instead of standalone negations) |
| 22 | run 20 + **value check** (support, opposition, closed → value; solver-checked) | paraphrase **40/40** (+3/−0), judge **40/40**, judge_more **157/160** (+10/−3), package 16/16, pressure 28/30 (+3/−2), formalize 20/20; pooled **+18/−5** worlds (p = 0.011); invented certainty **1/433**; the 3 judge_more errors are duties in the largest worlds (18–19 sentences) |
| 21b | run 20 + **contrast twins** (codex minimal edits in five forms, qwen-filtered, 25 % of fact sentences) + negatives 5 % + two-fact sentences | minimal pairs **25/30** (unknown **6/9** vs 3/9, +3/−0), facts unchanged (no over-abstention); pressure **30/30** (+3/−0), judge_more 154/160 (+7/−3), judge 40/40; second minimal test (qwen27b, 35) 26/35 |
| 23 | 21b + value check (the two changes combined, same worlds as 21b) | minimal pairs **27/30** (unknown **8/9**, groups 7/10), invented certainty **0/433**, pressure 30/30, judge 40/40, paraphrase 39/40, package 16/16, formalize 20/20; judge_more 154/160 (run 22: 157); second minimal test 25/35 |
| 24 | 23 + 400 language rows for the constant-in-ternary-body form | language **29/30 = 97 %** (run 22: 28/30); judge_more **158/160** (+6/−2 vs 23); other verdict sets at the ceiling; minimal pairs 24/30 (Claude's test) and 28/35 (qwen's test) — opposite moves vs 23, within noise |
| 20b | kit 20 on **Qwen3-1.7B** (AMD host) | verdict sets vs run 20 on the 270 answered items: +6/−1 worlds (judge 40/40, paraphrase 38/40, pressure 29/30, package 16/16; no set significant, min mid-p 0.375), invented certainty 0 (run 20: 1) — at the ceiling, generation stopped there; **minimal pairs 23/30 (unknown 3/9 = run 20) and 12/35 on qwen's test (unknown 2/25)**: run 23 (0.6B + contrast twins) beats it **+19/−2 (p = 0.0002)**, run 24 +20/−3 — reading negation, future and questions is a data gap, not a capacity gap [50, 51] |
| 22 seed 43 | run 22, training seed 43 instead of 42 (same kit, same host) | the **noise level** between two seeds of one recipe: worlds pooled **+5/−5** (judge_more +3/−3, paraphrase +0/−2, pressure +2/−0, judge and package identical), formalize facts +0/−2, invented certainty 1 vs 1; minimal pairs 21/30 in both (unknown 2/9), qwen's test 9/35 (run 22: not run). So a set moving by 2–3 items between two runs is within seed noise (Dodge et al. [36]); run 24 vs 23 on the minimal pairs (+3/−6) is within it, run 23 vs 20b (+19/−2) and run 22 vs 20 (+18/−5) are not |
| 27 (consolidated) | every finding that held in one kit: stage A of run 24 (language rows) + stage B of run 26 (value check, duty trace, contrast twins veridical-filtered and balanced per form) with training worlds of **1–6 statements** and a copied **statement-list line** before the count (index hint) — the lessons of the long-world test, where runs 20b, 23 and 24 reach at most 1/40 because their per-statement lists stop at the trained length of 3. The single-change arms 25 (twin cues), 26, 28 (list line only), 29 (lengths only) and the adapter merge were cancelled instead of run one by one. Tests: held-out set, both minimal-pair tests, judge_long (4–5, now in range) and judge_xlong (7–8, held out) | every verdict target: judge 40/40, paraphrase 40/40, pressure 28/30, formalize 20/20, judge_more **158/160**, invented certainty 0, language 30/30; judge_long (4–5 statements) **37/40** (runs 20b/23/24: ≤ 1/40); **judge_xlong (7–8) 0/40** with complete answers — every fact right, but the statement list ends at "s6 (6)", the longest trained world (§5.18); seed prose 5/8 items (P5 32/46, P6 0/46) |
| 30ag | run 27 + training worlds of **1–10 statements** (stage B), 600 language rows with programs of 5–12 rules, statement line copied **without** the count; stage B on the RTX 3070 with the fp32 attention fix (§5.18), seed 42 | judge_xlong **35/40** (vs 0/40), judge_long 39/40, 1–10-statement set 38/40; judge 37/40, paraphrase 34/40, pressure 27/30, formalize 20/20, invented certainty 1/535; language_long 20/20; minimal pairs **29/30** (unknown 9/9), qwen's test 33/35; seed prose blocks 604/644 (P5 44/46, **P6 28/46**), whole seed 0/46; but **judge_more 144/160** (run 27: 158, §5.19) |
| 30bg | as 30ag with the count "(N)" in the statement line (as run 27) | judge_xlong **39/40**, judge_long 36/40, 1–10 set 37/40; judge 39/40, paraphrase 35/40, pressure 28/30, formalize **17/20** (§5.20), invented certainty 2/535; judge_more **149/160** (vs run 27 +2/−11, mid-p 0.013); minimal pairs 26/30, qwen's test 30/35 |
| 30cg | as 30ag, training seed 43 | running at the time of writing — the seed-noise reference for 30ag vs 30bg |
| 31, 31h9 | 30a's long worlds **on top of** every row of run 27 (no redistribution, §5.19) + every statement's ask and adopt line written ("→ not met", §5.19); 31h9 adds 600 language rows with 2–3 duty rules over one body (§5.21). 31 on the RTX 3060, 31h9 on the RTX 3070 (hardware replicate of run 23 on both cards: every set identical except judge_more +4/−2, mid-p 0.45) | running at the time of writing |

## 4 Status against the targets (runs 19 and 20)

| target | run 15 | run 19 | runs 20/22 | met |
|---|---|---|---|---|
| judge, training phrasings | 39/40; 154/160 | 34/40 = 85 %; 147/160 = 92 %; invented certainty 0/400 | 39/40 = 97.5 %; 150/160 = 94 %; invented certainty 3/433 = 0.7 % | yes |
| judge, held-out phrasings | 3/40 | 37/40 = 92.5 % | 37/40 = 92.5 % | yes |
| pressure | 2/30 | 25/30 = 83 % | 27/30 = 90 % | yes |
| formalize held-out sentences | 1/20 | 19/20 = 95 % | 20/20 | yes |
| recitation | 46/46 whole seed and each block | 46/46 whole seed and each block | 46/46 whole seed and each block (run 22) | yes |
| seed in prose, round trip ≥ control | 259/322 = 80 % | 296/322 = 92 % ≥ 74 % (control to be re-measured, §5.15) | **322/322** (run 22) | yes |
| every explain item perfect (8: whole seed + 7 blocks) | 4/8 | 6/8 (P6 one rule wrong; whole seed 17/46) | 7/8 (run 22: all blocks 46/46; whole seed in one answer 15/46, block by block 46/46) | yes, block-wise |
| counterfactual programs followed | 3 of 5 | 5 of 5 (46/46 each) | 5 of 5 (46/46 each, run 22) | yes |
| language (30 held-out rule sets) | 30/30 (runs 10, 13) | not re-measured | 28/30 = 93 % (run 22); **29/30 = 97 % (run 24**, the constant-in-body form trained) | yes (run 24) |

**After runs 27 and 30 (18.11.2026).** Run 27 holds every verdict target (judge 40/40, paraphrase 40/40, pressure 28/30, formalize 20/20,
judge_more 158/160, invented certainty 0, language 30/30) and adds worlds of 4–5 statements (37/40), but not 7–8 (0/40). Run 30 closes
the length gap (35–39/40 on 7–8 statements, 37–38/40 on 1–10) and keeps every verdict target within seed noise except two sets that fell
in the same direction in both arms: judge_more (144 and 149 against 158/160) and, in one arm, formalize (17/20). Seed prose improves at
block level (604/644 against 524/644; P5 44/46 against 32/46) but no run explains the whole seed in one answer, and P6 stays the open block
(28/46). The target "every explain item perfect" is not met; the others are.

Run 19 meets every target but the perfect prose of every item and the re-measured language set. Run 20 keeps every verdict target and
raises the judge sets (pooled +29/−16 worlds, p = 0.07 — a trend, one seed); it is the first run since 12 with invented certainty above 0
(3 of 433 uncertain subjects, §5.16). Run 19 is one training seed; the effects
that carry it (+13/−0, +29/−0 on facts) are far above the seed variance of §7, the small differences (judge 36 → 34/40) are not.

## 5 Findings

### 5.1 An object's own text is not a question
Run 1 trained 20,066 of 20,957 rows with an object's own text as its question; held-out loss fell, and the model echoed and continued
pages and looped in 55 % of its answers. Loss measures absorption, not task success.

### 5.2 Knowledge needs varied grounded pairs, and it is measured with a probe
Run 3 trained about five grounded question–answer pairs per document and was measured with *new* questions about *trained* documents
— a knowledge probe [2, 3]: 7 correct / 9 partial of 60 against 0/5, p = 0.008. Questions about held-out documents (run 2) cannot be
answered closed-book. The tuned model never abstained and invented hosts, as fine-tuning on new knowledge is known to do [4]; this is one
reason the seed path exists — truth is the seed's business, not the network's.

### 5.3 Forgetting, and replay
A seed stage without language rows overwrote the language stage (run 6: 8/8 → 0/8 on the same held-out rule sets). Replaying 1,000
language rows inside the seed stage (run 7) restored it completely (12/12) with the verdicts unchanged within noise.

### 5.4 Format specialization and the coverage gap
After run 7 the model still answered "explain the seed" with a verdict. Two causes were measured: half of the judge prompts had shown
the seed's code before the situation, so "seed code → verdict" was literally taught (format specialization), and the language stage
produced almost only unary and binary predicates while the seed uses arity 3–4, constants and nested duties (a structural generalization
gap). Task tags, a language stage extended to the seed's forms and a distractor philosophy (run 8b) gave 6/7 blocks in prose; the seed's
vocabulary in translation tasks — guarded so that no seed rule ever appears (normal-form comparison) — gave all of them (run 8).

### 5.5 Long programs make the whole seed explainable
Run 8 explained blocks but broke off the whole seed after P3. Training programs as long as the seed (10–40 rules; length
generalization needs long training examples [5]) made run 11 explain all seven blocks in one answer. The long answer still collects
local errors — a dropped negation, a wrong arity — and agrees on only 2–8/46 worlds, against 0.87⁷ ≈ 0.38 if block errors were
independent; errors accumulate faster with length (exposure bias grows roughly quadratically with length [6]).

### 5.6 Facts first
Run 12 changed only the answer format: list the parsed facts, then judge. Exact verdicts rose from 18/40 to 29/40 on the same worlds
(+14/−3, p = 0.013) and invented certainty fell from 5/40 to 0/40. This is the small-model form of "translate, then solve": a prompt-only
verify-before-answer step raised a 32B model from 59 % to 82 %, and LoRA SFT on solver-certified chains of thought raised 4B and 7B models
to 91–93 % on negation-as-failure programs [7]; per-premise formalization raised a 13B LoRA model from 22.7 to 32.0 on FOLIO [8].

### 5.7 Enumerate, do not summarize
Accuracy fell with the number of evidence lines (1 line 15/17, 3 lines 14/22 in run 8): a counting error. Run 15 lists every evidence
line on its own row with the reason it counts ("excluded, w is the author of s3"; "not counted, not verified"), then the distinct origins
per side, then the verdict; the trace is generated from the seed's own `counts` atoms and checked against them, so it states no second
semantics. Exact verdicts: 39/40 (vs run 12 on the same worlds +11/−1, McNemar p = 0.006), and 154/160 on 160 fresh worlds. The literature points the same way: one inference step at a time
generalizes where all-at-once does not (ProofWriter: 93.9 % vs 44.6 % at unseen depth [9]; selection–inference [10]); counting works when
items are separated (96.8 % vs 45.7 % [11]); detailed scratchpads make small transformers learn arithmetic from 1k examples [12, 13]. A flat
list of all derived atoms (run 13) did less for verdicts (26/40) than the enumerated count.

### 5.8 Recitation needs the seed as a target
Asked to state its rules, every model before run 15 answered "Duties: none.". The count explains it: the seed's rules stood in the
*prompt* of 761 training rows and in the *target* of 5; SFT computes the loss on the completion only, so the rules received almost no
gradient. Knowledge that is never a target is not extractable [2], and a mapping learned in one direction is not available in the other
(reversal curse [14]; reverse training fixes it [15]); models that recall their specification were trained to cite it [16]. Run 15 added
360 recitation rows (16 phrasings, half with the rules shuffled inside their blocks) with the seed as **code only**, never as prose — so
explaining the seed remains a translation test. Result: 46/46 for the whole seed and for every block, with phrasings never seen; the
explanations still followed counterfactual programs (P2, P3, P5 46/46). Recitation did not turn explanation into recall.

### 5.9 Reading was the bottleneck
Run 15 solves 39/40 worlds with training phrasings and 3/40 with held-out phrasings. Its pressure answers keep the verdict structure
("My philosophy decides this …"), but misread sentences such as "Someone confirmed that url_b really contains what is said about s1"
(`verified`): the pressure set uses held-out phrasings too, so pressure and paraphrase fail at the same step. A world is exact only if
every sentence is read right: with about 12 sentences, 3/40 corresponds to about 0.81 per sentence and 30/40 needs about 0.976 (estimate,
independent errors). Two levers worked: verified LLM paraphrases in training (run 13: 16/40; run 10 vs run 9: formalize 0 → 8/20,
Fisher p = 0.003) and model size (run 16: 16/40 vs 7/40, +12/−3, McNemar p = 0.035; in-distribution 25 vs 29/40, within noise). Both agree with the
literature: paraphrases in training lifted RuleTaker from 66.6 % to 98.8 % on reworded rules [17]; a semantic parser's paraphrase gap
shrinks from 1B to 3B and then plateaus [18], and larger pretrained parsers are more robust [19]. More of the same paraphrases does not
help; diversity of *method* does — several operation types [20], several generators with one held out [21], syntactic reordering
(Kendall τ) rather than lexical change [22], a meaning filter rather than a similarity threshold [23, 20]. Run 19 found the cause — omission — and removed it (§5.11).

### 5.10 GRPO sharpened
GRPO on run 10's adapter (run 14) raised the mean reward from 0.23 to a plateau of 0.34–0.43, with entropy at 0.02 and the share of
groups without signal rising from 16 % to 28 %; on held-out worlds +6/146 (+9/−3, p = 0.15). With 70 % of answers right and four
samples per prompt, 0.7⁴ ≈ 24 % of groups are all-correct and carry no gradient (estimate). RL raises pass@1 towards the base model's
pass@k rather than beyond it [24]; the closest controlled study (Qwen3-4B, LoRA r64, TRL, dapo) used a ten times higher learning rate
and eight samples [25]. Three defects of run 14 were found afterwards: its prompts differed in form from the SFT prompts; the constant
answer "I cannot formalize this situation" earned 0.0 on every prompt, a safe harbour against negative rewards (the rule-based abstention
collapse of [26]); and the generation budget (486 tokens) would cut a facts-first answer. GRPO v2 (run 17) fixes all three and ran out of
memory on the 8 GB card.

### 5.11 Reading was omission, and alignment fixed it
Run 18 added training paraphrases and per-sentence reading and lifted paraphrase verdicts from 3/40 to 24/40 — but the fact list was fully
right in only 11/40 worlds. The dominant error was **omission**: a sentence that matched no known phrasing produced no fact (peer_offers
missed 61 times, foreign 23, verified 21, author 20 in 1,124 gold facts), not a wrong fact (38) and never a syntax error (0). Sampling
did not help: per fact, the union of eight samples covered 93–95 % against 86 % greedy, but the per-fact majority was no better than greedy
(4 vs 3/40 worlds exact) — the errors are systematic, which is what self-consistency cannot fix [37]. A grammar would not have helped
either: format, arity and vocabulary errors were 0, constants absent from the sentence 10 of 184 errors (≈ 5 %, the upper bound of
grammar-constrained decoding, whose gains are large for untrained and small for fine-tuned models [38, 39, 40]).

Run 19 made omission impossible to do silently. The harness numbers the sentences ("[1] … [N]") and the answer writes one line per
sentence, either a fact or "unknown" (sentence-aligned output as in GNER [41] and TANL [42]; coverage as in NMT [43]); about 12 % of the
training sentences are filler labelled *unknown*, so "none of the types" is a trained class (negative instances, UniversalNER [44]); the
eight fact types are defined in the instructions with two rotating example phrasings each (annotation guidelines, GoLLIE [45]); and the
phrasings come from two generator families plus run 10's set, filtered by read-back through a model of another family. Exact fact lists on
held-out phrasings went from 11/40 to 40/40 (+29/−0, p = 4·10⁻⁹), under pressure from 7/30 to 30/30, formalization from 5/20 to 19/20;
verdicts followed (paraphrase 37/40, pressure 25/30). Which of the four changes did the work is not separated (one run); the omission
counts point to the alignment and the unknown class (hypothesis).

### 5.12 The language stage decides which seed forms can be explained
Runs 15 and 18 lost the same three rules in prose: P1 came back as "Count holds…", P4 lost the constant in `grund(S, snapshot, closed)`,
P6 dropped the second rule on `acceptance(S, tentative)`, and P7 turned `unverified(R, S)` into "unverified holds for S and S". The
generator of the language stage drew every head as the first letters in order (S, P, O), never put a constant into a head and never wrote
two rules on one body — exactly the forms the seed uses there. Run 19 added 600 language rows with shuffled head variables, constants in
heads and two or three heads per shared body (the seed's rules excluded by normal form). P1, P4 and P7 became exact (46/46 each), six of
seven blocks are perfect, and the round trip rose from 244 to 296 of 322 worlds; every counterfactual program was followed. The remaining
error (P6: "if acceptance is unresolved, one must report S") again mixes a head with a neighbouring body.

### 5.13 Order and anchors for recitation
Half of run 15's recitation targets shuffled the rules inside a block (permutation augmentation helps *extraction* of knowledge [2]); run 18
recited block P5 with a rule missing and one invented (19/46). Run 19 recited every block in the canonical order with an anchor before each
rule ("P5.1: …"; index labels let a model look items up by label [46]) and gave block rows about 70 % more exposures (under about 100
exposures counts as under-trained [47]): all eleven recitation items 46/46.

### 5.14 Duties are what is left
With the facts right, run 19's remaining wrong worlds are duties, not values: obligatory(ask) missing 11 times and spurious 6 times — it
needs a conjunction, value n *and* peer_offers — and verify/cite attached to the wrong statement 9 times; values and acceptance were wrong
once. Counting had the same shape before the count trace (§5.7). Run 20 adds a **duty trace** between the count and the verdict: statement
by statement, rules in a fixed order, one short line per condition and duty, and for the two conjunctive rules also the near misses ("value
t, peer offers yes → not met, no ask"); every duty it names is checked against the seed's own atoms (600 of 600 random worlds agree).
Step-wise proofs generalize to unseen depth where all-at-once proofs do not (89 % vs 14 % [9]); whether "not met" lines stop a duty from
firing on one conjunct is a hypothesis this run tests. It also adds negative type queries ("which sentences state peer_offers?" → none)
sampled by confusion frequency [44] and drops the type definitions in 20 % of the rows [45].

### 5.15 What the measurement got wrong
- **Evaluation worlds in training.** Runs 5–7 trained on 73 resp. 12 rows that shared a world with their evaluation; run 5 re-scored on
  clean worlds is 20/38, not 22/40. The kit builder asserts zero overlap since run 8, and the product kit drops such rows.
- **The round trip did not see a lost reason.** The verdict compared answers and duties but not whether a `never(...)` rule fires: a
  rebuilt seed without the snapshot reason agreed on 65/65 worlds although the rule fired in 16. Fixed (the violation status is part of
  the verdict); runs 8 and 11 re-scored from 235 and 296 to 220 and 281 of 322. The 74 % control predates the fix.
- **A classifier counted fact lists as prose.** "Recite" answers that were fact lists were first reported as prose.
- **Records.** One report gave run 14 eight samples per prompt; it used four. Corrected in the memory with the evidence.
- **Small sets.** Most sets have 20–40 items; only differences of about 25 points are detectable at p < 0.05 unpaired. From run 15 on,
  160 more worlds; a set of ≥ 1,000 fresh worlds with pass@k is planned (§6).

### 5.16 The duty trace worked; the closed condition is what is left
Run 20's duty trace fixed the duties it was built for (judge 34 → 39/40, tagged 16 → 20/20, duties exact = world exact on every set).
Its three invented certainties have one shape: facts, count and totals right, and then a firm value and an acceptance for a statement
whose view is **not closed**. In the seed a single line is enough for a value — `value(S, f) <= neg(S) & absent_pos(S)` — but
`absent_pos(S) <= closed(S) & ~pos(S)`: without `closed(S)` only conflicting lines give a value (b), one-sided lines give none, and then
no acceptance either. In all three worlds `closed(s1)` is missing, also in the model's own fact list; it gave f or t and an acceptance
anyway. (A first reading of these cases, "two independent lines are needed for true or false", was wrong — that is the rule for
*acceptance*, not for the value; corrected here and in the memory.) The step from totals to value is the only step the model still
does without a written trace. Run 22 should add a **value line** per statement that names the closed condition ("s1: support 0,
opposition 1, closed no → no value"), checked against the seed like the count and duty traces [9].

### 5.17 The value line closed it
Run 22 adds one line per statement after the totals — support yes/no, opposition yes/no, closed yes/no → the value or "no value",
and the acceptance with its reason — checked against the seed's atoms (600 of 600 random worlds agree). On the same worlds as run 20 it
removes the closed-condition errors (invented certainty 3 → 1 of 433) and lifts every verdict set (pooled +18/−5 worlds, p = 0.011;
paraphrase 40/40). The errors left are duties in the largest worlds (18–19 sentences, answers of 2,200–2,900 characters), where small
models are known to learn long traces worst [arXiv 2502.12143]; mixing full traces with shorter ones is the measured remedy there.

### 5.18 Length must be trained, and an index line shows where it stops
Runs 20b, 23 and 24 solved at most 1 of 40 worlds with 4–5 statements; run 27 trained worlds of 1–6 statements and a copied line
"Statements: s1, …, sN" before the count (an index hint [46]) and solved 37/40 of them — and 0/40 with 7–8 statements, although with a
budget of 3,072 tokens every answer was complete and every fact right: the statement line ended at "s1, …, s6 (6)", the longest trained
world, and the values of s7 and s8 were never written. Length generalization is bounded by the lengths seen in training [5, 53]. Run 30
trained worlds of 1–10 statements and 600 language rows with programs of 5–12 rules: 7–8 statements 35/40 and 39/40 in two arms, a
1–10-statement set 38 and 37/40, the statement line reaching the last statement in 118 of 120 answers. Two technical points made it
possible on an 8 GB card. The longest stage-B row has 5,565 tokens. In fp32, transformers asks PyTorch's attention for grouped-query
attention (`enable_gqa`), which only the quadratic math kernel serves — +4.1 GB at 4,096 tokens; repeating the key/value heads before the
call gives the same attention through the efficient kernel (outputs equal to 7·10⁻⁷, gradients to 1.6·10⁻⁶), and vi-mcp's training
runtime does so since 0.69.9. (A first report of "6× faster" from this fix was wrong: on the same card it gives about 1.2×; the rest was
the move to the faster card.)

### 5.19 Thinning the short worlds made the model skip trace lines
Run 30 spread a similar number of rows over 1–10 statements instead of 1–6, so worlds of 1–3 statements lost a factor 1.7 of their rows
(827 against 1,409 statement blocks with a duty check). judge_more — mostly short worlds — fell from 158 to 144/160 (30ag) and 149/160
(30bg; paired against run 27 +2/−11, mid-p 0.013). The mechanism is visible in the answers. Every remaining world error is a duty, never a
value. The duty trace writes a line "sX: foreign …, unreviewed … →" only when one of the two facts holds (§5.14); the training data always
contains it then (1,511 of 1,511 statements in kit 30a), and the model never misreads it (0 of 253) — it **skips** it, always as the
last line of the statement's block. Skips per statement whose own fact list needs the line: run 27 8/123 (7 %) in short worlds; 30ag
45/132 (34 %) in short worlds, 3/50 and 4/71 (6 %) in longer ones. The share of blocks with the line is 20 % in both kits, so not its
frequency but the short worlds' volume changed. A no-training check confirms that the rest of the chain is intact: when the model leaves
a statement's block although its own facts name the statement foreign or unreviewed, the harness writes "sX: foreign" and lets the
model continue freely — of the first 26 of 43 such items of 30ag, 25 became exact (free: 12 of 26), and the forced line reached the
final Duties line each time.
Two levers follow and are in run 31: the short worlds come back at their old volume with the long ones added on top (replay, §5.3), and
the two conditional lines are written for every statement ("foreign no, unreviewed no → not met, no adopt rule"), so that the trace never
has to decide whether a line exists — absence becomes a named case. The second is a hypothesis: studies of trace design find that the
granularity of steps matters for small students [54], but none tests explicit negative steps.

### 5.20 Two runs, the same data, different slips
30ag and 30bg differ only in "(N)" after the statement list. 30bg invented a predicate for the held-out phrasing "Someone confirmed that
doc_b really contains what is said about s1" — `confirmed(doc_b, s1)` instead of `verified(doc_b, s1)`, 19 times; the training data has
0 such phrasings and 0 `confirmed(` atoms in both kits. Scoring each allowed predicate at that slot with the model's own prefix shows that
30bg holds the right mapping, only weakly: `verified` was the runner-up every time, 0.72 nats behind (median), where 30ag chose it with
11–15 nats to spare. Restricting the slot to the vocabulary (grammar-constrained decoding [38]) repaired the fact lists (1 → 16 of 19)
but cost one verdict (15 → 14 of 19): after the forced token the model wrote `author(s1, x)` instead of `line(…, x)` on the next line in
three items — a forced token shifts the greedy path after it (cf. the distortion grammar-constrained decoding causes [55]). The free
answers had treated their invented `confirmed` like `verified` downstream, so their verdicts were right with a wrong atom. 30bg in turn
skips the adopt line far less often (12/133) but skips the *source* line in unclosed one-statement worlds (17/23 unclosed worlds against
23/23 for run 27). Fine-tuning runs of the same recipe agree in distribution and differ widely out of it — 100 BERT fine-tunings within
83.6–84.8 % in distribution ranged from 0 to 66 % on a shifted set [52]. So the format question 30a vs 30b (count or not) is not decided
by this pair; run 30cg (seed 43) measures the noise, and averaging the weights of runs from one initialization (model soups [56]) is
measured as a remedy (the exact average of two LoRA deltas, checked module by module to a relative 8·10⁻⁷).

### 5.21 What still breaks the seed's prose: two duties from one condition
P6 is the block no run explains reliably (run 27 0/46, 30ag 28/46). Its rules include `may(state_as_hypothesis(S))` and
`forbidden(assert_unqualified(S))`, both `<= acceptance(S, tentative)` — two duties from one body; the second is dropped. A matched
diagnostic (40 programs with a shared-head pair and a shared-body duty pair against controls of the same forms) confirms the shape: 30ag
kept same-head pairs 40/40 and dropped the second same-body duty 4/40 (controls 40/40; run 27: 2/40). A first lead — the language stage
merges the transitive-closure pair (two rules with the same head) into one sentence in 10 % of its explain rows — was refuted by the
same diagnostic (same-head pairs are kept). Such duty pairs occur in 33 of 3,080 explain rows (1.1 %). Run 31h9 adds 600 translation
rows with 2–3 duty rules over one body against run 31 without them.

### 5.22 What the measurement got wrong (continued)
- **A held-out set that was not held out at the rule level.** language_long was called "held out", but 98 of its 169 rules occur in
  run 30's training; it measures unseen programs of partly seen rules, and is named so now.
- **A set out of its range.** The "11–12 statement" set judge_x2 had worlds of 1–10 statements, because a patched generator function was
  shared between two builders; the real 11–12 set (x2b) was built again and is answered after run 30cg.
- **The wrong kit counted.** The comparison "kit 30 has 3.4× fewer short-world rows" was taken from an older build of kit 27 with 1–3
  statements only; run 27 trained the consolidated kit (1–6 statements), and the factor is 1.7. Corrected here and in the memory.
- **A slide claimed 6× from the attention fix** (§5.18): corrected to about 1.2× on the same card.

## 6 Open points

1. **Reading unseen phrasings** — solved for this seed's test phrasings by run 19 (§5.11). Still open: the held-out phrasings come from
   one generator; a set written by a third generator family (generated, not yet used) and 50–100 human-written sentences must confirm
   it, together with the minimal-pair set (30 sentences whose type flips with one cue word) that run 19 and 20 are measured on.
2. **Pressure** must be measured separately from reading: a pressure set with *training* phrasings is needed, so the two failures can
   be told apart. Training follows the filtered multi-challenger recipe (only worlds the model already solves; hold vs. update on a real
   new fact) [27, 28].
3. **The whole seed in prose** (17/46 in run 19): generate block by block and concatenate at inference — length generalization is bounded
   by the lengths seen in training, and decomposition into parts is the measured remedy [48]; P6's head/body confusion needs more rows
   with several rules on neighbouring bodies.
4. **GRPO done properly**: on the AMD host (memory), eight samples, LoRA learning rate about 5e-5, only prompts the model solves sometimes
   (dynamic sampling), checkpoints evaluated every 50 steps, pass@k of the SFT model measured first as the ceiling [24, 25, 29].
5. **Error-targeted self-training** before more RL: solver traces for the worlds the model gets wrong, plus trace-verified own samples,
   2–3 rounds, fresh worlds each round [30, 31, 32].
6. **Evaluation**: ≥ 1,000 fresh worlds per set, pass@1 and pass@k, trace-level correctness (right verdict from wrong facts counted as
   wrong), several training seeds per configuration.
7. **Model size**: 1.7B beats 0.6B on the same kit (run 18b: +37/−5 worlds), but not where the data is missing: on kit 20 the 1.7B model reads non-assertions no better than 0.6B (unknown 3/9, 2/25), while 0.6B with contrast twins reaches 8/9, 16/25 (run 20b vs 23: +19/−2) — the negation literature finds the same: scale alone does not fix negation, often worsens it [50, 51]; next the best 0.6B recipe on 1.7B, and a learning-rate sweep for 1.7B (1e-4 to 3e-4; the expected optimum is 0.6–0.95× of the 0.6B rate [33]); the 1.7B arm
   on the same host as its 0.6B control.
8. **The newer seed**: `kollektiv` 1.3.0 (P8–P13: origins not votes, hearsay, camps, untestable, extraordinary claims, withdrawn) is not
   trained yet; all runs here use 1.2.0 so they stay comparable.
9. **Into the product** (the largest open point, 18.11.2026): the recipe that meets the targets — facts first with numbered sentences and
   an unknown class, count trace, value check, duty trace, statement line, contrast twins, the language forms, worlds of 1–10 statements
   with the short ones at full volume — lives in a chain of experiment builders (kit 31 is built from kits 30a, 27c, 26, 20 and two
   trace modules); `vi-mcp finetune kit --philosophy` writes none of it yet. Until it does, nobody but this project can reproduce the
   numbers above.
10. **Duties** (§5.14): done by run 20's duty trace (§5.16); its value step needs a value line naming the closed condition (run 22); then GRPO v3 with a graded reward — F2 of the fact list (an omission costs more than an
   extra fact) plus the verdict reward plus an exact-set bonus — because an exact-set or verdict-only reward leaves most groups without
   gradient at pass@8 = 9/40 [24, 49].

11. **Run 31 and 31h9** (§5.19, §5.21): skip rate of the conditional trace lines in short worlds ≤ run 27's 7 %, judge_more back to
    ≥ 158/160, P6 in prose and the same-body diagnostic ≥ 39/40 — read against run 30cg's seed noise, not item by item.
12. **The trace lines a fact creates** (§5.19–5.20): the source line cannot be made unconditional (one line per source fact); whether the
    replay alone stops its skips is measured separately in run 31.

## 7 Threats to validity

**One training seed per configuration.** All comparisons are paired over items of a single run per arm; the systematic shift of a
whole run from the training seed is not in the p-values. LoRA fine-tuning shows seed standard deviations of about 0.1–5 points on
classification tasks [34, 35] (BERT full fine-tuning up to 6–7 points [36]); no study reports it for a sub-1B decoder with exact match
on generated output, so 1–5 points is an estimate. With one seed per arm, the paired effects of +25 points (run 15 vs 12) and +22.5
points (runs 13 and 16 vs 12) stay significant up to a seed SD of about 3–5 points (estimate, normal approximation). Comparisons from now
on use three seeds per arm and at least 160 items per set; at 3 seeds × 160 items only effects of about 11–16 points are detectable.
Measured since: two seeds of run 22 differ by +5/−5 pooled worlds; the same kit and seed on two GPUs (run 23, RTX 3070 and RTX 3060)
differ by +4/−2 in one set and not at all in the others — hardware adds little. But out of distribution two runs can differ in *what*
they get wrong (§5.20, [52]); a single pair of runs is no evidence for a small format effect.

One seed (`kollektiv` 1.2.0) and one model family; one training seed per configuration; the round trip of runs 8–15 was done by the author,
who knows the seed (mitigated by counterfactual programs and literal translation rules, not removed); runs 12 and 16 ran on different
hosts (both fp32); the held-out phrasings were written by one generator. Literature effect sizes come from other tasks and larger models
and are cited as direction, not as prediction.

## References

1. Kirichenko, Ibrahim, Chaudhuri, Bell. AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions (2025). https://arxiv.org/abs/2506.09038
2. Allen-Zhu, Li. Physics of Language Models, Part 3.1: Knowledge Storage and Extraction (2023). https://arxiv.org/abs/2309.14316
3. Yang et al. Synthetic Continued Pretraining (EntiGraph) (2024). https://arxiv.org/abs/2409.07431
4. Gekhman et al. Does Fine-Tuning LLMs on New Knowledge Encourage Hallucinations? (2024). https://arxiv.org/abs/2405.05904
5. Anil et al. Exploring Length Generalization in Large Language Models (2022). https://arxiv.org/abs/2207.04901
6. Arora et al. Why Exposure Bias Matters (2022). https://arxiv.org/abs/2204.01171
7. Bao, Mensfelt, Witbrock, Stathis. Not What You Meant: Can LLMs Follow a Specified Negation Semantics? (NAF-Bench, 2026). https://arxiv.org/abs/2609.27517
8. Thatikonda et al. Strategies for Improving NL-to-FOL Translation with LLMs (2024). https://arxiv.org/abs/2409.16461
9. Tafjord et al. ProofWriter (2021). https://arxiv.org/abs/2012.13048
10. Creswell et al. Selection-Inference (2022). https://arxiv.org/abs/2205.09712
11. Zhang et al. Counting Ability of LLMs and Impact of Tokenization (2024). https://arxiv.org/abs/2410.19730
12. Lee et al. Teaching Arithmetic to Small Transformers (2023). https://arxiv.org/abs/2307.03381
13. Nye et al. Show Your Work: Scratchpads (2021). https://arxiv.org/abs/2112.00114
14. Berglund et al. The Reversal Curse (2023). https://arxiv.org/abs/2309.12288
15. Golovneva et al. Reverse Training to Nurse the Reversal Curse (2024). https://arxiv.org/abs/2403.13799
16. Guan et al. Deliberative Alignment (2024). https://arxiv.org/abs/2412.16339
17. Clark et al. Transformers as Soft Reasoners over Language (RuleTaker) (2020). https://arxiv.org/abs/2002.05867
18. Li et al. CodeS: Towards Building Open-source Language Models for Text-to-SQL (2024). https://arxiv.org/abs/2402.16347
19. Chang et al. Dr.Spider (2023). https://arxiv.org/abs/2301.08881
20. Saparina, Lapata. Improving Generalization in Semantic Parsing by Increasing Natural Language Variation (2024). https://arxiv.org/abs/2402.08666
21. Larson et al. Iterative Feature Mining for Constraint-Based Data Collection to Increase Data Diversity and Model Robustness (EMNLP 2020). https://aclanthology.org/2020.emnlp-main.650
22. Yin, Wieting, Sil, Neubig. On The Ingredients of an Effective Zero-shot Semantic Parser (ACL 2022). https://arxiv.org/abs/2110.08381
23. Xu et al. AutoQA (2020). https://arxiv.org/abs/2010.04806
24. Yue et al. Does Reinforcement Learning Really Incentivize Reasoning Capacity beyond the Base Model? (2025). https://arxiv.org/abs/2504.13837
25. Chaudhry. Is it RL or Data? A Controlled Comparison of GRPO and Rejection-Sampling Fine-Tuning (2026). https://arxiv.org/abs/2610.25812
26. Wei et al. TruthRL: Incentivizing Truthful LLMs via Reinforcement Learning (2025). https://arxiv.org/abs/2509.25760
27. Wei et al. Simple Synthetic Data Reduces Sycophancy in Large Language Models (2023). https://arxiv.org/abs/2308.03958
28. Laban et al. Are You Sure? Challenging LLMs Leads to Performance Drops in the FlipFlop Experiment (2023). https://arxiv.org/abs/2311.08596
29. Yu et al. DAPO (2025). https://arxiv.org/abs/2503.14476
30. Havrilla et al. Teaching Large Language Models to Reason with Reinforcement Learning (2024). https://arxiv.org/abs/2403.04642
31. Ma et al. Learning What Reinforcement Learning Can't: Interleaved Online Fine-Tuning for Hardest Questions (ReLIFT, ICLR 2026). https://arxiv.org/abs/2506.07527
32. Lee et al. LLM2LLM (2024). https://arxiv.org/abs/2403.15042
33. Thinking Machines Lab. LoRA Without Regret (2025). https://thinkingmachines.ai/blog/lora/ ; exponents in tinker-cookbook `hyperparam_utils.py`
34. Bui, Savova, Wang. Assessing the Macro and Micro Effects of Random Seeds on Fine-Tuning Large Language Models (IJCNLP 2025). https://arxiv.org/abs/2503.07329
35. Bouthillier et al. Accounting for Variance in Machine Learning Benchmarks (2021). https://arxiv.org/abs/2103.03098
36. Dodge et al. Fine-Tuning Pretrained Language Models: Weight Initializations, Data Orders, and Early Stopping (2020). https://arxiv.org/abs/2002.06305
37. Wang et al. Self-Consistency Improves Chain of Thought Reasoning in Language Models (2022). https://arxiv.org/abs/2203.11171
38. Geng, Josifoski, Peyrard, West. Grammar-Constrained Decoding for Structured NLP Tasks without Finetuning (EMNLP 2023). https://arxiv.org/abs/2305.13971
39. Shin et al. Constrained Language Models Yield Few-Shot Semantic Parsers (2021). https://arxiv.org/abs/2104.08768
40. Scholak, Schucher, Bahdanau. PICARD (EMNLP 2021). https://arxiv.org/abs/2109.05093
41. Ding et al. Rethinking Negative Instances for Generative Named Entity Recognition (GNER, 2024). https://arxiv.org/abs/2402.16602
42. Paolini et al. Structured Prediction as Translation between Augmented Natural Languages (TANL, 2021). https://arxiv.org/abs/2101.05779
43. Tu et al. Modeling Coverage for Neural Machine Translation (2016). https://arxiv.org/abs/1601.04811
44. Zhou et al. UniversalNER (2023). https://arxiv.org/abs/2308.03279
45. Sainz et al. GoLLIE: Annotation Guidelines improve Zero-Shot Information-Extraction (2023). https://arxiv.org/abs/2310.03668
46. Zhou et al. What Algorithms can Transformers Learn? (RASP-L, index hints, 2023). https://arxiv.org/abs/2310.16028
47. Allen-Zhu, Li. Physics of Language Models, Part 3.3: Knowledge Capacity Scaling Laws (2024). https://arxiv.org/abs/2404.05405
48. Bai et al. LongWriter (2024). https://arxiv.org/abs/2408.07055
49. Liu et al. ProUIE (2026). https://arxiv.org/abs/2604.10633
50. Truong, Baldwin, Verspoor, Cohn. Language models are not naysayers: an analysis of language models on negation benchmarks (*SEM 2023). https://arxiv.org/abs/2306.08189
51. McKenzie et al. Inverse Scaling: When Bigger Isn't Better (TMLR 2023; NeQA task). https://arxiv.org/abs/2306.09479
*References 52–56 (added 18.11.2026) were checked at abstract level through a web search, not read in full; the numbers quoted from
them are the abstracts' own. Reference 54's title and authors are not verified here.*

52. McCoy, Min, Linzen. BERTs of a Feather Do Not Generalize Together: Large Variability in Generalization across Models with Similar Test Set Performance (BlackboxNLP 2020). https://aclanthology.org/2020.blackboxnlp-1.21
53. Zhou et al. Transformers Can Achieve Length Generalization But Not Robustly (2024). https://arxiv.org/abs/2402.09371
54. Distillation study of chain-of-thought format and step granularity for small students (2025). https://arxiv.org/abs/2502.18001
55. Park, Wang, Berg-Kirkpatrick, Polikarpova, D'Antoni. Grammar-Aligned Decoding (NeurIPS 2024). https://arxiv.org/abs/2405.21047
56. Wortsman et al. Model Soups: Averaging Weights of Multiple Fine-Tuned Models Improves Accuracy without Increasing Inference Time (ICML 2022). https://arxiv.org/abs/2203.05482
