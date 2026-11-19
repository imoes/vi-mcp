# Pre-registration G8b-1 (version 2, after review 1 by Claude Fable) — does a library of mechanisms from another purpose help
# symbolic regression over rules, and through which path: lookup at the start, or a better starting point for the search?

Version 2 of 2026-11-19, with the fixes of review 2 (Claude Fable: 'freeze after the listed fixes'). Review 1 found the draft unfreezable (shape not canonical, nearness confounded with kind, unequal start phase,
X crashing and mostly dead, cost censored by wall clock, test underpowered). This version answers each point; it is frozen
(sha256 + VI record) only after review 2. This is a PILOT on 33 tasks; inference is to these tasks.

## Material (hashed at the freeze)
- blind_tasks/blind_tasks.py — 33 everyday tasks written by a subagent that did not read the library (report saved as
  blind_tasks/AUTHOR_REPORT.md); kinds a/b/c 11/11/11; exhaustive verify worlds; stress worlds with unseen values where applicable.
- gp2.py — the G8b-0 search with: stop on evaluations only, AFTER_SOLVE = 0 for these cost runs, the first solution written at once,
  solver timeout 10 s, lineage (every program carries the origin of its start candidate), deduplicated refill.
- arms2.py — the start sources L, XR, XL, Z (below); K = 200 distinct non-empty start programs per arm (at most 20,000 draws; the
  distinct count is reported — Z's random space is small on easy tasks and may stay below K).
- near.py / nearness.json — renaming-invariant nearness (self-test: 0 failures over 99 renamings), DESCRIPTIVE only.

## Arms (only the start source differs; all re-seeded per task, arm and seed)
- L: library mechanisms mapped onto the task vocabulary (helpers renamed inv1.., library constants -> fresh variables, fixed projection
  per (predicate, arity), rules with nested terms excluded).
- XR: library REWIRED — per rule the variable occurrences are permuted across the variable slots (same predicates, signs, lengths,
  variable multiset); rejected if unsafe, if an atom gains a repeated variable, X != X, or canonically equal to the original. Rules with
  no admissible rewiring (42 of 113, mostly one-variable rules that carry no wiring) stay unchanged and are counted per run.
  Re-smoke start table (seed 99): L vs XR mean rules 1.69/1.67, 1.45/1.47, 1.39/1.39; size 5.76/5.82, 5.00/4.96, 4.99/5.11; share
  recursive 0.113/0.100, 0.100/0.095, 0.110/0.065; repeated-variable share 4.6/3.5 %, 1.5/2.0 %, 2.0/1.5 % (bank_fraud,
  hospital_triage, library_overdue).
- XL: library RELINKED — rules intact, references to block helpers redirected to heads of other blocks: destroys the wiring between rules.
  Limits: self-recursion is exempt (a closure with its base rule survives intact); with an empty pool a literal stays linked; XL
  chunks carry fewer rules (1.24–1.48 vs L 1.39–1.69).
- Z: random rules.
- A start-phase table per arm (distinct programs, mean rules, mean size, share recursive, share with a helper) is reported; L and XR
  are expected comparable on it (smoke, library_overdue: rules 1.36 vs 1.29, size 5.01 vs 4.79).

## Outcomes and tests (wording of review 2, adopted verbatim in substance)
Runs: 33 tasks x 4 arms x seeds 0–9 = 1,320, 12 in parallel, in SEED BLOCKS (all 132 task x arm runs of seed 0, then seed 1, ...);
only complete seed blocks are analysed. Every run is wrapped in `timeout 10800`; a run hitting it is a setup failure (reported), not
"unsolved". Per run: none_evals and timeouts (solver returned no answer / hit the 10 s limit) are recorded.
- O2 = evaluations after the start phase until the first verified solution, with a search budget of 15,000 evaluations after the start
  phase in every arm (search.budget = start_evals + 15,000). A run is censored if it has no verified solution within that budget; all
  censored runs get the same value, 15,001; a solution recorded with O2 > 15,000 is censored. O2 is undefined if first_in_start.
- OT (total cost) = evaluations from the first start candidate to the first verified solution, censored at start_evals + 15,001.
  Defined for every run.
- H1 (search path): L vs XR on O2 over the pairs (task, seed) in which neither arm has first_in_start. Excluded pairs are counted per
  task and arm and reported. Within each task the retained L and XR values are pooled and given midranks; d = rank(XR) − rank(L) per
  pair; statistic S = sum over tasks of the mean d of the task's retained pairs; a task with no retained pair contributes 0. Reference
  distribution: 10,000 Monte Carlo sign flips of the pairs (RNG seed 20261119), p = (1 + #{|S*| >= |S|}) / 10,001, two-sided. H1 is
  "not testable" if fewer than 10 tasks have at least 3 retained pairs that are not censored in both arms.
- H2 (lookup): the same test on first_in_start (1/0), all pairs.
- H3 (total): the same test on OT, all pairs. Holm over H1, H2, H3.
- Effect for H1 and H3: per task, the ratio of the XR median to the L median (censored = 15,001); tasks with both medians censored are
  excluded and counted; reported as the median over tasks of the log ratio with a task bootstrap 95 % interval.
- Trivial: a task is trivial iff arm Z has first_in_start in at least 8 of its 10 seeds (determined from Z runs alone). H1–H3 are
  computed on the non-trivial tasks; the same statistics are reported for the trivial stratum and for all 33 tasks, without a claim.
- Secondary (no claim): L vs XL, L vs Z on O1/OT (Z may stay below K distinct start programs on small vocabularies, so L vs Z on O2
  is not like for like — use OT there); per kind a/b/c; nearness as a descriptive covariate.
- Smallest effect of interest: a median cost ratio of 1.5. If the interval excludes ratios >= 1.5 in L's favour the result is "not
  supported"; a non-significant test alone is not a refutation.

## Provenance (S8)
- Every solution's origin follows its lineage (gp2.origin; immigrants are labelled "immigrant"). The origin share is ~100 % by
  construction and is NOT evidence. Reported: the share of L solutions with a rule matching (near.matches, bodies >= 2 literals) a rule
  of its origin block; base rates: the same share for XR/XL solutions against their UNSCRAMBLED origin block, and for L solutions
  against a random other block.

## Named limits
- 33 tasks, one search algorithm, one library; random (sampled) mapping, not exhaustive.
- Nearness is not a usable predictor (strict key: 7/33 near; mapping-faithful key: 26/33 near) — the library holds generic templates
  for most everyday rules; a library effect may therefore show only on tasks whose solution needs a multi-rule mechanism (recursion,
  helper under negation).
- Smoke (seed 99, not part of the test): family_ancestor solved by lookup in L and XL, by search in XR (1,961) and Z (540);
  library_overdue solved by enumeration in Z, by search in L/XL/XR (179/148/86).
