# Who should learn what? A 0.6B model, a solver and a binder on multi-hop questions and rule induction

*Working paper, vi-mcp research branch symbolic-regression, draft written 21.11.2026 20:33 UTC. Intended as the basis of a BabyLM
workshop paper (non-competition track: language modelling × cognitive science). Every number names its pre-registration or
analysis and the commit that holds it; "exploratory" marks what was not pre-registered. Evidence levels as in EXAPTATION_PAPER.md:
**A** own measurement, reproducible from the named files; **B** read in the cited paper; **H** hypothesis.*

## 0 Summary
We built a question-answering and rule-learning system in which a small language model (Qwen3-0.6B, LoRA) translates between
English and logic (question → clingo goal, paragraph → facts), the answer-set solver clingo derives, and rules come from search. Over
one week we tested, mostly pre-registered and on fresh data, which of the three jobs — **translating, inducing, deriving** — a model
of this size should be trained for. The answer is unusually clean:
1. **Deriving belongs to the solver.** A tiny GPT trained on derivation traces applies rules written in its prompt in 16.6 % of
   in-distribution items and in 0 % at unseen depth 4–5, with or without recitation, frozen name embeddings or one-step iteration
   (R2-small Parts B, D, F; all pre-registered hypotheses fail) (A). A pretrained 0.6B model with LoRA does read: trained on
   recall plus counterfactual rows, it follows unseen rule bodies written in its prompt in 55.7 % of items (74 % at one step, 41 % at
   three) against 1.1 % for the tiny model (p 0.00033), and recalls its library better than without the reading rows (94.9 vs 88.1 %).
   The goal of 85 % on both is missed (A, PREREG_Z3_2). Training the reading rows on 60 instead of 12 rule bodies raises unseen-rule
   reading to 72.6 % (p 0.0079; 216 bodies: 62.9 %, p 0.028) and removes the template failure, but the goal is missed again and
   recall falls slightly; the dominant error becomes citing facts the world does not contain. By the pre-registration this approach
   ends there (A, PREREG_Z3_3); continuing Z3 (user, 25.11.2026) is a new approach with its own pre-registration.
2. **Inducing belongs to the symbolic side.** A fine-tuned 0.6B model writes exact rules for 17 / 300 synthetic tasks; expert
   iteration on its own verified samples does not raise that (17 → 15). A training-free binder — rank every (rule shape, predicate
   binding) by marginal data statistics, let clingo check in that order — solves 450 / 450 fresh tasks of the trained shapes in 5.7
   solver calls on average (fixed enumeration 83.7, model-first 32.7), 150 / 150 tasks of two shapes no model ever produced via a
   small shape grammar, and with FOIL-style covering 374 / 375 fresh 2Wiki kinship tasks (A, pre-registered, PREREG_binder). Its
   limit is coverage, not cost: on 40 blind tasks written by an independent author (default negation, invented helpers, arity 3) it
   uses fewer evaluations than a genetic program search on 22 tasks and more on 12 (Wilcoxon p 0.074, pre-registered hypothesis not
   shown); 7 tasks need mechanisms its grammar lacks (undirected reach, mutual recursion, nested negation, …) (A, PREREG_binder_g8d).
   Extending the grammar from those references did not carry to the next author: on a second blind set binder-G2 is fewer on 14,
   more on 18 (p 0.589), so binder-G ended under the two-failures rule; 8 of its 25 losses are again shapes outside the grammar (A,
   PREREG_binder_g8e). A pre-registered portfolio of the two engines beats gp2 alone on a third blind set (gp2 start phase, then
   binder-G2 up to 3,200 evaluations, then gp2: fewer on 18, more on 7, Holm-adjusted p 0.0094; binder-first also holds, p 0.0247)
   but reaches 18 of 40 tasks, not the goal of 35 (A, PREREG_portfolio_g8f). Even the per-run best of binder-G2 and gp2 is cheaper
   than gp2 alone on only 15–25 of 40 tasks — the open lever is the hypothesis space, not the schedule (A, descriptive; §2.3, §2.8).
3. **Translating is the model's job — and its bottleneck.** The pipeline answers 70.75 % of 400 fresh 2WikiMultiHopQA questions
   with its own reads and 94.0 % with gold facts; 76 of the 98 reading-loss questions are attainable from the text (A). A dedicated
   reader (read rows only, demonyms, kin-role contrast) plus a primary-first merge with the base model's reads raises this to 75.5 %
   on a further fresh set (vs 70.0 % for the plain union, 27 vs 5 questions, p 5.7e-5; vs the dedicated reader alone 73.5 %, p 0.038;
   pre-registered, PREREG_R3r + PREREG_R3m) (A). Fine-tuning pays exactly here. What is left is recall:
   31 of 44 missed gold facts are in neither read, and a perfect gold arbiter between the two readers adds only 0.25–2 points;
   sampled reads with an answer vote gain 10 questions for 1 lost on development data but rarely produce a missing fact (§2.12, A).
4. **Names are retrieval keys.** Fixed names make tiny models recall instead of read (H13s g3: trap recall 99.8 / 99.4 / 92.7 % at
   name doses 100 / 90 / 50 %, chance floor 4.6 %); for symbolic retrieval the same property is an asset: looking up the titles
   named in a question and one mention hop finds all gold paragraphs for 90.5 % of questions at k = 4 vs 35.0 % (BM25) and 43.8 %
   (bge-m3) (A). End to end, a reader-guided second hop answers 61.5 % vs 56.75 % without it (19 vs 0 questions, p 2e-6), 4.5 points
   below the gold paragraphs (pre-registered, RAG-1c) (A).
5. **Thinking in clingo needs teaching first.** Untrained, Qwen3-0.6B solves 5 of 100 multi-step deductions by writing a clingo
   program for the solver, against 16 of 100 in step-by-step prose (3 vs 14 discordant, p 0.0127, Holm 0.0509; pre-registered
   hypothesis not shown, opposite direction); 77 of its solver calls fail on syntax or grounding, and the solver's report repairs
   nothing (A, PREREG_CT_S0, §2.11). Formalisation must be trained before a solver loop can pay off.

## 1 System
- **Reader:** Qwen3-0.6B reads a paragraph into `relation("Subject", "Object").` lines over the 34 relations of 2Wiki
  (`d0_docs.py`, `q1_read_v2.py`: greedy, no token cap, loop guard). Deployed reader since 22.11.2026 = R3r (LoRA, 0-shot) merged
  primary-first with the base model (2-shot): a base triple is kept only where R3r gives none for that relation and subject
  (`reader_merge.py`, PREREG_R3m).
- **Goal:** the question's goal is a template induced from TRAIN questions (`goal_templates.py`, no model).
- **Solver:** clingo derives the answer (`q1_oracle.py`); kinship rules from Popper on train worlds (`kin_selected.jsonl`).
- **Pipeline levers (pre-registered, PREREG_Q1_levers):** tie-break (shortest contained value) and title anchoring.
- **Metric:** official 2Wiki evaluator v1.1 EM with aliases and demonyms (`official_score.py`, sha 7f9170e9…).

## 2 Results
### 2.1 Pipeline on fresh questions (PREREG_Q1_levers, commit 4e9f10f; analysis 72f4ff7, bb579a0)
400 fresh dev questions (100 per type): no lever 67.5 %, tie-break 71.0 % (14 vs 0, p 6e-5), both 70.75 % (14 vs 1, p 0.0005). With
gold facts as reads the same pipeline answers 94.0 %. Per question: 278 right both ways, 98 right only with gold facts (inference 48,
compositional 39), 19 wrong both ways, 5 right only with read facts; 22 of the 98 contain a fact whose object is not in the paragraph
(Wikidata only), so ≤ +19 points are attainable by reading. Three symbolic object-linking rules were rejected on the development set
(71.5 / 69.25 / 72.25 vs 72.5 %): relatives share name tokens.

### 2.2 Readers (exploratory, development 400; commits d690247, 5b3c816)
Stated-fact recall / conflicting values: R1-full 80.5 / 10.0 %, kit R2 81.5 / 9.8 %, base 2-shot 83.6 / 18.3 %, union R1-full + base
90.9 / 21.4 %. Pipeline EM: single readers 58.75 / 57.75 / 62.0 %, union 72.5 %. R1-full omits nationalities because its targets
lacked demonyms (country of citizenship 8 / 55 vs base 43 / 55); kit R2 repairs that (40 / 55) but reads father less (83 → 53 / 97;
cause untested — H: rows with father as a rule target). Every reader confuses kin roles (mother: up to 33 of 52 stated facts with a
competing wrong value). A dedicated reader (R3r: read rows only, demonyms, kin contrast; pre-registered, PREREG_R3r) raises the pipeline on a
new fresh set from 66.0 % to 70.75 % as part of the reader union (30 vs 11 questions, p 0.0022); stated-fact recall 91.3 % with 9.8 %
conflicting values. Its descriptive lead ALONE on that set (73.0 %) did not replicate on a further fresh set (PREREG_R3r2: alone
70.25 % vs union 71.0 %, 20 vs 23, p 0.73): the union recalls more (94.3 vs 89.2 %) but contradicts more (18.9 vs 11.3 %). Merging the
two readers primary-first (a base-reader triple only where R3r has none for that relation and subject) gave 75.25 % vs 70.75 % on
development data (21 vs 3) and, pre-registered on a fourth fresh set (PREREG_R3m), 75.5 % vs 70.0 % (27 vs 5, p 5.7e-5) and vs
R3r alone 73.5 % (12 vs 4, p 0.038). Where the merged reader still loses, and why no step over the two reads closes the gap, is
§2.12.

### 2.3 Rule induction (kit R2 + PREREG_binder; commits 09f4c33 … 35343f2, 498fe23, 457d7f3, dae9bbe, d559aca)
- Kit R2 run 1 (SFT): exact rules held-in 17 / 300 (base 0), unseen shapes 0 / 200; kinship with meaningful names 368 / 368, with
  randomly numbered symbols 17 / 368 (names are recalled, not induced).
- Expert iteration (pre-registered addenda 3/5): gate passed (442 / 1,800 samples exact at k = 8), but solve@1 after one round:
  held-in 17 → 15 (p 0.79), kinship 625 → 593; random-symbol kinship 17 → 24 (p 0.059). By family only recursion was ever solved
  (15 → 10). This matches STaR's precondition that the start model must be above chance (Zelikman et al. 2022) (B).
- Solver calls with the model's K = 8 shapes then enumeration: held-in 300 / 300 at 47 calls vs 84.7 — the model's value is the
  ORDER of proposals, not their content.
- **Binder (pre-registered, fresh tasks, no model):** H-BR1 450 / 450 at 5.73 vs 83.68 calls (fewer on 448 tasks, more on 1; sign
  test p 3e-133); H-BR2 chain3 + join 150 / 150 (one-sided 95 % Clopper–Pearson lower bound 0.980) at 18.1 calls; H-BR3 fresh
  kinship (random symbols) 374 / 375 at 2.7 calls (bound 0.987). A learned proposer for the program search (G8d-1, pre-registered, 40 blind tasks, 1,600 runs) does not beat its permuted control
  (p 0.70) or uniform proposals (p 0.69), only a static prior (p 0.009), at 4.4× the run time; even an oracle proposer beats uniform proposals only 1.41× on the hard tasks
  (pre-registered bar 1.5×), so guided search was abandoned. Same division as RLIE (LLM proposes, regularised logistic regression
  selects; arXiv 2510.19698) and LLM-built language bias for ILP (arXiv 2505.21486) (B) — here the proposer is not needed at all.
  The oracle's gain shrank from 2.76× on 12 hard development tasks (G8d-0b) to 1.41× on 16 hard blind tasks: a gain measured on
  tasks one has looked at did not carry to tasks one had not (A).
- **binder-G on blind tasks (no model; PREREG_binder_g8d, PREREG_binder_g8e; docs/SR_BINDER_G8D.md, SR_BINDER_G8E.md on branch
  sr-binder).** binder-G adds a grammar of helper templates (closures, reach from a unary start, undirected reach, negated guards,
  union closure) and negated sub-conjunctions to the binder. Measure: evaluations to the first verified exact program, task
  medians over 10 seeds, against gp2 with uniform proposals; CENSOR = 15,100.

  | | G8d-1 (binder-G) | g8e (binder-G2) |
  |---|---|---|
  | fewer / more / tie | 22 / 12 / 6 | 14 / 18 / 8 |
  | Wilcoxon one-sided | p 0.074 (fails) | statistic 276, p 0.589 (fails) |
  | solved runs binder / gp2 | 302 / 315 | 295 / 306 |
  | kind a / b / c fewer | 4/10, 12/15, 6/15 | 0/10, 8/15, 6/15 |

  Two failed pre-registrations end the approach (goal rule). After scoring, the references of the 25 qualifying g8e tasks were read
  and classified into classes fixed in advance:
  - (viii), 9 tasks: trivial kind-a tasks that gp2 hits inside its own random start phase.
  - (iii), 8 tasks: mechanisms outside the templates. Examples are reach with a negated guard on an EDGE, closure over the projection
    of a ternary predicate, reach from a derived start set, same-generation recursion on pairs, pairwise closure over symmetric or
    guarded edges, and inequality to a head variable. Seven of the eight were not on the first attempt's gap list.
  - (ix), 5 tasks: solved inside the grammar, slower than gp2's search.

  The engineered prior built from one author's references did not carry to the next author. 20 g8e runs (two tasks, all seeds) were
  killed by the registered 6 GB memory scope (A).
- **Portfolio on a third blind set (g8f; PREREG_portfolio_g8f.md on sr-binder, sha256 16bbbb8b…, commit 7f810e4; result
  docs/SR_PORTFOLIO_G8F.md, commit 3977b57).**
  - Result (A, scored 23.11.2026 20:30:43 UTC with the frozen script, recounted independently with identical p values):
    - P2 is fewer on 18 tasks, more on 7, tie 15 (raw p 0.0047, Holm-adjusted 0.0094);
    - P1 is fewer on 19, more on 14, tie 7 (raw p 0.0247, adjusted 0.0247);
    - both hold after Holm; P2 is the registered candidate; adoption is the user's decision;
    - Z2 is missed (18 and 19 of 40, needed 35), as predicted.
    - Named limit (found 24.11.2026 by the coordinating session's recount): the prereg's CENSOR sentence ("if gp2 is unsolved or
      missing … CENSOR") can be read literally to censor runs binder-G2 solved within B. The frozen scorer follows the portfolio
      reading (gp2 never runs after a binder solve), which the P1 rule states. Under the literal reading P1 gives p 0.23 and P2
      p 0.073, and neither holds. Both readings are in SR_PORTFOLIO_G8F.md (commit fb414bb).
  - Descriptive:
    - On g8f, binder-G2 alone already beats gp2 U (19/14/7, p 0.028; on g8e p 0.589). P1's task-level counts equal binder-G2's own
      in every kind, so the effect rests on the blind set more than on the schedule.
    - P2's gain over P1 is kind a (one-rule tasks), where gp2's start phase ties: SATzilla's pre-solving pattern, as predicted.
    - VBS is fewer on 21 of 40, so no schedule of these two engines reaches Z2 here either.
    - 6 kind-c tasks are unsolved in every run of every arm.
    - binder-G2 had no memory kill on g8f (20 on g8e).
  - Design, as registered:
  - Two co-primary orderings against gp2 alone, Holm at α 0.05:
    - P1: binder-G2 interrupted at B = 3,200 evaluations, then gp2;
    - P2: gp2's start phase, then binder-G2, then gp2's search.
  - B was chosen on G8d-1 + g8e by a rule fixed before the computation.
  - A bound found while preparing it (A, descriptive): the virtual best solver (per run, the cheaper of the two engines) beats gp2 on
    only 25 of 40 (G8d-1) and 15 of 40 (g8e) tasks. No schedule of these two engines reaches the goal of 35 of 40.
  - Portfolio theory predicts gains only for uncorrelated engines where neither dominates (Gomes & Selman 2001; SATzilla, Xu et al.
    2008) (B, read for the pre-registration).

### 2.4 Derivation in a tiny model (R2-small, all pre-registered; Parts B–F)
A 0.83 M-parameter GPT on synthetic worlds: rules in the prompt (ctx) 16.6 % faithful in distribution, memorised library (mem)
82.6 %; depth 4–5: 0 % in every arm (Part B). Recitation and frozen name embeddings fail (Part D: p 0.52, 0.79). One step per call,
harness- or model-kept chain: depth 4–5 0.03 % / 0.0 % (Part F: p 0.24, 1.0). Counterfactual library names (Part H, after
CREAM, arXiv 2207.11104; pre-registered): training half the items with library names bound to OTHER rules in the prompt makes the
model follow the prompt's rule under a misleading name in 45.1 % of items vs 0.5 % for the pure recall model (p 5.4e-6), at a cost
in recall (94.9 → 74.75 %). Names as per-sequence random vectors (Part G, after Isik et
al., arXiv 2410.17161; pre-registered) do not help: unseen names 3.9 % vs 0 % (p 0.24), in distribution 4.0 vs 19.9 %. Mirror worlds
(Part E, after SLR; pre-registered) do not teach predicate choice either: exact 3.9 vs 4.2 % (p 0.58), shape right in ~44 % of items
in both arms.

**Recall and reading in one tiny model (Z3-1, pre-registered; docs/SR_Z3_1.md on sr-binder, RESULT_Z3_1.json sha256 bd7d6083…).**
H-Z1 to H-Z4 all fail. On rules the model never saw, under trained names (testCFN), every arm stays at 0.0002–0.017 faithful; the
best seed reaches 0.037. Unseen rules under unseen names and depth 4–5 give 0 in all 40 runs. The tiny model maps a known body to a
new name (testCF 70–81 %); it does not read. **Z3-2** asks whether pretrained Qwen3-0.6B reads where the tiny model does not
(PREREG_Z3_2, sha256 5761b0d9…; result docs/SR_Z3_2.md on sr-binder, commit 3c63ede, RESULT_Z3_2.json sha256 643bfbfc…).

**Z3-2 result (A, scored 24.11.2026 01:31 UTC with the frozen script; recounted independently, identical).** Arms: Qwen3-0.6B LoRA
trained on recall + counterfactual rows (Qmix, 5 seeds), on recall only (Qmem, 5 seeds), and the base model with 3 worked examples
(Q0).
- H-Q1 holds: testCFN faithful Qmix 0.557 (seeds 0.482–0.620) vs the tiny mixeq 0.011 (exact MWU U 50, p 0.00033).
- H-Q2 holds: testI Qmix 0.949 vs Qmem 0.881 (CI of the difference [0.041, 0.096]).
- Goal Z3 (testI and testCFN ≥ 0.85) is missed on testCFN. Per the prereg, one last registration of this approach is allowed.

Descriptive:
- Reading falls with depth: testCFN 0.74 / 0.52 / 0.41 at depth 1 / 2 / 3; unseen names (testCFU) 0.51; depth 4–5 (testD) 0.84.
- Step-level count (added 24.11.2026, sr-binder SR_Z3_2.md "Step-level analysis"): each testCFN step succeeds with about 0.73
  whatever its position, so the depth curve is compounding of single-step errors (0.74, 0.74², 0.74³), not a chaining problem.
  84 % of the wrong grounded steps apply another trained library body. Hypothese: the model learned the 12 trained bodies as
  templates. The goal needs about 0.94 per step.
- Qmem follows memory instead of the prompt (memory-following 0.22 on testCFN).
- Q0 does not read (0.010), so the reading comes from the counterfactual training, not from pretraining alone.
- Against the tiny model: testCFU 0 → 0.51 and testD 0 → 0.84.

**Z3-3 (PREREG_Z3_3, scored 25.11.2026; sr-binder docs/SR_Z3_3.md, RESULT_Z3_3.json bfb75aa1…), the last registration of this
approach.** Same recipe as Z3-2 qmix; only the reading rows' bodies change, from 12 to 60 (qb60) or to 216 with every argument
orientation (qbwide).
- **H-B1 holds for both arms** (Holm), against Z3-2 qmix on testCFN 0.557:
  - qb60 0.726, U 24, p 0.0079;
  - qbwide 0.629, U 22, p 0.028.
- **Goal Z3 is missed** in both arms (testCFN < 0.85). H-B2 (no recall cost) is not shown: testI 0.916 / 0.888 vs 0.949.
- **By the prereg, the approach ends here.**
- **Descriptive:**
  - The template failure disappears: steps applying another trained body fall from 959 to 43 / 34, and per-step accuracy rises
    from about 0.73 to about 0.85 (qb60).
  - The dominant failure becomes grounding (body facts not in the world: 384 → 757 / 1,072).
  - More orientation diversity was worse (qbwide < qb60 on every set).

**Z3-G stage a, a new approach to Z3 (PREREG_Z3G_a, scored 25.11.2026; sr-binder docs/SR_Z3G_a.md, RESULT_Z3G_a.json
a9cf956a…).**
- Z3-3's dominant error was citing facts that are not in the world. 670 of 673 were near misses, and in 433 of 650 steps the model
  had picked a wrong target entity first.
- **Stage a:** the 10 Z3-3 models were re-decoded with the body of every step constrained to the given facts (a token mask, after
  Selection-Inference and grammar-constrained decoding).
- **The constraint works mechanically:** "fact not given" falls from 757 to 0.
- **It does not make steps faithful:** the errors become existing but wrong facts (64 → 818). qb60 testCFN is 0.7273 vs 0.7270
  (sign-flip p 0.125), so H-G1 fails and the goal is missed.
- **Reading (H):** the error is in choosing the next step, not in copying a fact. A fix has to act on the choice.
- **Z3 paused (user, 25.11.2026): "rules to clingo".** Reading a given rule goes to the solver, per the division of labour. The
  step-choice error is the argument for delegating rule application to clingo. §2.11 (Z12 arm G: the model writes rules, clingo
  derives) tests exactly that; Z3 rests until Z12 S1 has results.

### 2.5 Names as retrieval keys (H13s g3, peer session; vi-mcp-scratchlm baa8d4f)
Pre-registered dose arms: T3 trap recall at 20k steps p100 99.83 %, p90 99.35 %, p50 92.70 %, chance floor p0 4.62 %; H13a′ is
uninformative because p90 fails the pre-registered floor rule (reading accuracy with random names 2.95 %); no arm reads the data
well (T2 ≤ 1.2 %). Fixed names act as keys at every dose at which they occur (A, descriptive).

### 2.6 Retrieval (sym-rag RAG-0 exploratory; RAG-1 pre-registered, sym-rag repository commit e0300c7)
All gold paragraphs in the top 4 on the 400 fresh questions' pool (2,783 titles): BM25 35.0 %, bge-m3 43.8 %, title lookup + one
mention hop 90.5 % (bridge_comparison 74 / 100 vs 0 and 1). On the whole dev pool (54,957 titles) 65.0 % at k = 4 and 91.3 % at
k = 10 (BM25 29.5 / 39.8 %). Symbolic retrieval works because names are keys — the property that hurts induction helps lookup.
End to end (RAG-1, 400 fresh questions, the same reader and solver): symbolic retrieval at k = 4 answers 65.75 % vs BM25 at k = 4
33.0 % (132 vs 1 questions; H-R1 holds) and 5.0 points below the gold paragraphs (70.75 %, 95 % CI −7.25 to −3.0; H-R2 "within
2 points" fails narrowly); a reader-guided second hop reached 68.25 % (exploratory) and, pre-registered on new questions (RAG-1c), 61.5 % vs 56.75 % for
symbolic retrieval alone (19 vs 0, p 2e-6), still 4.5 points below the gold paragraphs (66.0 %, CI −7.0 to −2.25).

### 2.7 Meaning from use in a tiny GPT (W lab, peer session, pre-registered; vi-mcp-scratchlm branch llm-from-scratch, commits b77a8ca … 9203788)
Reported by the session that ran it (A for that session; numbers taken from its commits, not re-computed here): a tiny GPT that sees
k example sentences with the word replaced by a fresh symbol picks the right Wiktionary gloss for held-out lemmas in 43.8 % at k = 3
(chance 25 %; H-W1a holds, exact Wilcoxon over 10 seeds), more with more evidence (k = 3 vs k = 1 +3.2 points, H-W1b), German in the same
direction (3 / 3 seeds); on natural Wikipedia sentences 37.9 % (H-W1x); pretraining on 130 M Wikipedia tokens adds +1.43 points in 10 of
10 paired seeds (H-W2, called WP in the W-lab paper). Meaning from use — reading — is what the small model learns; it fits the division of labour of section 3.
Full write-up: vi-mcp-scratchlm branch llm-from-scratch, docs/W_LAB_PAPER.md (commit 71724b5; the Wikipedia study is named "WP"
there — the name W2 is reserved for the symbol model, not built yet).

### 2.8 Can a model learn to find rules by itself? Our evidence and four systems read in full
**Our evidence (A, §2.3–2.4):**
- As a rule writer, a 0.6B model learns shapes, not predicate choice (17 / 300), and composes no new shape (0 / 200). Self-training
  does not lift it.
- As a guide for the search, the information exists (within-parent AUC 0.77), but a learned guide does not beat its permuted
  control. On blind tasks even an oracle saves only 1.41×.
- On blind tasks the losses lie in the hypothesis space (8 of 25 shapes outside the grammar) and in trivial start-phase hits (9 of
  25). Neither is an ordering problem.

**Four systems that "find" programs or formulas (B: read in full on 23.11.2026, quotes checked against the text at the cited
lines of our copies; supplements not read):**

| system | what proposes new structure | what the full text shows |
|---|---|---|
| DreamCoder (Ellis et al. 2021) | **symbolic** compression, not the network | New library routines come from "finding common program fragments from task solutions" found during waking, by an MDL/Bayesian refactoring objective over version spaces. The neural recognition model only "ranks candidate programs" over the existing library. It is trained on replays and on "dreams" drawn from that library. A routine therefore has to occur in some solution a bounded search already found. Scale: 100–200 tasks per domain, "around a day" on 20–100 CPUs, "approximately a year of total CPU time" to rebuild functional programming from its basis. No logic programs or predicate invention. |
| AlphaGeometry (Trinh et al. 2024) | a **learned** proposer of auxiliary constructions, called only when the symbolic engine stalls | IMO-AG-30 solved, out of 30: DD 7; DD + AR 14; DD + AR + human heuristics 18; DD + AR + GPT-4 constructions 15; AlphaGeometry 25. Ablations: without pretraining 21, without fine-tuning 23. With 20 % of the data 21; with beam 8 instead of 512, 21. Data: about 1 billion random premise sets on 100,000 CPU workers for 72 h gave 500 M proofs, 100 M unique, of which 9 M have at least one auxiliary construction. **Auxiliary constructions are not written by a generator: they are found by traceback as the "dependency difference"** between a proof's premises and the conclusion's objects. Pretraining on pure deduction proofs matters more than fine-tuning on constructions (21 vs 23). The model has 151 M parameters and a vocabulary of 757. Failures trace to rules the engine lacks; no test beyond the generator's vocabulary is reported. |
| FunSearch (Romera-Paredes et al. 2024) | a frozen pretrained code LLM (Codey), no fine-tuning, about 10^6 samples | The LLM writes only one function inside a fixed skeleton. It is "a source of diverse (syntactically correct) programs with occasionally interesting ideas". It works best with "(1) … an efficient evaluator; (2) a 'rich' scoring feedback … (as opposed to a binary signal) and (3) … a skeleton with an isolated part". Proofs fall outside its scope; MAX-SAT's count of satisfied clauses is named as a graded score. Ablation numbers are only in the supplement, which we did not read. |
| LLM-SR (Shojaee et al. 2025) | a pretrained LLM (GPT-3.5, Mixtral, GPT-4o) proposes equation skeletons; BFGS/Adam fits the constants | Ablation on Oscillation 2 (NMSE in-domain / OOD): full 2.12e-7 / 3.81e-5; without iterative refinement 1.01e-1 / 1.81e-1; without the skeleton/optimizer split 0.378 / 0.375; without the problem description 4.65e-5 / 0.0071. The search loop and the split carry most of the gain; the prior helps but is not the core. Pretrained SR Transformers (NeSymReS, E2E) "perform poorly, likely due to limited generalization from their pretraining on common benchmark distributions" to new data. Budgets are counted in iterations (2.5K vs 2M+), not in equal evaluations. |

Systems read at abstract level only (C): NeSymReS (arXiv 2106.06427), E2E (arXiv 2204.10532), TPSR (arXiv 2303.06833), DSR (arXiv
1912.04871), Hypothesis Search (arXiv 2309.05660). All of them keep a search or a verifier in the loop.

**Answers to the two questions raised before the decision:**
- Does DreamCoder's abstraction already "propose helper definitions"? **Partly, and not in the way we need.**
  - It invents helpers symbolically, by compressing solutions it has already found.
  - It cannot invent a helper for a task no search has solved, and its network never proposes one.
  - Its non-learned route is a necessary baseline for us: compress the solutions gp2 and binder found on development tasks into new
    templates.
- What did AlphaGeometry's ablation show? A learned auxiliary-construction proposer adds 11 problems over the engine alone (14 → 25).
  Human-designed heuristics (250 parallel workers for 1.5 h) add 4 (→ 18). The gain survives a fivefold cut in data and a 64-fold cut in beam
  (21 each). Pretraining on the engine's own derivations matters more than fine-tuning on constructions.

**Direction (H, accepted by the user for a pre-registered test on 23.11.2026; not started).** A small model proposes ONE helper
definition when the binder stalls; clingo verifies. The full texts change the design in four places:
1. **Data by traceback, not by a shape generator** (AlphaGeometry):
   - sample random layered programs with invented intermediate predicates, and random worlds;
   - let clingo derive, pick a target, and trace back its dependencies;
   - the intermediate predicates the target depends on are the helper labels.

   This avoids writing our own blind spots into a hand-made shape generator.
2. **Pretrain on derivations first, then train on helper proposal** (AlphaGeometry: 21 vs 23 vs 25).
3. **A graded score for proposals** (FunSearch): e.g. the share of labelled atoms a helper lets the binder explain, not pass/fail.
4. **Baselines at equal evaluations** (LLM-SR counts iterations, not evaluations):
   - random helpers from the same sampler;
   - a DreamCoder-style library compressed from development-set solutions;
   - gp2.

   Primary measure: tasks of a NEW author's blind set that neither gp2 nor binder-G2 solves.

**Phase 0, oracle ceiling (A, descriptive, development data, 3 seeds; research/symbolic_regression/hp/PHASE0.md on sr-binder).**
On the 9 g8e tasks binder-G2 never solved (0 of 27 registered seeds), injecting the reference's helper predicates lets it solve 5
tasks and 14 of 27 seeds at budget 15,000. Three of them are solved by neither gp2 nor binder-G2 today. A perfect helper proposer
would therefore extend what the symbolic engine reaches; whether a learned one gets there is open. In generated tasks the helper
decides in only 1–2 of 20, because binder-G2 materialises each clause size level (about ×14 per level) and runs out of memory first.
The engine after the proposal is the binding constraint, as DD+AR is AlphaGeometry's.

**Named risk:** NeSymReS/E2E failed out of their pretraining distribution (LLM-SR, B), and AlphaGeometry reports no test beyond its
generator's vocabulary. A from-scratch proposer may share the coverage limit that ended binder-G.

### 2.9 How symbolic regression finds formulas, and how a small model could search in its thinking (literature, 24.11.2026)
The user asked on 24.11.2026 two things: how symbolic regression (SR) finds new formulas, and how the 0.6B model could apply SR in
its thinking mode. Four readers read the primary sources in full text, or in part where marked, and checked the arXiv IDs. The
extracted texts are in the session scratchpad; condensed notes are in the VI (insight:4b83cdd6, insight:bbe6a17b,
insight:c65fa7c8, insight:e216ac80). Everything below is level B unless marked; "(H)" marks our own inference.

**What every successful SR system shares** (Schmidt & Lipson 2009; PySR 2305.01582; AI Feynman 1905.11481 and 2006.10782; DSR
1912.04871; NeSymReS 2106.06427; E2E 2204.10532; TPSR 2303.06833; SRBench 2107.14351; Popper 2005.02259; Poppi 2104.14426):
1. **A cheap, exact evaluator that defines what counts as a law.** Hillar & Sommer (1210.7273) show that the evaluator can smuggle
   in the law: Schmidt's fitness, as published, is flat, and the working variant builds in Hamilton's or Newton's equations.
2. **A complexity prior to choose among near-equal fits.** Examples: Pareto fronts, description length in bits, TPSR's
   λ·exp(−l/L), Popper's fewest literals. Without it, fit is not discovery. Operon fits SRBench's black-box sets best yet "struggles
   to recover solutions"; PySR has Acc0.1 56.8 % but symbolic accuracy 8.1 % on LLM-SRBench's LSR-Transform.
3. **Structure separated from constants.** BFGS inside the loop (PySR, DSR), rational snapping (AI Feynman 2.0), model-initialised
   constants (E2E: skeleton + BFGS 0.40 vs model init + BFGS 0.61 Acc0.1). Popper keeps constants out of the clauses.
4. **Decomposition or a reusable library.** Dimensional analysis and separability (AI Feynman); seeded terms cut Schmidt's search
   from 30–40 h to 7–8 h; PySR's hall of fame; invented predicates (Poppi: invention shrinks the smallest solution, which is what
   ILP search cost depends on).
5. **Feedback from failure.** Popper turns each failed hypothesis into constraints (too general → prune generalisations; too
   specific → prune specialisations). NeSymReS, a one-shot decoder, "cannot adjust its posterior … but simply sample again".
- **Shared limit:** the alphabet and bias bound what can be found (missing tanh, length caps, no negation in Popper). None of
  these papers validates a new law within the paper; the evidence is rediscovery. LLM-SRBench (2504.10415) shows LLMs memorise
  known equations, and the best method reaches 31.5 % symbolic accuracy on non-memorised transforms.

**LLMs inside SR** (LaSR 2409.09359; ICSR 2404.19094; LLM-SRBench; SR-Scientist 2510.11661; PiT-PO 2602.10576; EvoTune
2504.05108; Symbolic-R1 2508.09897; FunSearch; AlphaEvolve 2506.13131):
- **The gain comes from the loop.** An external evaluator, constant fitting and selection are in every system; removing evolution
  or feedback hurts:
  - FunSearch finds the full-size set in 2 of 5 runs with evolution and 0 of 5 without;
  - ICSR's seeds-only arm is worse than its loop;
  - LLM-SRBench's data-blind baseline reaches 0–7 % symbolic accuracy.
- **Diversity management matters** (islands, forward-KL DPO in EvoTune).
- **The model prior is a proposal distribution.** Variable names matter (LaSR), and a frozen 8B ≈ GPT-4o-mini inside LLM-SR
  (30.6 vs 31.5 % symbolic accuracy).
- **Small models gain from training inside the loop.**
  - PiT-PO: frozen Llama-3.2-1B in LLM-SR 3.28 → 99.95 (Oscillation 1, Acc 0.001), via GRPO + LoRA on the search's own candidates.
    This holds only in part: on Stress-Strain the 1B stays behind a frozen 8B.
  - EvoTune (1B–3.8B): DPO on pairs from the search beats FunSearch, and beats SFT on the best programs (ReST-EM).
  - Symbolic-R1 (7B): SFT + RL lifts single-shot R² 0.201 → 0.540, and inside the LLM-SR loop to 0.743.
- **Agentic tool use needs size.** SR-Scientist: at 8B and 14B the agent loses to the fixed LLM-SR pipeline even after RL (8B
  15.5 / 20.9 vs 22.5); only at 32B does RL make it win (39.5 vs 30.5).

**Searching inside the thinking** (Stream of Search 2404.03683; Searchformer 2402.14083; DeepSeek-R1 2501.12948; Logic-RL
2502.14768; Cognitive Behaviors 2503.01307; SimpleRL-Zoo 2503.18892; Small Models Struggle 2502.12143; Open-RS 2503.16219; s1;
LIMO; CodeIt 2402.04858; SOAR 2507.14172):
- **Traces with mistakes teach search.** Stream of Search (250M, from scratch) solves 51.3 % on held-out Countdown inputs, against
  25.7 % when trained on optimal paths only. Afterwards STaR/APA raise it to 0.556/0.565. Searchformer (45M) needs fewer data
  with A* traces and bootstraps traces 26.8 % shorter than A*.
- **Prime briefly, then use RL.** About 1,000 primed traces with backtracking unlock RL at 3B, and primed incorrect solutions work
  as well as correct ones (Cognitive Behaviors). Small models learn better from short than from long chains of thought: 0.5B
  19.5 vs 14.8 (Small Models Struggle). RL from a small base is the weakest option: DeepSeek's 7B RL failed, and Distill-32B 72.6
  vs RL-32B 47.0 on AIME. Open-RS (1.5B) degrades after 150–200 GRPO steps.
- **Failed attempts are data.** CodeIt and SOAR relabel every sampled program as the solution of the outputs it actually
  produces. Without relabelling CodeIt stagnates; SOAR's 7B goes from 14.25 with search to 36.25 with learning from its own
  search.

**Checking in the head versus with a tool** (ToRA 2309.17452; ToRL 2503.23383; ReTool 2504.11536; ZeroTIR 2505.07773; PAL
2211.10435; Logic-LM 2305.12295; LINC 2310.15164; SatLM 2305.09656; CRUXEval 2401.03065; T1 2504.04718):
- **Simulating execution in text is unreliable.**
  - PAL: GSM8K 72.0 with the interpreter vs 23.2 when the model "executes" its own code.
  - SatLM: the same specification solved by Z3 69.4 vs in text 54.5 (GSM-Sys).
  - CRUXEval: 1.3B models predict short-function outputs correctly 23–27 % of the time.
  - (H) Judging 30 worlds in the head at 5 % error per world is right only (0.95)^30 ≈ 0.21 of the time.
- **Tool calls inside the reasoning work from 1.5B:** ToRL and ZeroTIR, with tool output masked from the loss and outcome-only
  rewards. But ZeroTIR's 1.5B barely learned to call the tool with a budget of 2 calls; it needs about 4 or more. Nothing has been
  tested at 0.6B.
- **Propose, then an external solver verifies** is the best-supported pattern (Logic-LM, LINC, SatLM, T1). Its weakness: within one
  attempt nothing corrects the error, so sampling or repair rounds are needed.

**What this means for the 0.6B model (H; the order of steps is a proposal, each step needs its own pre-registration):**
1. **The verdict always comes from clingo, never from the model's own simulation.** Held-out worlds are only checked outside the
   trace.
2. **Base: the 0.6B as a proposer inside an external loop.** The loop is propose rules → clingo on the training worlds → a
   counterexample world goes back into the prompt (Popper/gp2-style) → revise, with a complexity prior (fewest literals) and
   held-out verification.
   - Training data: verified teacher programs (T1 step 2, if M1 ≥ 2), our engines' solutions, and relabelled failed programs
     (CodeIt).
   - Then RL or DPO on the loop's own candidates, with a graded clingo reward and a size penalty (PiT-PO, EvoTune).
3. **Then "SR in thinking", measured against step 2 at equal samples and tokens.**
   - The trace is a compact, Stream-of-Search-style protocol: hypothesis → `clingo(train worlds)` call → compact verdict (pass per
     world, missing and extra atoms) → revision or backtracking.
   - Cold start: SFT on about 1,000 short traces from our engines' real searches, with failures, and from the teacher. Tool
     outputs are masked from the loss.
   - Then GRPO with an outcome reward on held-out worlds and a size penalty, a budget of ≥ 4 calls and a short length budget
     (1–2k tokens).
   - Controls: rule-only SFT, empty-think priming, and a data-blind proposer.
4. **Evaluation:** blind tasks of a new author, symbolic equivalence on the exhaustive verify domain plus stress worlds (as now),
   several seeds, and the share of tasks no engine solves as the primary measure.

**Named risks:**
- Nothing in these sources is tested below 1B; SR-Scientist shows agentic use failing at 8–14B.
- Wrong self-checks and reward hacking (Logic-RL lists seven format exploits).
- Collapse after 150–200 RL steps, repetition, and language mixing.
- Trace length grows with problem size (Searchformer: Sokoban traces near 100,000 tokens).
- "Discovery" in the literature is mostly rediscovery.

### 2.10 Teacher measurement (T1) and proposer preparation (L1) for Z2; state 25.11.2026 (in progress)
- **T1, qwen3.8 as a teacher for rule finding** (research/symbolic_regression/t1/PLAN_T1.md, frozen 24.11.2026, amendments 1–5;
  sr-binder 62ef099 … 1a1361c).
  - Design: on the 80 scored development tasks (g8e, G8d-1) the teacher writes k = 8 programs per task and arm. A program counts
    only if it is exact on the training, verify and stress worlds, the engines' "solved".
  - Arms: N, predicate names and data only; D, plus the task's plain-language description, which counts as an upper bound only.
  - Primary measure M1: how many of the 9 tasks no engine solves in any seed arm N solves. M1 ≥ 2 leads to a distillation step.
  - Status: the pilot chose thinking off (think cost 84 s vs 2.4 s per request for +1 verified sample). The registered run started
    24.11. 18:00 UTC on a shared production server with 1 worker and a load guard, and runs until done or 11:00 UTC. The result
    follows here.
- **L1, Qwen3-0.6B as the proposer inside a clingo loop** (docs/PREREG_L1.md, draft, not frozen).
  - Prepared:
    - the loop (counterexample feedback, the engines' "solved", 32 evaluations per task);
    - 79,592 training rows from 20,000 generated tasks (direct, repair and relabelled rows);
    - a new blind set g8g by an independent author (hashes recorded, unread).
  - Not trained. The untrained model solved 0 of 3 development tasks in the loop and did not understand the format.
  - Open for the user: whether L1 runs, whether T1's teacher rows enter it, and whether the rule "small model first, 10 seeds"
    applies.

### 2.11 Thinking in clingo: does an untrained 0.6B model reason better by writing a program? (CT S0, goal Z12)
*Pre-registered (PREREG_CT_S0, vi-mcp-sr-binder branch clingo-think, commit 3234659); result commit b278cf7
(research/clingo_think/RESULT_CT_S0.txt); recounted by the coordinating session (A).*
- **Question.** Instead of deriving in its own text (§2.4), can the model *formalise* — write facts, rules and the goal as a clingo
  program, let clingo derive, read the result and repair the program after the solver's report? S0 measures the headroom of the
  untrained model before any training.
- **Items.** 100 family-D items: 50 multi-step deductions from the frozen R2-small/Z3 generator (CT-own library and item seeds;
  depths 1, 2, 3, 5, 7; 0 overlap with the 3,000 Z3 test prompts; each checked with clingo to have exactly one answer), each in
  the generator's notation (sym) and as English sentences (nl).
- **Arms** (Qwen3-0.6B, greedy, fp32 CPU, 1,536 generated tokens per item and arm; a reply that reaches the budget fails):
  Pcot — step-by-step prose, thinking off (primary comparison); P — Qwen3 thinking mode; C1 — a clingo program with up to three
  calls and a label-free solver report (syntax error, unsatisfiable, no answer, several answers, several models; never the gold);
  C0 — the first call of C1; C1sim — the program plus the answer the model states for it, scored on the statement (PAL §6 analogue).
- **Result (A).** Solved of 100: Pcot 16, P 5, C1 5, C0 5, C1sim 1 (its programs, run by clingo, 4). The pre-registered hypothesis
  C1 > Pcot is **not shown and points the other way**: 3 items only C1 solves, 14 only Pcot (exact McNemar p 0.0127, Holm-adjusted
  0.0509). C1 > C0 (0 vs 0), C1sim-run > C1sim-stated (4 vs 1, p 0.375) and C1 > P (5 vs 5) are not shown either. No cell of depth ×
  surface has C1 above 2/10; on English items C1 solves 0/50.
- **Why (A, descriptive).** Of C1's calls, 77 end in a syntax or grounding error, 37 in several answer sets, 21 without an answer
  atom, 6 run cleanly; 59 of 100 items exhaust the budget (mean 1,343 tokens), and the solver report never led to a repair (C1 = C0
  on every item). The thinking mode fails differently: 76 of 100 replies reach the budget while re-reading facts. A three-item smoke
  run before freezing (C1 2 of 3) was not representative; it is reported in the diary and was not scored.
- **Reading.** Per the pre-registration: the untrained model cannot write the programs, so there is no edge of competence for
  reinforcement learning on this task (a group of samples that are all wrong gives no gradient; Yue et al. 2025 find that RLVR
  does not extend what the base model samples). The next stage (S1, to be pre-registered) teaches the notation first by supervised
  fine-tuning on gold programs and repair traces, with the 2×2 design training × test condition (with/without solver report) and a
  permutation arm. That copying every fact into the program consumes most of C1's budget is a hypothesis (H); S1 tests an arm in
  which clingo receives the facts and the model writes only rules and goal, the protocol LLASP uses for ASP (Coppolillo et al. 2024).

### 2.12 Where reading still loses: a bound and a sampling probe (goal Z1)
*Development evidence on the spent sets fresh3 and fresh4. The step-0 probe was planned and frozen before its reads
(PLAN_Z1_step0.md, sha file next to it). Branch z1-reader, research/symbolic_regression/q1/z1/ (A).*

**Where the loss is.** The deployed reader (R3r + base, primary-first; §2.2) answers 75.5 % of fresh4. Gold triples as the only read
answer 94.5 %; both scores were reproduced per question with the frozen scorer. The 83 questions that reads lose and gold facts win
fall into four classes, by their weakest gold fact:
- missed, stated but not read: 38;
- evidence not stated in the paragraph: 19 (2Wiki's evidence comes from Wikidata with a string-presence check, Ho et al. 2020 §3.2);
- read correctly but answered wrong: 19, about 13 of them a correct entity in another surface form;
- conflict: 7.

**No step over today's two reads can close the gap.** 31 of the 44 missed gold facts are in neither read.
- A relation **type guard** (dates need a digit; places and agents must not be dates or numbers; placeholders dropped) changes
  **0 answers** on both sets. R3r breaks a type in 4 of 4,544 triples, and where the base reader does, the right value is missing too.
  The type-binding loss class of our documentation-QA study (a city bound as a path) therefore does not carry over to 2Wiki.
- A **perfect arbiter** that keeps only the gold-matching candidate of R3r ∪ base, per single-valued relation, is a ceiling that uses
  gold. It gives +0.25 points (fresh4) and +2.0 (fresh3). Voting, verifier questions or a judge choosing between the two readers are
  bounded by that.

**Sampling plus an answer vote (step 0; MBR-READ, after MBR-EXEC [Shi et al. 2022]).**
- Setup: R3r reads every paragraph K = 8 times (T 0.7, top_p 0.8, top_k 20) in one batched call. clingo answers each sampled read
  set, and the majority answer over greedy plus the 8 samples is kept.
- Questions: 198 of fresh4, namely the 98 that PREF gets wrong plus 100 random right ones.
- Result: **10 gains against 1 harm**, about +7 questions per 400 when extrapolated. The frozen threshold was +12, so the probe ends
  as no-go.
- Votes that are unanimous are right in 87 of 123 cases.
- The batched K = 8 call costs about one greedy read (3.47 s per paragraph).
- **Coverage is the finding.** Only 9 of the 42 stated gold facts that neither greedy read contains appear in any sample (21 %).
  Sampling re-orders values the 0.6B reader already writes; it rarely produces the facts it misses.

**Reading (H).** The remaining Z1 gap is a recall gap of the 0.6B reader's distribution, not a selection problem. That points to a
stronger source of reads: a teacher of at most 9B, the BabyLM limit, distilled into the reader. Whether such a teacher covers the
missing facts is the next development probe; its training run needs the owner's decision. Hard constrained decoding is not the
remedy at this size: in a preprint, sub-3B models gained schema validity (61.5 → 100 %) and lost accuracy (19.7 → 11.0 %)
(arXiv 2605.26128).

## 3 Interpretation (H)
At 0.6B (and far more at 0.8M), what the model learns well is a mapping between surface forms it has seen many times — reading
facts, recalling names. What it does not learn from a few thousand rows is a procedure that must generalise over symbols (apply an
unseen rule, choose predicates from data). Those procedures are cheap and exact symbolically. The design consequence is a division
of labour: train the model only for translation, measure translation on fresh data, and give it a solver and a binder. The same holds for handing derivation to the solver from inside the model's reasoning: an untrained
0.6B model does not yet write the formal language well enough for the solver to help (§2.11), so translation into clingo is the
skill to train first.

## 4 Threats to validity
Synthetic worlds for induction (random facts; 2Wiki kinship is the only real relation set); one model family (Qwen3); several
analyses on development sets are exploratory and are marked; the pipeline's goal templates and the kinship teacher come from 2Wiki
train; 2Wiki gold is incomplete for precision; our own errors corrected during the week are listed in the research log
(SYMBOLIC_REGRESSION.md: corrections of 21.11.2026, e.g. the object-form claim, the father-density count, five time stamps). A
descriptive lead on one fresh set (R3r alone 73.0 %) did not replicate on the next (70.25 %, PREREG_R3r2) — single-set differences of
2–3 points are within noise here, which is why every claim above was re-tested on unseen questions. Blind rule-induction sets come
from one author each, in everyday domains; censoring at 15,100 evaluations hides how far unsolved runs were; binder-G2 runs under a
3,600 s wall limit and a 6 GB memory scope that bind on a few tasks (all runs of one arm stay on one host for that reason).

**Research history of §2.8 (23.11.2026).** A first version was written from abstracts only (level C), as a separate file. That
duplicated this paper, so it was reverted (commit 936a17d, reverted by f25168f on sr-binder). Before the test was decided, the four
key systems were then read in full. This changed the plan in two places:
- DreamCoder's network does not propose helper definitions; its library comes from symbolic compression of found solutions. This
  is now a baseline, not the precedent.
- AlphaGeometry's auxiliary constructions come from traceback over random premises, not from a hand-written generator. This
  replaces our first idea, a generator that composes helper shapes.

The abstract-level version had also cited AlphaGeometry's 100 M examples from the DeepMind blog. The paper gives 100 M unique
examples, of which 9 M have auxiliary constructions.

## 5 For a BabyLM submission (H)
The non-competition track fits sections 2.3–2.5 (what a small LM should and should not be trained for; names as retrieval keys).
A competition entry would need an English LM within 100 M words; the binder/solver are tools, not training data, and their use at
evaluation is outside the BabyLM benchmark format.

## References (level B unless stated)
- Ho, Nguyen, Sugawara, Aizawa 2020: Constructing A Multi-hop QA Dataset for Comprehensive Evaluation of Reasoning Steps, COLING
  2020, 6609–6625; arXiv 2011.01060 (verified 21.11.2026 via arxiv.org/abs/2011.01060).
- Zelikman, Wu, Mu, Goodman 2022: STaR, arXiv 2203.14465.
- RLIE 2025: arXiv 2510.19698. — LLM-automated language bias for ILP 2025: arXiv 2505.21486.
- Isik et al. 2025: interchangeable token embeddings, arXiv 2410.17161. — CREAM 2022: arXiv 2207.11104.
- Cropper & Morel 2021: Learning programs by learning from failures (Popper), Machine Learning 110:801–856; arXiv 2005.02259
  (verified via arxiv.org/abs/2005.02259).
- Quinlan 1990: Learning logical definitions from relations (FOIL), Machine Learning 5:239–266, doi 10.1007/BF00117105 (verified via
  mlanthology.org/mlj/1990/quinlan1990mlj-learning).
- Tafjord, Dalvi, Clark 2021: ProofWriter: Generating Implications, Proofs, and Abductive Statements over Natural Language, Findings of
  ACL-IJCNLP 2021, 3621–3634; arXiv 2012.13048 (verified via aclanthology.org/2021.findings-acl.317).
- BabyLM 2026 guidelines: https://babylm.github.io/guidelines.html (read 20.11.2026).
- Ellis, Wong, Nye, Sablé-Meyer, Morales, Hewitt, Cary, Solar-Lezama, Tenenbaum 2021: DreamCoder: Bootstrapping Inductive Program
  Synthesis with Wake-Sleep Library Learning, PLDI 2021, 835–850, doi 10.1145/3453483.3454080; full text read from arXiv 2006.08381v1
  (main paper; the supplement was not read).
- Trinh, Wu, Le, He, Luong 2024: Solving olympiad geometry without human demonstrations, Nature 625:476–482, doi
  10.1038/s41586-023-06747-5 (full text incl. Methods; Extended Data figures only as captions).
- Romera-Paredes et al. 2024: Mathematical discoveries from program search with large language models, Nature 625, doi
  10.1038/s41586-023-06924-6 (main text and Methods; Supplementary Information, with the ablations, not read).
- Shojaee, Meidani, Gupta, Barati Farimani, Reddy 2025: LLM-SR: Scientific Equation Discovery via Programming with Large Language
  Models, ICLR 2025, arXiv 2404.18400 (full text incl. appendices; figure values not in the text).
- Gomes, Selman 2001: Algorithm portfolios, Artificial Intelligence 126:43–62. — Xu, Hutter, Hoos, Leyton-Brown 2008: SATzilla, JAIR
  32:565–606 (both read for PREREG_portfolio_g8f).
- Gao et al. 2023: PAL: Program-aided Language Models, ICML 2023, arXiv 2211.10435 (§6 read: model "executes" its own program).
- Yue et al. 2025: Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?, arXiv 2504.13837
  (full text read 24.11.2026).
- Zhang, Neubig, Yue 2025: On the Interplay of Pre-Training, Mid-Training, and RL on Reasoning Language Models, arXiv 2512.07783
  (abstract and §1 read 24.11.2026).
- Coppolillo, Calimeri, Manco, Perri, Ricca 2024: LLASP: Fine-tuning Large Language Models for Answer Set Programming, KR 2024,
  arXiv 2407.18723 (full text read 25.11.2026: Gemma 2B, QLoRA SFT on about 3.7 M template tuples; programs checked with clingo
  against gold on the gold instance's facts).
- Level C (abstract only): Biggio et al. 2021, NeSymReS, ICML, arXiv 2106.06427; Kamienny, d'Ascoli, Lample, Charton 2022, E2E,
  NeurIPS, arXiv 2204.10532; Shojaee et al. 2023, TPSR, NeurIPS, arXiv 2303.06833; Petersen et al. 2021, DSR, ICLR, arXiv
  1912.04871; Wang et al. 2024, Hypothesis Search, ICLR, arXiv 2309.05660.
- Z1 (§2.12), full text read 25.11.2026: Shi, Fried, Ghazvininejad, Zettlemoyer, Wang 2022, Natural Language to Code Translation with
  Execution (MBR-EXEC), EMNLP, arXiv 2204.11454 (Table 2 and §4.4.3 checked in the PDF); Ray 2026, The Constraint Tax, preprint,
  arXiv 2605.26128 (main sections). Further sources for Z1 and their reading level: research/symbolic_regression/q1/z1/LITERATURE_Z1.md.
