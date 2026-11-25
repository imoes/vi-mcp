# PREREG binder — a data-ranked binder for way A, confirmed on fresh tasks without any model (frozen 21.11.2026 18:07 UTC by PREREG_binder.sha256, before the fresh tasks are generated)

**How it came about (stated, not hidden).** Kit R2's EI round did not teach the model data-driven predicate choice (solve@1 held-in
17 → 15). The registered solver-call measure showed the model's value as a proposal ORDER (model shapes first, then enumeration:
held-in 300/300 at 47 calls vs 84.7). Then, EXPLORATORY on the already-used held-in (300) and random-fresh kinship (368) sets,
`binder_rank.py` bound slots by a marginal data score and was tried in two variants (run 1's answers and K = 8 samples):
- per-shape ranking: enumeration 84.7 → 74.1 calls; model shapes 32.7 → 21.6 (median 24 → 5);
- **global ranking** (all six shapes' bindings pooled, geometric mean of literal shares): **300/300 at 5.8 calls (median 3) with no
  model**; with the model's shapes in front 4.7 (median 2). Kinship rf: 246/368 at 1.2 calls with or without the model.
So the 0.6B model adds little to a data score for the six trained shapes. This registration confirms that on FRESH tasks and tests
whether the same binder over a slightly larger shape grammar solves the two families no model ever produced (chain3, join).
After the exploratory runs one change was made before this freeze: literals that touch neither X nor Y no longer count in the
geometric mean (affects only chain3's middle literal; no exploratory number changes).

**Data:** `gen_rules.py --seed 61 --n 600` (sha256 28aa0ea5…; seeds used before: 0, 1, 7, 8, 20 — 61 is fresh): 8 families ×
75 tasks (chain2, chain3, inverse, disj, filter, neg, recursion, join), two worlds each, closed world, generated after this freeze.

**Binder score** (`binder_rank.py`): for each body literal of a shape and each head variable it contains at argument position i, the
bound predicate's share of positive pairs whose value occurs at position i of some fact of that predicate (negated literal: does not
occur), averaged over both worlds; a (shape, binding) scores the geometric mean over its constrained literals. No candidate rule is
evaluated to compute it. Ties: shape order, then binding order.

**Strategies** (`binder_confirm.py`; calls = clingo checks `score_kit_r2.way_a_exact` until the first exact rule; cap 4,000):
enum (six trained shapes, fixed order) · enum_global (same shapes, binder-ranked) · grammar_global (six shapes + chain3 + join,
binder-ranked).

**Hypotheses** (`binder_test.py`, unit = task, α 0.05):
- **H-BR1:** on the 450 tasks of the six trained families enum_global needs fewer calls than enum — exact one-sided sign test (an
  unsolved strategy counts 4,001 calls; ties dropped).
- **H-BR2:** grammar_global solves the 150 chain3 + join tasks: one-sided 95 % Clopper–Pearson lower bound of the solved share > 0.80.
- Descriptive: per family solved / mean calls / share solved at the first call; grammar_global vs enum_global on the trained six.

**Decision:** H-BR1 holds → the pipeline binds predicates by the data score, not by the model; kit R3 drops way-A targets with
concrete predicates (the model, if kept, proposes shapes only). H-BR2 holds → unseen shapes come from a small shape grammar + binder
(gp2 / G8d only beyond it); kit R3 does not try to teach new shapes. Either failing is reported with the per-family numbers.

**Named limits:** synthetic worlds of 7 entities with random facts — real relations (2Wiki kinship) have skew the marginals may not
see; the binder is only as complete as the shape grammar; calls count clingo checks, not the cost of the score (linear in facts).

**Hashes (sha256):** binder_rank.py d5b75884… · binder_confirm.py b8a7be8d… · binder_test.py 716cbd6b… · solver_calls.py
bd8177d3… · score_kit_r2.py bcf4f73d… · gen_rules.py 28aa0ea5…

## Amendment 1 (18:12 UTC, after H-BR1/H-BR2 were read, before any fresh kinship task exists)
Result read before this amendment: H-BR1 and H-BR2 hold (research log). Then, EXPLORATORY on the already-used random-fresh kinship
set (368) and held-in (300): 122 kinship tasks need two-clause rules with four different predicates, outside every shape list.
`binder_cover.py` (sha d0bd097d1532777f…) adds FOIL-style sequential covering: one-clause
shapes (base, chain2, inverse, filter, neg, join), bindings ranked by the binder score against the still uncovered positives, a
clause accepted when clingo shows it derives ≥ 1 uncovered positive and nothing else; up to 3 clauses, then the exact check.
Exploratory: kinship rf 367/368 at 2.7 calls; held-in 256/300 (recursion 6/50 — no recursive clause in the list).
- **H-BR3 (new, confirmatory):** on FRESH kinship tasks — `gen_kin_rules.py ../kin/kin_inference_g2.json ../kin/kin_selected.jsonl
  OUT --per-rel 30 --split dev --random-fresh --seed 61` (only seed 0 was used before; new worlds from the same dev question pool),
  fresh arm only — binder_cover solves with a one-sided 95 % Clopper–Pearson lower bound > 0.90 (`binder_cover_test.py`, sha
  60e0c7f718fbebbe…).
- Descriptive: binder_cover on the 600 seed-61 synthetic tasks per family; grammar_global on the fresh kinship tasks.
