# Pre-registration Z7 — hint utility from hint-level labels

Written 2026-11-22 before any model below was fitted or scored on the holdout. Committed on branch `z7-router` before the run;
the analysis script is committed with it and is not changed after the first holdout number exists (a fix that becomes necessary is
recorded as an amendment with its reason, and the pre-amendment number is reported too).

## Question

Can the VI rank hints by how useful they are? Goal Z7 of the goal catalogue asks for "router AUC ≥ 0.65 and a measured hint
lift". This test decides which signal can carry that goal.

## Known facts (measured before this pre-registration, same data)

1. **The action-success label carries no measurable hint effect.** `intuition.before` holds back all hints of an eligible action
   with probability `HOLD_BACK` (logged as `before.hold_probability`, `before.held_back`). On 3,932 labelled eligible actions
   (13.–22.11.2026) the raw difference is shown 0.892 vs held 0.929 ok (−3.7 ± 1.15 points, SE) — Simpson's paradox: the hold
   probability changed from 0.05 to 0.2 on 16.11 while the base rate drifted. Stratified by period: +0.1 ± 1.1; by day × instance ×
   tool: −0.0 ± 1.0 points. An AUC on ok / not ok therefore measures how hard a situation is, not what a hint is worth.
2. **Covariate balance** of the hold-back arms holds for triggers (4.42 vs 4.40), candidates (11.6 vs 11.2) and selected hints
   (3.50 vs 3.48) but **not for `before.warning`** (0.099 shown vs 0.025 held). Hypothesis, not yet checked: a recording artefact
   (the code says the warning stays when hints are held back). It does not enter this test; it is reported as open.
3. **Hint-level labels are scarce.** 1,380 of 27,508 shown (action, hint) pairs carry a label of their own (5.0 %): 846 positive,
   534 negative, 241 distinct hints, 59 with ≥ 5 labels; 221 labelled pairs have a logged offer probability < 1.
4. Production already logs offer probabilities (`before.offer`, since 12.11.2026), has an ε slot and trains the outcome router
   with inverse-propensity weights (`learning.weighted_observations(ips_out=…)`, 0.62.0). The production ranking is the bandit
   (`before.router == "bandit"`): Thompson sampling per hint on the outcome advantage over the instance/tool base rate.

## Data

A read-only copy of a production database (22.11.2026). Experiences with `mode = 'active'`, ordered by `ts`.

**Unit:** a (experience, hint) pair with the hint in `before.shown` and a hint-level label.

**Label** (one per pair, in this precedence — the agent's own word first, the judge last):
1. `data.feedback[hint]`: +1 → 1, −1 → 0;
2. hint in `data.used` → 1;
3. `data.judge.hints[hint]`: `used` → 1, `not_used` / `misleading` → 0.

**Split:** temporal. The cutoff is the `ts` of the pair at the 70th percentile of all labelled pairs; train = before the cutoff,
holdout = at or after it. Inner validation for any hyper-parameter = the last 25 % of the training part (chronological). The
label-source mix (feedback / used / judge) per part is reported, since the judge started later than feedback.

## Models (all fitted on the training part only)

- **A1 — live order.** Rank of the hint in `before.shown` (first = best); score = −position. No fitting; the policy that ran.
- **A2 — bandit replica.** Per hint, the outcome advantage counters of `bandit.py` recomputed from training-part experiences only
  (success → a += 1 − p, failure → b += p; p = the instance × tool success rate without hints, ≥ 10 actions, else tool, else all);
  score = posterior mean (1 + a) / (2 + a + b).
- **A3 — outcome-router replica.** Logistic regression (`class_weight="balanced"`, C = 0.3) on the ok label of training-part
  pairs with the router's features (`action_features` + `hint_features` without content groups), IPS weights from
  `before.offer` clipped at 10. Approximation of production: no `scorer.label` weights, C fixed. Score = P(ok).
- **B — per-hint Beta posterior on hint labels.** Prior Beta(m·s, (1−m)·s) with m = training positive rate, s chosen from
  {1, 2, 5, 10} on the inner validation by log loss; score = posterior mean; an unseen hint gets m.
- **C — hint-label logistic regression.** Same features as A3, target = hint label, C from {0.03, 0.1, 0.3, 1, 3} on inner
  validation by log loss; two variants: **C0** unweighted, **C1** IPS weights 1/p where 0 < p < 1 (clip 10), else 1.

## Metrics on the holdout

- **Primary: hint-label AUC** (pooled over pairs). 95 % CI by bootstrap over experiences (clusters), 2,000 resamples, seed 22112026.
- **Secondary:** paired AUC difference vs A1 (same bootstrap); within-experience pairwise accuracy on experiences with mixed labels
  (did the model order a positive above a negative of the same action); Recall@4 of the positives among the logged candidates
  (`before.candidates`) for B and C — the positives are known only among shown hints, so this is a lower-bound proxy and is
  reported as such; A1 has no score for unshown candidates and is excluded from it.
- **Online yardstick (not decided by this offline test):** the stratified hold-back lift (stratum = day × instance × tool), today
  +0.0 ± 1.0 points; detectable effect at today's volume about ±2 points.

## Hypotheses and decision rules

- **H1:** the best of B, C0, C1 (chosen by hint-label AUC on the inner validation after refitting on the inner-train part with
  the selected hyper-parameter, never on the holdout; ties → the simpler model, B < C0 < C1) has a holdout hint-label AUC above A1's,
  with the bootstrap 95 % CI of the paired difference above 0.
- **H2:** the same chosen model reaches hint-label AUC ≥ 0.65 (lower CI bound reported; the point estimate decides).
- **H3 (descriptive):** C1 vs C0 — does IPS change the AUC? No direction pre-stated; with 221 propensity pairs a null is expected.
- **H4 (descriptive):** A2 and A3 (outcome-based) vs B/C (label-based) — expected: outcome-based ≈ 0.5 on hint labels (fact 1).

If H1 and H2 hold, block 4 designs how the label model enters the ranking (with propensity logging kept and an online hold-back
comparison), as code on its own branch with tests — no deploy. If they fail, the report says which part failed and the next step
is more hint labels (where and how cheaply), not more model.

## Goal Z7 wording — pending the user's confirmation

Proposed: **"hint-label AUC ≥ 0.65 on a temporal holdout AND a positive stratified hold-back lift"** instead of the outcome AUC.
Until the user confirms, this document reports both and decides only H1–H4.

## Limits

One copy, two weeks of data, about 400 holdout pairs: wide intervals. Labels are not missing at random — agents give feedback and
the judge runs on selected conversations. A replica (A2, A3) is not the production code; its deviations are listed above.

## Results (run 2026-11-22 10:58 UTC on commit 0985a9e, unchanged script)

1,379 labelled pairs; cutoff 2026-11-18T16:41; train 964 (588 positive), holdout 415 pairs / 206 actions / 89 hints (257 positive).
Label sources: train feedback 375 / used 373 / judge 216; holdout used 233 / judge 162 / feedback 20.

| model | holdout hint-label AUC | 95 % CI (cluster bootstrap, 2,000) | Δ vs A1, 95 % CI |
|---|---|---|---|
| A1 live order | 0.552 | 0.510–0.596 | — |
| A2 bandit replica | 0.388 | 0.320–0.461 | −0.244 … −0.078 |
| A3 outcome-router replica | 0.637 | 0.542–0.724 | −0.017 … +0.183 |
| B Beta posterior (s = 1) | 0.811 | 0.750–0.865 | +0.189 … +0.324 |
| C0 label logistic (C = 1) | 0.780 | 0.700–0.849 | +0.141 … +0.304 |
| C1 label logistic + IPS (C = 1) | 0.776 | 0.696–0.846 | +0.138 … +0.301 |

Chosen on the inner validation: C1 (0.962 vs C0 0.961, B 0.917). **H1 holds** (Δ +0.224, CI low +0.138), **H2 holds** (0.776 ≥ 0.65).
H3: IPS changes nothing (0.776 vs 0.780). H4: the outcome-based bandit ranks hints *against* their labels (0.388); the outcome-router
replica sits between. Within-action pairwise accuracy on 50 mixed pairs: A1 0.38, A2 0.42, A3 0.64, B 0.64, C0/C1 0.58.
Recall@4 among logged candidates (mean 6.7): B 0.901, C0 0.902, C1 0.894 — no random baseline was pre-registered, so not interpretable.

### Post-hoc check (not pre-registered) — the pass is a label-source artefact

The label source decides the label almost alone: holdout `used` 233/233 positive, `judge` 16/162 positive, `feedback` 8/20.
A predictor that knows only the share of a hint's training labels that came from `used` reaches **AUC 0.787** — as high as the models.
Within one source: judge B 0.577, C0 0.528, source-only 0.559 (16 positives); feedback B 0.417, C0 0.229 (n = 20). Judge-only temporal
split (one labeller, train 9 positives): B 0.607. So H1/H2 pass formally but measure which mechanism labels a hint, not its use.
**Consequence for Z7:** "hint-label AUC" is only a valid criterion on a label from **one labeller with both classes**. Candidate found
post hoc: actions whose agent reported `used=[…]` with ≥ 2 shown hints — the other shown hints are implicit negatives of the same
labeller at the same moment: 299 actions, 447 positive / 639 negative (12.–22.11.2026). It needs its own pre-registration
(within-action ranking, conditional logit), and two caveats: "not reported as used" is weaker than "not used", and only actions with
at least one used hint carry the field.

## Note (22.11.2026 13:0x UTC) — the `before.warning` imbalance is a period effect, not a recording artefact

Known fact 2 above named it a hypothesis: a recording artefact. Checked on the same copy, split by hold probability: at 0.05 warnings
in 350/1,072 shown vs 18/62 held-back actions (0.326 vs 0.290); at 0.2 in 0/2,615 vs 0/699. Within each period the arms are balanced;
the pooled 0.099 vs 0.025 comes from the held-back arm lying mostly in the 0.2 period, in which no risk warning was given at all
(0 of 3,314 eligible actions since 16.11.2026) — the same Simpson structure as the hold-back difference. The hypothesis "recording
artefact" is withdrawn. Why the risk warning stopped is not examined here (the router model is in test, not used).
