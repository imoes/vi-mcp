# Plan R3 — the consolidated next kit (draft 21.11.2026 ~10:40 UTC; not built, not pre-registered)

Rule "Training konsolidieren": findings go into the next kit, not into single runs. This draft collects what kit R2 run 1, the
R2-small parts, the Q1 analysis, run 34 and the literature taught, and marks what still waits for running measurements.

## What we know (with sources)
| finding | evidence | consequence for R3 |
|---|---|---|
| Way A: shape right, predicates wrong | held-in 17/300 exact, 145/300 with clingo re-binding (shape_bind.py); base 0/300 | split the task: the model proposes SHAPES (ranked), clingo binds predicates |
| never-trained shapes are never produced | held-out 0/200 (tuned and base); no method in the literature creates them (research log 21.11) | unseen shapes come from search (gp2 + G8d proposer), not from the model |
| proposing beats enumerating only marginally | model 13.2 calls vs enumerate 84.7 at 145 vs 300 solved (addendum 5) | keep enumeration as fallback; the model's value is the ORDER of proposals (K samples raise coverage: pending) |
| value lines skipped in traces | 22/305 vs 4,012/4,012 in training; restoring them: comparison 29→70/67 | one representation per fact: values only in the compare line |
| rules in context are not applied at depth | R2-small B/C: depth 4–5 0 % in every arm; in distribution memorised 83–90 % vs in context 17–19 % | way B stays short (≤ 3 steps per call); depth by iterating calls, the solver checks each step |
| names act as retrieval keys | H13; run 34 P7 renamed 5/8 in both seeds; kin fresh arm confounded by sorted symbols | every task in a fresh-symbol arm with RANDOM symbol numbers (--random-fresh); renaming only arity-consistent |
| plain renaming is a weak fix | run 34: 600 renamed blocks, P7 renamed still 5/8 in both seeds; CREAM (arXiv 2207.11104): training on MISLEADING identifiers (counterfactual) made code models robust to renaming, most on small data; ContraBERT (2301.09072): renaming augmentation helps least because renamed copies stay close to the originals | add counterfactual rows: a KNOWN name bound to a DIFFERENT rule in the prompt (the model must follow the given rule, not the remembered one); opaque tokens for part of the rows |
| ~~a name trained at two arities~~ (withdrawn 21.11.) | run 34 s42's two write_rules errors are the prompt-invalid items language_heldout:1/:21 (doubled-object prose); run 33c s43 (no ternary rows) errs on :1 too | exclude prompt-invalid items in scoring; no arity-specific change needed |
| reading is the pipeline bottleneck | Q1: 93 % of gold facts stated, 855/941 read; misses country of origin (4/23), mother/spouse | add read rows for these relations with distractor padding (as way B), measured on the fresh Q1 set |
| entity linking breaks chains | Q1 inference: 11 fail with gold facts (containment merges father/son; Jaccard splits ab/ap) | a linking step in the pipeline (title anchoring pre-registered; alias table from the paragraph) — not a training target |
| solve@k ≫ greedy for the tiny model | Part A p0: solve@16 7.2 % vs greedy 1.0 % | expert iteration is worth it; sample diversity matters (RLVR narrows pass@k at large k, Yue et al.) |

## Pending measurements that decide parts of R3
- **R2-small Part E (mirror worlds)** — if H-E1 holds (mix > indep on independent test worlds), half of the way-A rows become mirror
  tasks; if only H-E2 holds, predicate choice stays with clingo; if neither, no mirror rows.
- **R2-small Part D (rule recitation ctxR, frozen fresh embeddings ctxF)** — if ctxR beats ctx, way-B rows recite the rule before
  applying it (RFFT, Hu et al. 2402.17709).
- **Kit R2 EI round (gate ≥ 50/1,800 new exact rules)** — if passed, R3 starts from run 1 + EI rows; else SFT only.
- **G8d-1** — if the conditioned proposer C beats its permuted control, the search that supplies unseen shapes uses it.
- **Q1 levers on fresh questions** — decides the linking/tie-break steps of the pipeline (not training).

## Decided since the draft (21.11.2026, 17:40 UTC)
| pending item | result | R3 consequence |
|---|---|---|
| R2-small Part D | H-D1 (recitation ctxR) and H-D2 (frozen fresh embeddings ctxF) fail (insight:6519b446) | no recitation rows; rule application stays with the solver |
| Kit R2 EI round | gate passed (442/1,800), but solve@1 no gain: held-in 17→15 (p 0.79), held-out 0→0, kin 625→593, rf kin 17→24 (p 0.059, n.s.); by family only recursion was ever solved (15→10), the five others stay ≤ 2/50 | R3 starts from SFT, not from the EI adapter; no EI rows as targets — the model cannot choose predicates from data at this size (below STaR's precondition), so selection stays outside the generator (RLIE 2510.19698 pattern) |
| Q1 levers (fresh 400) | H-L1, H-L2 hold: alias EM 67.5 → 70.75 / 71.0 % | tie-break and title anchoring are pipeline steps, not training targets |
| own retrieval (sym-rag RAG-0) | all gold paragraphs in top 4: SYM-0 90.5 %, bge-m3 43.8 %, BM25 35.0 %; bridge_comparison 74 vs 1 vs 0 of 100 | the pipeline retrieves symbolically (title lookup + mention hop); the answer effect is RAG-1 (pre-registered) |

| K = 8 solver-call measure | model-first then enumeration solves held-in 300/300 at 47 calls vs 84.7 (before and after EI alike); held-out unsolved by every strategy | the model is a search ORDER (proposal ranking) in front of clingo, not a solver; unseen shapes (chain3/join) must come from gp2 / G8d search |
| data-ranked binder (PREREG_binder) | fresh 600 tasks, no model: trained shapes 450/450 at 5.7 calls vs 83.7 (448 vs 1 tasks, p 3e-133); chain3 + join via a shape grammar 150/150 at 18.1 calls | way A leaves the model: binding AND unseen shapes are symbolic (grammar + binder + clingo); kit R3 drops way-A rows (or keeps only a small shape-proposal head as an option) and spends the budget on translation (reader rows, question → goal) |
| covering binder (PREREG_binder amendment 1, H-BR3) | fresh kinship tasks with random symbols: 374/375 at 2.7 calls (CP lower 0.987) | real 2Wiki kinship rules (disjunctions included) are induced symbolically; the rule-learning part of the research model is gp2/binder/covering + clingo, the 0.6B model translates |
| where Q1 answers are lost (fresh 400) | gold facts 94.0 % vs read 70.75 %; 98 reading-loss questions (inference 48, compositional 39); mostly the object's written form (61), not missing relations (11); 23 objects unattainable (Wikidata only); symbolic object linking rejected on dev (71.5 / 69.25 %) | R3's main rows: READER rows for father, mother, spouse, place of birth/death, country — complete and text-faithful (R1 targets, more rows and distractor padding for these relations); NOT a canonical-name rewrite (corrected 19:04 UTC: three object-link rules gave no dev gain); 76 of the 98 losses are attainable (≤ +19 points); measured on a NEW fresh set |
| R2-small Part F | H-F1 and H-F2 fail: depth 4–5 0.0 % / 0.03 % faithful; in distribution worse than ctx | way B is not extended; depth stays with the solver; no step-wise trace rows in R3 |
| reader diagnosis (dev 400) | base 2-shot reads best alone (83.6 % stated recall); R1-full omits countries (no demonyms in its targets), kit R2 fixes countries but loses father (83 → 53/97); kin roles conflict in every reader (mother up to 33/52 wrong values) | R3 reader rows: demonyms in targets, father kept, kin-role contrast rows; judged by pipeline EM on a new fresh set; stated_recall.py (recall + conflicts) as diagnostic |
| R2-small Part H (counterfactual names) | H-H1 holds (prompt-rule reading under misleading names 45.1 % vs 0.5 %), H-H2 fails (recall 94.9 → 74.75 %) | given-rule vs recalled-rule tasks separated by an explicit marker; counterfactual-name rows are the way to make the model read a rule from the prompt (descriptively 45 % vs Part B's 16.6 % with fresh names) |
| G8d-1 (learned proposer for gp2's search) | H1 fails (C vs permuted Cs p 0.70), H2 holds (C < static prior P, p 0.009), H3 fails (C vs U p 0.69); C costs 4.4× U's wall time | the learned proposer is not used; O1/U in the hard stratum 0.707 (oracle 1.41× better than U, below the pre-registered 1.5×) → the G8d line ends; unseen shapes come from grammar + binder |
| R2-small Part G (names as vectors) | H-G1 fails (unseen names dual 3.9 % vs ctx 0 %, p 0.24), H-G2 fails (in distribution 4.0 vs 19.9 %) | no embedding change in R3; names are normalised in the pipeline (canonical renaming); counterfactual-name rows (Part H) are the remedy that works |
| R3r reader (PREREG_R3r) | H-R3r1 holds on fresh2: union(R3r, base) 70.75 % vs union(R1-full, base) 66.0 % (30 vs 11, p 0.0022); R3r ALONE 73.0 % (descriptive); R3r recall 91.3 % with 9.8 % conflicts | R3's reader rows = R3r rows (read-only, demonyms, kin contrast); test R3r alone vs the union next; adapter saved (sha f94be8b9…) |
| R2-small Part E (mirror worlds) | H-E1 and H-E2 fail (testI 3.9 vs 4.2 %, p 0.58); shape right ~44 % in both arms, predicates wrong | no mirror tasks in R3; predicate choice stays symbolic (binder) |
| R3r alone vs union (PREREG_R3r2, fresh3) | H-R3r2 fails: ALONE 70.25 % vs UNION 71.0 % (20 vs 23, p 0.73); union recall 94.3 % / conflicts 18.9 %, R3r alone 89.2 % / 11.3 % | the union stays the deployed reader; reader rows = R3r rows; next lever = conflict resolution between the two readers (pipeline, development data first) |

| PREREG_R3m (primary-first merge, fresh4) | H-M1 holds: PREF 75.5 % vs UNION 70.0 % (27 vs 5, p 5.7e-5); H-M2 holds: PREF vs R3r alone 73.5 % (12 vs 4, p 0.038) | the Q1 reader is R3r + base merged primary-first; kit R3 needs no new reader rows from this line |
| RAG-1c (second hop, fresh2) | H-R1c holds: HOP@4 61.5 vs SYM0@4 56.75 % (19 vs 0); H-R2c fails: −4.5 vs gold paragraphs | the retriever is SYM-0 + reader-guided hop; distractor facts remain |

Nothing pending from this plan. Everything that decides the kit R3 rows is in.

## R3 kit outline (to be pre-registered once the pending results exist)
- Way A as SHAPE proposal: target = the rule with predicates replaced by slots plus a ranked list of K shapes; clingo binds; exact
  rules from EI NOT as rows (EI round failed); fresh-symbol arm with random numbers; mirror rows if Part E says so.
- Way B short: ≤ 3 derivation steps per call, value only in the compare line (no recitation: Part D failed); distractor facts
  (means facts included) at the reading densities.
- Reader rows for the relations the readers miss (country of origin, mother, spouse, place of death), with paragraph-title subjects.
- Language replay 20 % (13R: keeps language_heldout 30/30), R1d and cycle replay as in R2.
- Measures as R2 (paired vs run 1 and vs base, McNemar), plus: shapes proposed per solved task, solved within K, fresh Q1 set.
