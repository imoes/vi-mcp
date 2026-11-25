# G8d — a candidate-conditioned proposer for the rule search, and which vectors it needs (draft, 19.11.2026)

Review: the Fable review was stopped on the user's instruction ("nein kein fable mehr", 19.11.2026). The plan gets a self-review
(marked as such) against the findings of the earlier reviews (G8c review 1, G10 reviews 1–2) before step 0.

## Why (the evidence chain)
- G8b-1: library wiring does not make the search after the start phase cheaper (ratio 1.10, CI [0.93, 1.24]); library gains were
  lookup (25.7 % vs 10.4 % solved in the start phase); first solutions keep their origin block's rule in 48 % (L) vs 46 % (XR).
- G8c-0: a STATIC per-task operator prior, even an oracle one, saves too little (median U/O 1.40 < 1.5; by edit distance k = 1: 1.20,
  k = 2: 1.24, k = 3: 2.77). Review 1 of G8c (minor 12): a static prior is not DreamCoder's candidate-conditioned guidance.
- G10 reviews: retrieval by vectors is redundant at ~570 rules (a symbolic aligner takes ms); the informative baseline for any VSA key is
  the exact symbolic context kernel it projects; per-rule keys cannot represent helper/closure mechanisms (base + step).
- Synthesis (HYPOTHESIS, insight:1d0eee27): our failures were selection/acceptance failures, not generation failures.
- User question (19.11.2026): real progress needs vectors — an existing embedding model, or our own? Answer to be MEASURED here:
  a text embedding (bge-m3) is ruled out by design (it embeds names; R1 anonymises them). Candidates are computed vectors first
  (behaviour, exact structure, VSA projection), a learned encoder only if those fail to transfer.

## Question
Does choosing the NEXT EDIT (operator and position) from a representation of the CURRENT candidate — its structure and its errors —
reduce the evaluations to an exact solution, and which representation carries the information?

## Binding rules
DESIGN_RULES.md R1 (anonymous identifiers, fresh bijection per task and seed; speaking-name control reported, no claim) and R2.
the workstation: at most 4 processes, each `systemd-run --user --scope -p MemoryMax=… -p MemorySwapMax=0`; big jobs alone.

## Step 0 — instrumentation (no claim)
gp2 records every child: parent canonical key, operator, position (rule index, literal index), whether the edit was EFFECTIVE (canonical
key changed), fitness before/after (FP, FN on the task's worlds), size before/after, generation, evaluation counter. Logging only:
the instrumented gp2 must reproduce the stored G8b-1 runs bit-identically (same RNG draws) — checked on all 330 L runs before use.
Data: the 33 G8b-1 tasks (DEVELOPMENT only) × 10 seeds, arms Z and L; plus the 30 G8c dreams (known edit scripts).

## Representations of a candidate (all name-free, all computed — no trained encoder)
- N  none: the operator/position marginal (what G8c's static prior had).
- W  wiring-blind signature: #rules, #pos, #neg, #!=, recursive, helper count, arities, body lengths.
- S  exact symbolic context kernel: per literal its 1-hop context features (sign, arity, which argument slots share a variable with which
     other literal slots, head-sharing, helper/recursive role), bundled per rule and per program (so base + step helper mechanisms are
     visible — review 2 #8). Edit candidates are scored with features of (candidate, operator, position).
- V  FHRR projection of S (d = 2048, torchhd, 10 codebook seeds fixed in advance): role-filler binding of the same contexts — the user's
     VSA idea, as a lossy compression of S. Kept only if V ≥ S − 0.02 AUC (it must not lose what S has).
- F  behaviour: error signature (FP, FN, share of FN whose derivation needs ≥ 2 chained facts, FP/FN on worlds with vs without the
     head's typical pattern) plus a literal-sensitivity profile computed by the solver: for each body literal, ΔFP/ΔFN when it is
     dropped and when its sign is flipped. This is the "execution trace" embedding of DYPRO/LiGer, but exact and untrained.
- F+S combined.

## G8d-0 — information gate (offline, development data, no search claim)
- Label per logged effective edit: 1 if the child is strictly better on the (FP+FN, size) Pareto order, else 0.
- Model per representation: logistic regression (scikit-learn), task-grouped: leave-one-task-out across the 33 tasks.
- Metrics: AUC of the label; top-3 hit rate (a label-1 edit among the 3 highest-scored edits of a parent); within-task CV beside
  leave-task-out (the gap shows whether a learned encoder would be needed — step 3).
- Gate to G8d-0b: the best of {S, V, F, F+S} beats N and W by ≥ 0.05 AUC (leave-task-out), task-bootstrap 95 % CI of the margin > 0.
  Else stop: the candidate carries no transferable information for the next edit at this scale.

## G8d-0b — ceiling of conditioned proposals (search, development tasks, before any learned proposer)
- Oracle proposer O1: at each mutation it knows which effective edits of the parent improve it (one-step lookahead, free of charge)
  and samples among them; ε = 0.2 uniform floor; identical start sets and evaluation budget as U.
- Gate to G8d-1: median ratio U/O1 on O2 (evaluations to the first exact solution) ≥ 1.5 in the stratum median U O2 ≥ 300.
  Else stop: even a perfect one-step predictor would not pay (the lesson of G8c-0, applied before building).

## G8d-1 — confirmatory (pre-registered after 0 and 0b, hash before any run)
- Tasks: a NEW blind set of ≥ 30 tasks written by a subagent without the library, gp2, the encoders or any result; strata fixed
  beforehand (median U O2 ≥ 300; k-distance to the nearest library block measured as in G8b-1).
- Arms, all with ε = 0.2 uniform floor, identical start sets (start RNG without the arm name), same budget:
  U uniform · P static prior (G8c) · C conditioned (representation chosen in G8d-0, model frozen) · Cs C with the feature→weight
  assignment permuted per seed (same output marginals, no information) · O1 oracle (ceiling, descriptive).
- Primary (one): C vs Cs on O2, unit = task, one-sided Wilcoxon signed rank over task medians of 20 seeds. Secondary: C vs P, C vs U,
  solved rate, lookup vs descendant first solutions, by k-stratum.
- Convincing pattern (fixed now): C < Cs and C < P in the hard stratum, no harm on easy tasks (ratio ≥ 0.9), gain grows with k.

## G8d-2 — our own encoder (only if earned)
Only if G8d-0 shows S or F informative WITHIN tasks but the leave-task-out AUC drops by ≥ 0.10: a small contrastive encoder
(ContraCode-style) over anonymised programs, positives = solver-proven equivalent programs (equivalent_to on the exhaustive domain),
hard negatives = one effective edit away; trained on the RTX 3070; it replaces S/V as input of the same proposer, same G8d-1 arms.

## Not in scope
Retrieval (G10 reviews), library injection, a rule-union operator for gp2 (noted gap, review 2 #5), changes to the fitness.

## Cost (estimate, to be replaced by a smoke measurement)
Instrumented replay of 330 L + 330 Z runs on the workstation at ≤ 4 processes; G8d-0 is minutes of scikit-learn; G8d-0b 33 tasks × 10 seeds × 2 arms.

## Self-review 1 (Claude, 19.11.2026 ~23:00 UTC — a self-review, it counts less than an independent one), against gp2.py
1. A child is crossover (30 %, gp2.py:466) followed by 1–2 mutations (gp2.py:474 randint(1, 2)), so one child's improvement cannot be
   attributed to one edit. Fix: G8d-0 learns only from children with no crossover and exactly one mutation (~35 % of children);
   in G8d-1 the proposer chooses every mutate() call.
2. Proposal unit: gp2 draws the operator and the rule index first (gp2.py:257–258) and the inner choices (literal, variable,
   constant) inside the operator. The proposer chooses (operator, rule index); inner choices stay random in every arm.
3. Fitness is a per-world F1-like score vector (Search.cases, gp2.py:370–386), not FP/FN counts; the cache is cleared on every
   counterexample (gp2.py:426). Labels are therefore computed OFFLINE after the run: parent and child re-evaluated on the run's final
   training worlds (train + all counterexamples) outside the search budget, so logging never adds an evaluation and the replay stays
   bit-identical. Label 1 = child's score sum > parent's, or equal with smaller size. Secondary label: the child is an ancestor of the
   run's first exact solution (covers neutral steps such as invent → recurse, G8c review 1 #3); share of neutral operators reported.
4. Evaluation accounting: F splits into F0 (free: per-world TP/FP/FN of the parent from the same solver call that cases() already
   makes — cases() is extended to keep them) and F1 (literal sensitivity: extra solver calls, COUNTED in the arm's O2). G8d-0 reports
   F0 and F0+F1 separately; G8d-1 uses F1 only if it pays after its cost.
5. Cs control: within each parent, C's scores are permuted over that parent's candidate (operator, rule) pairs — same score
   distribution per decision, no link to the edit. Replaces the feature→weight permutation.
6. N baseline: operator × parent size (rules, body literals) — the trivial predictor that operator identity and size alone give.
7. O1 oracle made finite: per mutate() call it draws up to 24 (operator, rule, inner) realisations, evaluates them offline free of charge
   and takes an improving one if any, else a uniform one. Its evaluations are not counted (ceiling), the O2 of the chosen children is.
8. Duplicates: gp2 drops children already in the next population (gp2.py:477–481); only novel children are logged; children equal to
   the parent after canon are logged as ineffective (label excluded, share reported per operator).
9. Logging must not touch the RNG: mutate() is copied into gp2_log.py with identical RNG calls plus the returned rule index; the
   bit-identical replay of stored runs is the test of the copy.

## Self-review 2 (Claude, 20.11.2026 ~00:30 CET) — the gate is decided WITHIN the parent; frozen before the full data
Pilot on the 12 replayed runs (9 tasks, 1,237 clean records, 98 positives; NOT a measurement): pooled leave-task-out AUC N 0.589,
W 0.458, S 0.518, F0 0.750, SF 0.734. The pooled AUC mixes in parent headroom — a bad parent is easy to improve whatever the edit —
which tells a proposer nothing, because it always chooses among the edits of ONE parent. Fix, frozen now (g8d0.py, sha256 below):
- Primary metric: AUC WITHIN parent = over all (improving, non-improving) pairs of edits of the same parent (grouped AUC); pooled AUC
  reported, not used for the gate.
- Gate G8d-0 → G8d-0b: within-parent margin best-of(S, F0, SF) − max(N, W) ≥ 0.05 and task-bootstrap 95 % CI lower bound > 0 (1,000
  draws, a task drawn twice is two independent copies), on edits0 (33 tasks × 10 seeds × Z, L), leave-one-task-out,
  HistGradientBoostingClassifier(max_iter=200, random_state=0), scikit-learn 1.9.1 on a second CPU host (CPU, own venv).
- Pilot within-parent (43 parents with both labels, 1,116 pairs): N 0.602, W 0.578, S 0.643, F0 0.694, SF 0.664; margin 0.092,
  CI [−0.032, 0.216] — too little data to decide, as expected.
- Representation hashing is deterministic (crc32), not Python's per-process hash().

## Amendment 1 (20.11.2026 ~06:30 CET) — computation only, metric and gate unchanged
The full G8d-0 run on a second CPU host grew to 22.5 GB (five feature dicts per record) when run 34 started training on the same host; it
was stopped before any result existed. g8d0.py now keeps per record only (ops, parent text, parent score) and computes each
representation's features when that representation is fitted. Check: frozen v1 (g8d0_frozen_v1.py, sha256 07bd6ea7…) and the new
version give byte-identical result JSON on the pilot (replay, 12 runs), on the workstation with scikit-learn 1.9.1, numpy 2.5.5, Python 3.12.3
(the same versions as a second CPU host; the pilot numbers equal those from a second CPU host). Full run on the workstation: OMP_NUM_THREADS=4, MemoryMax 20G.
New hash: 36c0f58db7f02f80…

## Amendment 2 (20.11.2026 ~08:50 CET) — before any result: cap per run, exact rank-based within-parent AUC
The full run (amendment 1) reached 16 GB and would not have finished: edits0 holds 1,116,961 clean records, median 73 per run but
58,906 in one run (the 5 largest runs hold 16 %), and the pairwise within-parent AUC is quadratic per parent inside a 1,000-draw
bootstrap. It was stopped in the model phase; no result existed. Changes:
- at most CAP = 300 clean records per run, sampled with random.Random("cap:<run>") before scoring: every run counts about equally
  (the unit is the task), 84,100 records in total. The pilot (max 178 per run) is unaffected.
- grouped AUC by Mann-Whitney midranks per parent: the same number as counting all pairs. Check: pilot without cap byte-identical
  to amendment 1's pilot result.
Gate, representations, model, leave-one-task-out and bootstrap unchanged. Hash: 5dcf25dbd3fa5fda…

## G8d-0 result (20.11.2026 ~09:45 UTC): PASS
Within-parent AUC N 0.632, W 0.704, S 0.720, F0 0.746, SF 0.770; margin +0.0657, task-bootstrap CI [0.0173, 0.1148] (31 tasks with
records, 83,733 edits, 5,260 improving, 1,991 parents with both outcomes). VI insight:7c0b2189.

## G8d-0b specification, fixed before its runs (20.11.2026 ~10:00 UTC)
- Hard stratum = the 12 development tasks whose median U search cost (stored runs1 Z, bit-identical to U) is ≥ 300:
  bank_fraud, games_levels, games_rps, garden_crowded, garden_irrigation, hospital_exposure, kitchen_vegetarian, logistics_served,
  office_top_manager, school_eligible, sports_ranking, sports_results. U = the stored runs1 Z results (no rerun).
- O1 = gp2_arms.py --policy O1, arm Z, seeds 0–9, budget 15,000 (the oracle's free evaluations are not counted, by design).
- Cost per run = search_cost (evaluations after the start phase to the first exact solution); unsolved within the budget = 15,000
  (censored; this UNDER-states ratios where U fails and O1 succeeds).
- Gate to G8d-1: median over the 12 tasks of (median U cost / median O1 cost) ≥ 1.5. Reported too: per task ratios, solved counts.
- Compute: a second CPU host CPU, 6 parallel, MemoryMax 4G each, beside run 34 (GPU).
