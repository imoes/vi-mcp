# G10 v2 — vector-symbolic retrieval for the rule search (after review 1, 19.11.2026; for review 2)

Changes against v1, by review finding (REVIEW_1_summary.md):

## Encoding (findings 7, 9, 15)
- One dimension d = 2048, FHRR (torchhd 5.8.4), 10 codebook seeds fixed before any measurement.
- Canonical key: a TRUE canonical labelling — brute force over literal orders and variable numberings (body ≤ 6, cheap), lexicographically
  smallest name-free form; gp2.canon_rule is NOT used (it breaks ties by variable names, gp2.py:72). T1 (renaming invariance) becomes a
  unit test of this function, not a gate.
- Predicate identity per rule: 'same predicate as literal i / new predicate' plus arity (so p(X,Y) & p(Y,Z) differs from p(X,Y) & q(Y,Z));
  constants keep identity WITHIN a rule (same/new constant), no global names (DESIGN_RULES.md R1). Variables only by context: each
  variable slot = bundle of the (literal-index, argument) roles it occurs in (Plate 1993 contextualisation). '!=' = a literal with its own
  role; '~' = sign role; inv-helpers = 'defined-in-program' predicate role; types are not encoded (they exist only per task).
- Library deduplicated by key; class sizes reported (review: 93 classes for 113 rules when constants keep identity).
- What is encoded is what mapped_chunk produces (library constants become variables, arms2.py:157).

## G10-0 — does the key carry structure beyond trivial signatures? (no search)
Unit of analysis: rules (68 non-trivial library rules + 57 reference rules of the 33 tasks, descriptive only — the 33 tasks are development).
- Baselines, all reported: random; wiring-blind signature (#pos, #neg, #!=, recursive, arities); body length; block size.
- R1 (similarity vs structure): AUC / average precision of cosine for SYMMETRIC near.matches pairs, and Spearman against a graded
  structural edit distance fixed now (literal insert/delete/sign flip = 1, argument rewiring = 1 per moved occurrence); margin over the
  wiring-blind baseline with a pair-bootstrap CI (finding 10).
- R2 (rewiring sensitivity, on the 71 rewirable rules only): cos(rule, its XR copy) vs cos(rule, another rule with the SAME wiring-blind
  signature); report AUC; plain HRR without contextualisation as ablation (finding 8).
- R3 (retrieval with an oracle query, rule level): for each reference rule with a symmetric match in the library, MRR / recall@k of the
  matching library rules among ALL library rules plus 500 DISTRACTORS (library rules with 1–3 effective edits and rewired copies, deduplicated,
  none matching the query), so that chance recall@3 < 0.2 (finding 1). Gate: MRR margin over the best baseline > 0, CI excluding 0.
- R4 (retrieval from PARTIAL programs, finding 12): replay recorded archive snapshots of gp2 runs (Z start, every 100 evaluations, archive
  re-evaluated after counterexamples) and measure whether the best partial programs retrieve the reference's matching library rule earlier
  than the baselines. Gate for G10-1: R4 margin > 0 with CI excluding 0.

## G10-1 — retrieval during the search, under scarcity (pre-registered after G10-0; findings 2–6, 11, 13, 14, 16)
- Library: the 24 real blocks + the 500 distractors of R3 (scarcity: uniform draws rarely hit the right block); retrieval at RULE level,
  the matched rule seeds mapped_chunk with the alignment as predicate mapping (finding 11).
- Start: Z (random rules, no library start) in every arm — what is tested is retrieval during the search, not start-phase lookup.
- Injection: every 100 evaluations, exactly N = 10 NOVEL programs (not in the cache, redrawn until novel) replace the 10 worst non-elite
  members, in every arm; the query's own origin is excluded; novel/cached injections and evaluations logged per arm.
  Arms: U random rules · Vr uniform random library (+ distractor) programs · Vs retrieval with shuffled keys · V retrieval · O symbolic
  oracle (near.matches against the reference — an upper bound).
- Gate: O vs Vs must reach ratio ≥ 1.5 on O2 (else stop: retrieval cannot help this search even when perfect).
- Primary (if the gate passes): V vs Vs on O2 and on OT; secondary V vs Vr, V vs U; record whether the first solution is an injected
  program (lookup) or a descendant (seed) and analyse both.
- Tasks: a NEW blind task set (written without the library, the encoder or these results), strata for match selectivity and hardness
  (median U O2 ≥ 300) fixed beforehand, ≥ 20 seeds; the 33 tasks only descriptive.
- Regression check: U with injection off replays the 330 stored L runs bit-identically (start L) — run before any arm comparison (16).

## Not now
G10-2 (edits in vector space, a proposer predicting the structural operation — DTM arXiv 2306.00751) only if G10-1 is positive.
