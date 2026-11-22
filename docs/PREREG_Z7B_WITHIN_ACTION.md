# Pre-registration Z7b — which shown hint does the agent use? (within-action test)

Written 2026-11-22 before the script below ran on any data. Follows docs/PREREG_Z7_HINT_UTILITY.md, whose formal pass turned out to be
a label-source artefact (pooled labels from three sources; a source-only predictor reached AUC 0.787). This test uses **one labeller
with both classes at the same moment**.

## Unit and label

An action whose agent reported `vi_after(used=[…])` (data key `used`) and whose `before.shown` holds ≥ 2 hints (answer objects
excluded), at least one of them in `used` and at least one not. Label per shown hint: in `used` → 1, else 0 ("not reported as used").
Counted before this pre-registration: 299 such actions, 447 positive / 639 negative hints, 12.–22.11.2026.

Known limits: "not reported as used" is weaker than "not used"; only actions with at least one used hint carry the field (the
comparison is therefore *which* hint, never *whether* any); the order of the shown list may itself cause use (position bias) — so the
live order is a baseline, and no model gets the position as a feature.

## Split

Temporal by the action's `ts`: train = the first 70 % of the actions, holdout = the rest. Inner validation = the last 25 % of the
training actions (chronological).

## Rankers (scores within one action; higher = ranked first)

- **R0 random:** every pair counts 0.5 (the analytic expectation; no draw).
- **A1 live order:** −position in `before.shown`.
- **A2 bandit replica:** the outcome-advantage posterior mean of `bandit.py` from training-period experiences (as in Z7, A2).
- **B' per-hint use rate:** Beta posterior of "used when shown in a labelled action" from training actions, prior mean m = training
  positive rate, strength s ∈ {1, 2, 5, 10} by inner-validation log loss.
- **C' pairwise logistic (Bradley–Terry / conditional-logit form):** for every positive/negative pair of one action, the difference of
  the two hints' features (hint id, hint kind, `age:new`, hint kind × tool of the action), no intercept, mirrored pairs added so both
  classes exist; L2 strength C ∈ {0.03, 0.1, 0.3, 1, 3} by inner-validation pairwise accuracy.

## Metrics on the holdout

- **Primary: within-action pairwise accuracy** = over all (positive, negative) pairs of the same action, the share where the
  positive scores higher (ties 0.5); equals the within-action AUC. 95 % CI by bootstrap over actions, 2,000 resamples, seed 22112026.
- Secondary: top-1 hit rate (the first-ranked hint is used; ties broken by live order) vs its random expectation (mean share of used
  hints per action); coverage = share of holdout pairs where both hints occur in the training actions.

## Hypotheses and decisions

- **H1:** the chosen model (B' or C', by inner-validation pairwise accuracy; ties → B') has a holdout pairwise accuracy above 0.5,
  CI lower bound > 0.5.
- **H2:** the chosen model beats A1 (paired bootstrap difference, CI lower bound > 0).
- **H3 (descriptive):** A2 (production ranking signal) vs 0.5 and vs A1.
- **H4 (descriptive):** pairwise accuracy ≥ 0.65 — the Z7 criterion as proposed on 22.11.2026 ("hint-label AUC ≥ 0.65 on a temporal
  holdout on a single-labeller label with both classes"), pending the user's confirmation.

If H1 fails, the hint identity does not predict use beyond chance at this volume, and the next step is labels, not models. If H1 holds
and H2 fails, the live order already captures it (or position bias does — not separable offline; an online test with a randomised
order would separate it).

## Known facts carried over

Randomised hold-back: total effect of hints on action success +0.1 ± 1.0 points (stratified; raw −3.7 was Simpson's paradox).
`before.warning` imbalance 0.099 vs 0.025 between the hold-back arms (open). Explicit agent feedback (`feedback`) came almost only
from one automated client and stopped on 16.11.2026 09:47 UTC — very likely because 0.67.0 made the keys inside the `vi_before`
response English (`zugriff.gezeigt` → `zugriff.shown`) and that client reads the German key (not yet verified in its code).

## Results (run 2026-11-22 11:05 UTC on commit 140030d, unchanged script)

299 actions (all from one instance), cutoff 2026-11-19T10:45; train 209 actions / 598 pairs, holdout 90 actions / 253 pairs
(138 used / 181 not used); coverage: both hints of a holdout pair seen in training 74.7 %.

| ranker | holdout pairwise accuracy (= within-action AUC) | 95 % CI (bootstrap over actions) | Δ vs A1, 95 % CI | top-1 hit (random 0.438) |
|---|---|---|---|---|
| R0 random | 0.500 | — | — | 0.438 (expected) |
| A1 live order | 0.518 | 0.439–0.601 | — | 0.400 |
| A2 bandit replica | 0.512 | 0.437–0.587 | −0.107 … +0.093 | 0.456 |
| B' per-hint use rate (s = 5) | 0.840 | 0.780–0.896 | +0.218 … +0.422 | 0.789 |
| C' pairwise logistic (C = 3) | 0.820 | 0.760–0.873 | +0.194 … +0.411 | 0.744 |

Chosen on the inner validation: C' (0.845 vs B' 0.775). **H1 holds** (0.820, CI low 0.760 > 0.5), **H2 holds** (+0.302, CI low
+0.194), **H3:** the production ranking signal (bandit) is at chance for this label (0.512), as is the live order (0.518) —
position bias is weak here (used share by position 0.39 / 0.45 / 0.43 / 0.36). **H4:** 0.820 ≥ 0.65.

### Post-hoc checks (not pre-registered)

- Bootstrap over **conversations** (18 in the holdout, up to 39 actions each): B' 0.757–0.870; B' − A1 +0.110 … +0.411.
- 89 of 90 holdout actions come from conversations with no training action (one conversation spans the cutoff): B' 0.838 there.
- Hint kind alone (Beta per kind) reaches 0.698: solution skills are reported used in 275/463 shows, insights in 34/304. The hint
  identity adds about 0.14 on top. Whether "skills are used more" is real use or a reporting habit of the one instance is not
  separable from this label.
- Limits: one instance, 18 holdout conversations, labels by the same agent family that reads the hints.
