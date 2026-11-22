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

## Correction (22.11.2026 ~11:35 UTC) — what the label really is

The label above was described as the agent's own report `vi_after(used=[…])`. That is **wrong**. The data key `used` is the stored
English name (0.67.0, `names.py`) of `genutzt`, written by `intuition.adopted()` (0.59.0): a shown hint counts as adopted when a
distinctive token of it (path, option, file name with a known extension; `intuition.distinctive_tokens`) that was absent from the
action it was shown before appears in one of the next `ADOPT_WINDOW` = 3 actions of the conversation that succeeds. The agent's own
report lands in `data.declared` (`intuition.declare_used`), which does not occur in the production copy. The label is therefore one
fixed mechanism with both classes within an action (the within-action design holds), but a heuristic of reuse, not a report of use.
Found by the session that works on the feedback hook (question about `data.used` vs `data.declared`), confirmed in
`vi_mcp/intuition.py:725` (`adopted`) and `vi_mcp/names.py:628`.

## Amendment — label validity check (written before it ran)

**Question:** does "adopted" measure that the agent used a hint, or only that the hint's tokens are common in the conversation's work?
**Placebo:** hints held back by the random hold-back (`before.held_back`; the agent never saw them). The same adoption rule applied
to them can only fire by coincidence.
**Procedure** (`scripts/z7b_label_placebo.py`): per conversation, actions in time order; for every action with shown hints (shown arm)
or held-back hints (placebo arm), a hint is adopted when one of its distinctive tokens (text + first 4,000 characters of content, the
rule of `intuition._hint_tokens`) is absent from that action's arguments and present in the arguments of one of the next 3 actions of
the same conversation that succeeded. Rate = adopted (action, hint) pairs / all pairs, per arm. Replica check: in the shown arm, the
agreement of the recomputed label with the stored `data.used`.
**Decision:** risk ratio shown / placebo with a 95 % bootstrap CI over conversations (2,000, seed 22112026). If the lower bound is
above 1, adoption carries a causal use signal and Z7b stands as a measure of *which hint is used*. If the CI includes 1, the label
measures token commonness, Z7b ranks hints by how common their tokens are, and the use-rate arm must not go online on this label —
only on declared labels (`data.declared`, the feedback hook).

## Result of the label validity check (run 2026-11-22 11:32 UTC on commit 0e20f71, unchanged script)

2,574 conversations. Shown arm (actions eligible for the hold-back): 584 adopted of 12,725 (hint, action) pairs, 4.59 %. Placebo arm
(held back, never seen): 149 of 2,567, 5.80 %. Risk ratio 0.79, 95 % CI 0.62–1.03 → **decision: token commonness**. The replica of the
rule agrees with the stored `data.used` (582 both, 2 replica only, 15 stored only). Not stratified by hold probability (pre-registered
unstratified); the lower bound is far from exceeding 1. **Z7b therefore does not show which hint is used**; its 0.84 ranks how
common a hint's tokens are in the work that follows.

## Production finding and proposed change (not applied — the user decides)

`scorer.label` (vi_mcp/scorer.py:317) gives a shown hint the label 1 with weight `WEIGHT["genutzt"]` = 1.5 whenever it is in
`data.used` — before the judge, the conversation grade and the ok tag. This label feeds the router, the bandit and the metrics.
On the production copy 22.11.2026: 607 of 27,508 shown pairs (2.2 %) take their label from it (3 more are overridden by direct
feedback); 19 of them sit on failed actions, where it turns the label from 0 into 1; 73 % of them fall on 10 solution skills
(52 distinct hints) — exactly the hints whose tokens (paths, commands) recur in the following work anyway.
**Proposal:** stop using `genutzt` as a label until it passes a placebo check — in `scorer.label` skip the `data.used` branch (the pair
falls through to judge / grade / ok), or set `WEIGHT["genutzt"]` to 0; keep recording `data.used` for measurement. Check after the
change: bandit counters of the 10 skills fall back toward their outcome advantage; the router's holdout metrics reported side by side.
