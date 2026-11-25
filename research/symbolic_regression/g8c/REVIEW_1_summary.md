# G8c draft — independent review 1 (Fable, 19.11.2026): "redesign the arms and the gate, then run"

Blocking:
1. LP vs L cannot separate task information from a task-independent operator prior: operators differ in how often they change the
   program at all (forced on 150 mapped starts x 6 tasks: add_rule 0.93, add_lit 0.78, add_neq 0.75, add_neg 0.72, invent 0.55,
   pred 0.49, del_lit 0.42, var 0.40, recurse 0.24, del_rule 0.23, flip 0.23, const 0.20); a no-op child is a free cached clone, so
   reweighting changes evaluations per generation. Fix: primary = LP vs LPs (permuted) and vs LM (mean output) on O2.
2. Block proposal nearly inert (24 blocks; 8 of 23 core tasks exhaust the start space below K = 200) and where it acts it changes
   start_evals and which pairs are excluded from O2 (selection bias). Fix: identical start sets across arms (start RNG without the arm
   name) for the operator test; test block proposal separately with small K, outcome lookup rate and OT.
3. Dream labels: operator names include no-ops; invent is semantics-preserving (no observable trace, but the route to recursion);
   recurse rarely observable on random worlds; origin block not identifiable (blocks map to the same canonical program); names are not
   a minimal edit script. Fix: effective ops only, dedup by canonical program with the set of producing blocks as label, non-equivalence
   against every unmodified block on structured worlds, retained share per operator.
4. Gate G8c-0 can pass trivially (significance, vocabulary/arity shortcut, near-duplicate leakage) and prediction is not search utility.
   Fix: hold out by structure; effect threshold + arity-only ablation; G8c-0b ORACLE test on held-out dreams — G8c-1 only if the oracle
   prior reaches ratio >= 1.5; transfer check on 5 lookup tasks.
5. Tasks and seeds are not blind any more (gp2 deterministic: L reruns bit-identical; outcomes known). Fix: new blind task set as
   confirmatory (33 = development) or at least seeds 10-19; freeze R before any test-task run; uniform path must reproduce the 330 L runs
   exactly.
Should fix: 6 LPs = derangement per seed + divergence threshold; 7 void "convincing pattern" clauses (kind a has no O2 pairs; gp2 does
not record operators — record effective ops per lineage); 8 conjunction rule instead of Holm, per-kind effect; 9 power fine only for a
homogeneous effect (17 tasks carry O2, 7 at a floor) — pre-specify stratum median L O2 >= 300, 20 seeds or new tasks; 10 XRP ill-defined
(rewiring redrawn per run); 11 dream worlds must match the test worlds R reads.
Minor 12: a static per-task prior is not DreamCoder's candidate-conditioned guidance — a null rejects this reweighting only.
