# PREREG kit36: member-cue contrast rows and P7 counterfactual blocks on top of kit35 (goal Z4)

Date: 25.11.2026. Frozen with the sha256 in `PREREG_kit36.sha256` **before any kit36 row is generated**. All times are UTC from
`date -u`. Decision: the user, relayed by the coordinator at 08:48:36 UTC ("Step 0 + kit36"). GPU: the RTX 3070 host on 26.11.2026,
seed 42 from about 09:30 and seed 43 from about 15:15. Every run ends by 21:00.

## Why

- **Run 35** (kit35 = kit34 + 600 synonym rows) taught copying the prompt's name (H-K1, 42 vs 32 of 64). It left two errors:
  - **P7 stays at 5/8 on p67ablate.** The three failing variants rename one member of the definitional pair verified/unverified,
    or rename both with diagnostic names, and the model writes the seed's pair. kit34 already carried 300 rows coupling the P6/P7
    vocabulary at random; P7 did not move.
  - **The held-out sentence "Speaking for claim sN: member X, source O."** is read as `author(sN, X)` when X is sN's author: run 35
    101/110 against run 34 110/110 (FINETUNING_PAPER §5.34, exploratory). The cue word "member" marks `author` 3,112 times and `line`
    1,312 times in kit34's training text.
- **Step 0** (PREREG_kit35_S43, vi-mcp-sr 5480e1f) runs today and decides whether that error belongs to kit35 or to seed 42. This
  registration is written before step 0's result. Its reading is fixed for both outcomes (below).
- **Sources read in full text for this design (25.11.2026):**
  - Kaushik, Hovy, Lipton 2020 (arXiv 1909.12434), Table 5: original and minimally revised data together cost about 1.7 points
    in-domain for BERT (88.5 vs 90.2) and gain about 9 on the revised side (95.1 vs 86.1). Table 6: the same combination gains out
    of domain. Both sides of a pair must be in training.
  - Gardner et al. 2020 (arXiv 2004.02709): contrast sets and a consistency score.
  - Wu, Geiger, Millière 2025 (arXiv 2505.20896): early heuristics persist under the general binding mechanism (§3.2). The data
    must make the shortcut unprofitable (§2.1, App. D).
  - arXiv 2510.03178: in code, misleading names are not worse than neutral renaming; ambiguous ones are the worst (Table 3).
  - Our own §5.26: kit33c's coupling rows fixed P5 (46/46) but broke P6 (0/46) and P7 (15/46). Hence the no-harm rule on every seed
    block below.

## The kit (`research/philosophy/kit36/build_kit36.py`, sha256 in the .sha256 file)

kit36 = the rebuilt kit35 (stage A sha256 da1da2af…, identical to run 35's training data) plus two row groups.

- **A — member-cue contrast, 300 rows in stage B (row seed 3612).**
  - Each row is an existing kit35 judge or pressure row from a self-supporting world, meaning X is sN's author and gives a line on sN.
  - In it, the author sentence is rewritten with a new "member" author template and the self line sentence with a new "member" line
    template, so the cue "member" sits on both sides of the decision in one situation.
  - The assistant target stays unchanged, because the facts are the same. The original row stays in the kit.
  - Templates M (author): "Member {1} made statement {0}." · "Statement {0} is by member {1}." · "Member {1} is the one who stated {0}."
  - Templates M (line): "Member {3} gives evidence {w1} statement {0}, drawn from origin {2}." · "Member {3} argues {w1} {0}; the origin
    is {2}." · "On {0}, member {3} testifies {w1} it, citing origin {2}."
  - **The held-out test template** `RENDER_TEST["line"]` = "Speaking {w1} claim {0}: member {3}, source {2}." **and its generator are
    never used.** The builder asserts that no M template contains "Speaking" or the colon pattern "claim {0}:". It also asserts that
    no group-A situation occurs in any eval file.
- **B — P7 counterfactual blocks, 300 rows in stage A (150 explain, 150 write; row seed 3613).**
  - Each row is the P7 block with the seed's own names, with exactly one rule changed by one minimal edit. Ten edits exist:
    - drop or add the negation of verified;
    - swap the arguments of verified or unverified;
    - replace `source` by `counts` in a body;
    - flip obligatory and forbidden.
  - Self-referential rules are excluded.
  - Half of the rows show a shortened block.
  - The prose is `rule_prose.program` of the edited code (kit35's translator, committed in bfe3ce0), so the target follows the
    edited rule, not the remembered seed.
  - No edited rule equals a seed rule or any rule in an eval file (the EVAL_FORBIDDEN set, built as in kit35).
- **Training:** exactly as run 35 and step 0: LoRA rank 64, fp32, learning rate 2e-4 in both stages, 2 epochs, batch 1. Two runs, with
  training seeds 42 and 43.

## Answers and scorer

- **Each kit36 run answers:**
  - `eval_k36.jsonl`: the kit's eval items of judge_same (40), judge_paraphrase (40), pressure_heldout (30), formalize_heldout (20) and
    explain_seed_part (7), 137 items in all;
  - `p67ablate.jsonl` (16);
  - `syn_ho.jsonl` (64).
  - All with `phil_answers_file.py out/logic`, greedy with thinking off and the kit's frozen budget.
- **Scorer:** `research/philosophy/kit36/score_k36.py` (sha256 in the .sha256 file).
  - It uses only committed code: `clingo_object.philosophy_train.parse_verdict`/`score`, kit35's `score_syn.correct`, and
    `rule_prose`.
  - It replaces the lost `score_run30.py`.
  - Before this registration it reproduced the published run 34 / run 35 numbers exactly:
    - worlds judge_same 40/40 / 40/40, paraphrase 39 / 36, pressure 29 / 29;
    - facts formalize 20 / 17, pressure 29 / 23, paraphrase 40 / 39;
    - "Speaking for"/self 110 / 101;
    - p67ablate P6 6 / 7 and P7 5 / 5 (11/16 and 12/16);
    - SYN-HO 32 / 42.
  - New and deterministic: `seed_blocks_literal`, where a seed block's prose equals `rule_prose.program(block)`: run 34 6/7, run 35
    5/7.

## Hypotheses (each must hold in BOTH kit36 seeds; point criteria)

- **H-36a (primary):** "Speaking for"/self ≥ 109/110 **and** pressure_heldout facts ≥ 29/30.
- **H-36b:** p67ablate P7 ≥ 7/8.
- **No harm**, with the tolerance of two items taken from the measured seed noise (run 22 seeds: +5/−5 pooled over 5 sets, §7):
  - worlds judge_same ≥ 38/40, judge_paraphrase ≥ 34/40 and pressure_heldout ≥ 27/30;
  - formalize facts ≥ 18/20, which is also the 15.11 target of 80 %;
  - invented certainty 0 in every set;
  - seed_blocks_literal ≥ 5/7 and p67ablate P6 ≥ 6/8;
  - SYN-HO ≥ 39/64 (run 35's 42 minus 3).
- **Descriptive:**
  - the per-seed values against run 35 (seed 42) and step 0 (seed 43);
  - the pooled paired comparison of kit36 (2 seeds × 110) against kit35 (2 seeds × 110) on "Speaking for"/self, with an exact
    one-sided sign test;
  - per-variant p67ablate.

**Reading, fixed before step 0's result:**
- **Step 0 replicates the error** (seed 43 ≤ 105/110): H-36a tests whether contrast rows repair a kit effect.
- **Step 0 does not replicate it** (≥ 109/110): H-36a can still hold, but it cannot show that group A repaired anything. It is then
  reported as "no kit effect to repair". Only H-36b and no-harm carry the decision.
- **Step 0 is undecided** (106–108): the same as the previous case, stated as undecided.

**Decision:** H-36b and no harm → kit36 is the base of the next Z4 run, and group B goes into the kit generator. H-36a decides group A
in the same way. A group whose hypothesis fails is not carried forward, and the paper reports it.

## Limits

- Two training seeds, not three.
- The answer set is a subset of the no-harm catalogue: judge_more, package_worlds, language and recite are not answered, so the runs
  fit the slots.
- Group A's templates are written by the author of this registration. They are a third phrasing family, but one person's.
- Group B uses the seed's own names in edited rules, which could teach the model a wrong P7. The no-harm rule on seed blocks and the
  P7 originals in p67ablate guard against it.
