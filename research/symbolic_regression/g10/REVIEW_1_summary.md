# G10 plan — independent review 1 (Fable, 19.11.2026): "redesign" (gate of G10-0 and injection of G10-1; the encoder idea stays)
Blocking:
1. T4 passes without structure: recall@3 random 0.73, block size 0.923, wiring-blind signature 0.923, body length 0.808 (26 tasks with a
   near match; median task matches 13 of 24 blocks). Fix: rule level (68 non-trivial rules), MRR / recall@k, gate on the margin over the
   wiring-blind and size baselines with task-bootstrap CI; selective stratum separately; distractors so chance < 0.2.
2. No scarcity: where retrieval is selective the uniform L start already finds the block (first_in_start 10/10 or 9/10); the K = 200 start
   already evaluated 33-91 % of sampled mapped block programs. Fix: library >= 500 blocks (other packages, XR/XL variants as distractors) or
   K ~ 10-20; lookup rate and OT co-primary; gate G10-1 on a symbolic-oracle arm (near.matches vs reference) reaching ratio >= 1.5 vs shuffled.
3. Injection channel barely exists: immigrants only when tries > 4*POP (gp2.py:478): 0-7 distinct immigrants per run. Fix: a separate fixed
   injection of N programs replacing the N worst non-elite members at each event, in every arm (U: random rules, Vs: shuffled-key library).
4. Timing by generations leaves most pairs identical (22-71 % solved before R = 2..20); 6 of 17 O2 tasks finish in <= 4 generations.
   Fix: trigger by evaluations (every 100 evals); stratum median U O2 >= 300; >= 20 seeds; new tasks needing > 1,000 evals.
5. Evaluation-cost confound V vs Vs (cached programs cost 0, gp2.py:372; V re-injects its own cached block). Fix: N NOVEL programs per
   event in every arm, exclude the query's origin block, log novel/cached injections; add Vr (uniform random library blocks).
6. Start set unspecified (L: findings 2/5; Z: V vs U = known H2 lookup effect). Fix: one start (Z or small-K L), record whether the first
   solution is an injected program (lookup) or a descendant (seed).
Should fix: 7 T1 is a canonicaliser unit test, and gp2's canon is not invariant: canon_rule breaks ties by str(l) with variable names
(gp2.py:72): 4/113 library and 6/57 reference rules change under renaming+shuffle; 42/113 change order under predicate renaming (gp2.py:71)
— true canonical labelling needed (brute force, body <= 6). 8 T2 trivial and in conflict with T3 (42/113 rules cannot be rewired; 27 of 71
rewired still near-match). 9 name-free identity collides (75 classes for 113 rules if constants merge; 93 if constants keep identity);
use per-rule same/different predicate identity; dedup the library. 10 T3 target asymmetric (242 of 404 matches one-directional) -> AUC/AP vs
symmetric match + a fixed graded edit distance. 11 retrieve rules, not blocks; seed mapped_chunk with the matched rule. 12 add T5: retrieval
from recorded partial archive programs; re-evaluate the archive after counterexamples. 13 gates from baselines, one d, >= 10 codebook seeds
fixed beforehand; new blind task set confirmatory, the 33 descriptive. Minor: 14 Vn only in G10-0; 15 one d; 16 U must replay the 330 L runs
bit-identically with injection off.
Reviewer scripts: review_scratch/m1.py-m5.py (read-only measurements).
