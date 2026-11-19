# G8c — a proposer trained on dreams: does it turn the library from a lookup into a seed for modification? (DRAFT for review)

## Why
G8b-1 (pre-registered, 33 blind tasks, 1,320 runs): the library of mechanisms helps by unchanged reuse (start-phase solution 25.7 % vs
10.4 % with the library rewired, Holm p = 0.0003) but NOT as a seed for modified mechanisms (H1: evaluations after the start phase,
median cost ratio XR/L 1.10, 95 % CI [0.93, 1.24], below the smallest effect of interest 1.5). In gp2 every mutation operator and
every start block is drawn UNIFORMLY: nothing tells the search which block to start from or which edit to make. DreamCoder (Ellis et
al., arXiv 2006.08381) reports that library learning and a recognition model — trained on "dreams", programs sampled from the library
and run — each add substantially. G8c adds that missing piece and asks again the question G8b-1 H1 answered no.

## The proposer R
- **Dreams (training data, never a blind task):** take a library block (the same 113 rules of kollektiv, messung, code that arms2.py
  uses), map it onto a random synthetic vocabulary (arms2.mapped_chunk with fresh predicate names), apply k ∈ {0, 1, 2, 3} random gp2
  mutations → target program P*. Generate N random worlds over P*'s input predicates and typed domains; answers = clingo on P*.
  Keep a dream only if its answers vary across worlds, and for k > 0 only if P* is not equivalent (on its worlds) to the unmodified
  block. Record (worlds + answers, origin block, the k operator names).
- **Two models (kleinmodell zuerst):**
  - R-lin: hand-written task features (input arities, answer density, answer/input co-occurrence, signatures such as "answer pairs
    closed under composition" for recursion, negation signatures "answer iff input absent") → multinomial logistic regression
    (scikit-learn) for the origin block and for each of the 12 operators (present / absent).
  - R-tiny: the from-scratch tiny transformer (CPU, ~1 M parameters) reading the worlds as text → the same outputs.
- **G8c-0 (feasibility, on held-out dreams only):** top-5 origin-block accuracy vs the frequency baseline; per-operator AUC vs 0.5.
  G8c-1 runs only if R beats both baselines on held-out dreams (bootstrap CI over dreams excludes the baseline).

## G8c-1 (the test)
Same 33 blind tasks, same gp2 search, same budget (15,000 evaluations after the start phase), seeds 0–9.
- **L** — G8b-1's arm L, rerun with the G8c code path and uniform probabilities (must reproduce G8b-1's L numbers within noise —
  a check of the code path, reported).
- **LP** — start blocks drawn with R's block probabilities; mutation operators drawn from 0.8 × R's operator distribution + 0.2 ×
  uniform (exploration kept).
- **LPs** — R's outputs permuted ACROSS tasks (a proposer exists and is non-uniform, but carries no task information): separates
  information from mere non-uniformity.
- (secondary) **XRP** — R trained on dreams from the REWIRED library, used with the rewired library: does a proposer make a
  structureless library useful?

Primary H1c: LP needs fewer evaluations after the start phase than L (O2, pairs without a start-phase solution in either arm), the
statistic of G8b-1 (task = unit, mean rank differences, 10,000 sign flips), smallest effect of interest: ratio 1.5.
H2c: LP vs LPs on total cost OT. Holm over H1c, H2c. H2 of G8b-1 (lookup) is reported for LP vs L without a claim.

## Convincing pattern (fixed in advance)
LP beats L AND LPs on O2; the gain is larger on tasks whose solution needs a modified mechanism (G8b-1's kind b and c) than on
kind a; R's predicted operators for a solved task match the operators on that solution's lineage more often than LPs's do.

## Limits (named in advance)
- The 33 blind tasks were already used in G8b-1 (as test, never for training). R never sees them.
- Dreams come from the same library: R learns this library's edit statistics, not edits in general.
- gp2's operator set is fixed; R only reweights it.
- One search, one library; the tiny model is small on purpose.
