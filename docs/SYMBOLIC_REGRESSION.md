# Symbolic regression over rules — research log

Branch `symbolic-regression`. Code and data: [`research/symbolic_regression/`](../research/symbolic_regression/) and
[`research/blind_tasks/`](../research/blind_tasks/). Paper sections: [EXAPTATION_PAPER.md](EXAPTATION_PAPER.md) §5.8–§5.10.
Why we do it: README, section "Symbolic regression" (the quotes of Schopenhauer, Jobs and Einstein).
This log says what was done, in what order, why, what came out and where the evidence lies. Newest decisions at the end.

## The idea in one paragraph
Symbolic regression searches the space of formulas for one that fits data and stays short (genetic programming; AI Feynman; PySR).
We search the space of **rule sets** instead: candidates are ASP rules in clingo-object notation, mutated, crossed, selected by how
well they explain example worlds and by size. A found rule set is a mechanism — an object with edges (derived from, equivalent to,
solves). The question behind it: can a VI find new laws in data (genius: a target nobody else sees) rather than fit what it was shown
(talent), and can mechanisms learned for one purpose be reused for another (exaptation)?

## Timeline (19.–20.11.2026)

| step | question | result | evidence |
|---|---|---|---|
| G8 | does a library of mechanisms speed up an evolutionary rule search? | **invalid by construction** — an independent review found the tasks were renamed library blocks, the random arm crippled, hits were lookups, "solved" unsound; stopped at 119/240 runs | paper §5.8; `g8/` |
| G8b-0 | can the search find known mechanisms from data alone, without a library? | **42 of 60 runs**, 5 of 6 mechanisms (an invented recursive closure among them; one law shorter than the reference); lineage_root never | paper §5.9; `g8b/result_G8b0.json`, `note_G8b0.md` |
| Popper baseline | how does an established ILP system do on the same tasks? | Popper v5.0.1 native 20/60, with assists 40/60; dependency_cycle 0/10 (GP 10/10) — Popper's optimal size-10 program was not general | VI insight (Popper baseline, 19.11.2026) |
| G8b-1 | exaptation, fairly: 33 tasks written blind to the library; library vs rewired vs relinked vs random | **library helps by reuse as it is** (lookup 25.7 % vs 10.4 %, Holm p = 0.0003); **not as a seed for modification** (H1 ratio 1.10, CI [0.93, 1.24] excludes 1.5); random rules not worse in total cost. Provenance (after the data): searched solutions keep the origin's structure from the true block (48 %) barely more often than from its rewired copy (46 %) — the structure comes from the task, not the lineage | paper §5.10; `g8b/prereg_G8b1*.md`, `result_G8b1*.json`, `robust1.json`, `provenance1.json`, `runs1.tar.gz` |
| G9 | do rules found over the VI's own experiences predict future failures? | **no** (one agent instance (A), 3 seeds): every seed fails the test-period gate; a 2-leaf tree beats it (F1 0.066 vs ≤ 0.032). Cause: selection on one validation day picked a predictor that drifted (0 of 75 on the test period); 69 training failures only | `g9/` (code only — the data are private experiences and stay local) |
| G9 all instances | the same over every instance's experiences (train 5,727 / 1,014 failed, test 7,379 / 394) | all 3 seeds pass the test gate (lift 6.5) but only by finding the best single rule: 'the action comes from instance i2' (seed 0 identical to it: 310 / 588 / 84; seeds 1-2 +0.001 to +0.005 F1); a depth-1 tree splits on the instance too. No mechanism, only an instance's base rate — the strict gate (beat the best single rule AND the tree) is not passed in substance | `g9/` (results local: coded instances) |
| G9b | same data, selection fixed: MDL (size + FN + FP) on two validation days, "no rule" always a candidate, the same rule for every method | pre-registered (predictions: mostly abstain; no non-abstaining choice fails the test). **All abstain** — single rule, tree and all 3 GP seeds: the best non-empty GP candidate costs 63 against 59 for 'no rule'. P1 confirmed; P2 not violated but untested (nothing was chosen). The selection now refuses a law it cannot pay for; whether it ACCEPTS a true law needs data with more failures or after 16.11. | `g9/prereg_G9b.md`, `.sha256`, `g9b.py`, `g9b_baselines.json`, `g9b_gp_summary.json` |
| G8c draft + review | a proposer trained on dreams (the user's MTP idea, DreamCoder-style): does it make the library a seed for modification? | independent review: **not runnable** — LP vs L cannot separate task information from a task-independent operator prior (operators change the program 20-93 % of the time; no-op children are free clones), block proposal nearly inert and biasing the excluded pairs, dream labels include no-ops, the gate passes trivially, tasks and seeds no longer blind | `g8c/prereg_G8c_draft.md`, `REVIEW_1_summary.md` |
| G8c-0 | oracle ceiling: does even a prior that KNOWS each task's true edit operators speed gp2 up by 1.5? | **fails its pass rule**: median ratio 1.40 < 1.5, although the oracle beats the permuted prior (p = 0.0013) and the mean prior (p = 0.034) — the information is real, a static reweighting of gp2's operators is too weak (by edits needed: 1.20 / 1.24 / 2.77 for k = 1/2/3). Decision: abandon static per-task priors; a proposer must see the candidate program (G8d). Limit: half of the dreams were solved by start-phase lookup | `g8c/prereg_G8c0.md`, `score0.py`, `result_G8c0.json` |
| G10 (plan) | vector-symbolic binding (VSA) as the representation of the search — the user's idea 'binding attributes to entities via vectors is the approach to realise our symbolic regression' | research: nobody has encoded ASP/Datalog rules in VSA or retrieved rule libraries by it; review 1: redesign (24 blocks give no scarcity, trivial gate, inert injection); v2 with 500 distractors, rule-level baselines and an oracle gate under review | `g10/PLAN_G10*.md`, `REVIEW_1_summary.md` |
| G8d plan | a CANDIDATE-conditioned proposer (after G8c-0): which representation of the current program predicts the edit that improves it — and does it need an embedding model? (user question 19.11.) | text embeddings ruled out by design (they embed names, identifiers are anonymised); computed vectors first: behaviour F, exact structure S, its VSA projection V; an own contrastive encoder only if S/F do not transfer. Two self-reviews against gp2 (the user stopped the independent review) | `g8d/PLAN_G8d.md` |
| G8d step 0 | log every edit without changing the search | `gp2_log.py` replays 12/12 stored runs bit-identically; 660 runs logged (33 tasks × 10 seeds × arms Z, L), 1.12 M clean single-edit children | `g8d/gp2_log.py`, `replay_check.py` |
| G8d-0 | does a representation predict which single edit improves THIS parent? (gate frozen before the data; AUC within the parent, because the pooled AUC rewards parent headroom; amendments 1–2: memory, ≤ 300 records per run, exact rank AUC — byte-identical on the pilot) | **pass**: within-parent AUC N 0.632, W 0.704, S 0.720, F0 (free behaviour) 0.746, **SF 0.770**; margin +0.066, task-bootstrap CI [0.017, 0.115]; 83,733 edits, 31 tasks. Behaviour carries most, structure a little; V not built (it would project S, whose own gain is +0.016) | `g8d/g8d0.py`, `result_G8d0.json` |
| G8d-0b | ceiling: does an oracle that knows the improving edit make the search ≥ 1.5× cheaper on the 12 hard tasks? | running (gp2_arms.py --policy O1; U = the stored runs, bit-identical) | `g8d/gp2_arms.py`, `PLAN_G8d.md` |
| H13s (with the philosophy training) | names as retrieval keys: a fine-tuned model recalls the seed instead of translating (renamed predicates come back with the seed's names); does rule induction with names that carry nothing fix it? Tiny GPT from scratch, arm N (fixed name per structure) vs A (random names per example), name trap | pilot (1 seed, 5k steps): **N memorises name → rule (seen 100 %, new 0 %) and in the trap writes the FOREIGN rule in 95.7 %**; A follows the data (2.5 %) but solves only 3–7 % → pre-registered gate failed, grammar reduced, pilot repeated | VI (internal); the tiny-model lab is a separate project |
| A2 | external evidence: our search on Popper's own example tasks | running: 32 of 51 tasks usable (19 need lists or Prolog rules); Popper 3 reps, GP 5 seeds, 600 s; protocol hashed before the run | `a2/PROTOCOL_A2.md`, `.sha256` |

## What the results mean (synthesis, a hypothesis)
Read as data, the results compress to one law: **the search finds, the selection decides.** Every failure so far was in the
acceptance criterion, not the generator: an unsound "solved" (G8), a colour list accepted as a law (G8b-0, caught by stress worlds),
a program that fits all examples but is not the law (A2 smoke test, kinship-pi: ours size 8, Popper's law size 7 with an invented
`parent`), a rule chosen on one day that drifted (G9). The acceptance criterion decides whether the search rewards talent or genius.

And: **a library without a learned proposer acts only as a lookup** (G8b-1). This agrees with the literature:
- DreamCoder (Ellis et al., [arXiv 2006.08381](https://arxiv.org/abs/2006.08381)): library learning and a neural recognition model
  (trained on "dreams" sampled from the library) each add substantially; the library alone is not the whole gain.
- Berlot-Attwell, Rudzicz, Si ([arXiv 2410.20274](https://arxiv.org/abs/2410.20274)): in LLM library learning (LEGO-Prover, TroVE)
  learned functions are rarely reused; the gains came from self-correction.
- LaSR (Grayeli et al., NeurIPS 2024, [arXiv 2409.09359](https://arxiv.org/abs/2409.09359)) and FunSearch (Romera-Paredes et al.,
  Nature 625, 2024): the gains come from a proposer conditioned on concepts or on the best programs so far.
- MaxSynth (Hocquette et al., AAAI 2024, [arXiv 2308.09393](https://arxiv.org/abs/2308.09393)): choose by description length
  (size + false negatives + false positives); choose from a Pareto front on a separate validation partition
  ([arXiv 2109.00238](https://arxiv.org/abs/2109.00238)).

## Decisions (with the user, 19.11.2026)
1. All symbolic-regression work lives on this branch (`symbolic-regression`), never directly on built-for or main.
2. Fix the selection first: MDL acceptance (size + FN + FP) and validation over several time windows (G9b). gp2 stays frozen
   (its hash is part of the G8b-1 and A2 protocols); the change goes into a new version.
3. The library is useful as a co-option index (find an existing mechanism by predicate mapping before searching) — proven by H2.
4. The user's idea of an MTP-like proposer becomes a DreamCoder-style recognition model trained on dreams, tested first on the
   from-scratch tiny model, pre-registered as G8c with H1's measure, reviewed independently before any run.
5. Rules to weights: (B1) rules as router features, (B2) one weight per rule (LPMLN), (B3) KBANN-style compilation into the tiny
   model with rule-initialised vs structure-only-random vs random arms (sources in the VI, topic rules-to-weights).
6. Identifiers: a learned proposer sees only anonymised identifiers (fresh random renaming of predicates, constants and block ids per dream / task), with a speaking-names control; real-data values stay coded, decode tables local, no code next to a plain name (`research/symbolic_regression/g8c/DESIGN_RULES.md`; user question 19.11.2026).

## How children and animals learn words — what it means here (research 20.11.2026)
The user: children learn their first words as symbols ("apple", "car"), animals learn intuitively — "we are training a pet".
- **Cross-situational learning** (Smith & Yu 2008, [Cognition](https://cogdev.sitehost.iu.edu/labwork/Cognition_Smith_Yu2008.pdf)):
  12–14-month-olds learn word → object from statistics over individually ambiguous situations; a generic network learns such
  mappings from 61 h of one child's head camera (Vong et al., Science 2024, [doi](https://doi.org/10.1126/science.adi1374)).
  → H13 arm A is this mechanism: a name means only what the statistics over the worlds say.
- **Underdetermination** (Quine 1960, "gavagai"): evidence admits several readings → four worlds often did not identify a rule
  (H13 amendment 1: six); our answer is parsimony (MDL, G9b) and fresh check worlds.
- **Symbol grounding** (Harnad 1990, [paper](https://www.southampton.ac.uk/~harnad/Papers/Harnad/harnad90.sgproblem.html)): symbols
  need grounding outside the symbol system → the worlds and the solver ground clingo-object; arm N learns a "dictionary" meaning
  and falls into the name trap.
- **Learned attention and learning to learn** (shape bias, Landau, Smith & Jones 1988; Harlow 1949) → G8d-0: behaviour + structure
  predict the helpful edit; H13 reports a learning curve.
- **Fast mapping by exclusion** (Kaminski, Call & Fischer 2004, the dog Rico; contested: Griebel & Oller 2012, "slow mapping" in a Yorkshire terrier, PMC3281824 — corrected 20.11.2026, earlier wrongly named Pilley & Reid) → H13 test set T5.
- **Complementary learning systems** (McClelland et al. 1995; Kumaran, Hassabis & McClelland 2016): fast episodic + slow interleaved
  learning with replay → the VI (objects) + sleep + fine-tuning; replay against forgetting = release 0.70.9.
- **Prediction error** (Schultz 2016) → learn where the outcome differs from the expectation (GRPO with solver reward; oversampling
  rare cases).
- **Caution**: curricula modelled on children helped little in BabyLM ([findings](https://arxiv.org/abs/2504.08165)).

## Symbol scripts (20.11.2026)
clingo-object is a symbol script like Chinese or hieroglyphs, with one difference: a symbol means exactly what its rules define (the
solver checks it). In logographic scripts a sign is polysemous and context decides (ChineseBERT fuses glyph and reading,
[arXiv 2106.16038](https://arxiv.org/abs/2106.16038)); Egyptian determinatives are silent class signs
([arXiv 2407.00475](https://arxiv.org/abs/2407.00475)). Polysemy belongs BETWEEN contexts (exaptation = a mechanism with a second
function), never within one program. Planned: H13 arm D (anonymous names + class marks) and opaque added tokens for Qwen.

## Decisions (with the user, 20.11.2026)
1. Working hypothesis (not a finding — see the review of 20.11.2026 below): names act as retrieval keys; the model itself is trained on symbolic regression (rule induction) with names that carry nothing (H13).
2. Symbol scripts: arm D and opaque tokens are in the plan (H13 pre-registration, "planned extension").
3. BabyLM: we take part with this approach and publish there when done. The 2026 edition (EMNLP, October) is over; target the next
   edition. Rules read: generated data counts toward the word budget (≤ 100M / 10M words), teacher models ≤ 9B, an English
   Transformers model with log-likelihoods for the competition; non-competition workshop papers are accepted
   ([CFP 2026](https://arxiv.org/abs/2602.20092), [guidelines](https://babylm.github.io/guidelines.html)).

## Reproducing
- Python with clingo and the repository on the path (`VI_MCP_REPO=<repo>`; the scripts default to the repository root).
- G8b-1 scoring: `cd research/symbolic_regression/g8b && tar xzf runs1.tar.gz && python score1.py` reproduces
  `result_G8b1.json` exactly (checked 19.11.2026). `robust1.py` re-checks every first solution on 1,000 new worlds.
- Blind tasks: `python research/blind_tasks/check.py` (33 tasks, kinds a/b/c 11/11/11).
- A2: `POPPER_EXAMPLES=<Popper v5.0.1 examples/> a2/run_a2.sh` (needs the Popper container image; see the VI insight on the
  Popper baseline for its Dockerfile).
- `SANITISED.json` lists the files whose local paths were made relative for this repository, with the original hashes that the
  pre-registrations name.

## Open
- A2: results pending.
G9b: abstains everywhere — next test needs data where a law can pay (more failures, or experiences after 16.11.2026: a new production copy, the user's decision).
- G8d-0b running; then G8d-1 on a NEW blind task set (arms U, P, C, Cs, O1). G10 merged into G8d (V only if S carries enough). B3 (rules → weights): to be pre-registered.
- H13s: pilot with the reduced grammar; if A learns the task, 10 seeds per arm, then anonymised induction rows for the Qwen kit (kit35). Next idea (user 20.11.): the same verifier loop for Python — clingo as the specification level, Python as the execution level.

## Independent review, 20.11.2026 (the user asked for it; the reviewer read files only)

The reviewer got the plan, the H13 pre-registration and its generator, this log, both papers and the kit-34 builder, plus run 34's
numbers; it did not get our conclusions. Each finding below was **re-checked by the coordinating session** and is marked with the result.

| # | Finding | Re-check |
|---|---|---|
| 1 | H13 T2 "held-out structures" is largely not held out: `canon()` (h13data.py:71-73) hashes arities + text of the sorted rules, with no variable renaming or slot permutation, although PREREG:15-16 claims both | **confirmed.** Own syntactic canonical form on data2: 19/50 held-out structures equal a training class (30/50 if unused distractor predicates are dropped); the reviewer's normaliser counts 27/50 and 43/50, and the H13 peer session re-counted independently and got exactly 27/50 and 43/50 (my rougher normaliser undercounts). Only 7 held-out structures (56 of 400 T2 items) are syntactically new; the 200 training structures fall into 88 classes, so arm N is already partly anonymised |
| 2 | For arm A, T3 is an ordinary T1 item, so "A > N on T3" is nearly the gate question; arm N can reach zero loss without reading worlds — shortcut by construction, not proof that a model prefers names when it can read | design argument, accepted; proposed: dose arms with binding consistency p ∈ {1, 0.9, 0.5, 0} |
| 3 | Pool is 108 words, not 120; the head name is not a perfect key (94 head names for 200 structures) | **confirmed** (len(WORDS) = 108) |
| 4 | "Names are retrieval keys" (H12) overstated: for P6/P7 the trigger is the block shape (author → writer still yields "author") | accepted; headline §5.27 and decision 1 reworded as hypothesis; EXAPTATION §5.11 sentence removed |
| 5 | Run 34's p67 gain (7/20 → 15/20, 8:0 discordant) is near-train (kit34 trains renamed seed blocks) and confounds R rows, V rows and +900 rows | accepted; needs seed 43 (running), a +900-neutral-rows control and renamed NEVER-trained blocks (P8–P13 of 1.3.0) |
| 6 | Arity errors of run 34: concrete source (`rename_block` draws names without arity), but 2 errors, p = 0.49 → hypothesis | accepted (kit33c already had 44 multi-arity names and wrote 18/18) |
| 7 | T5 tests partial renaming, not exclusion (new word from the trained pool, old name not in the prompt, recall measure over-counts any fact-less rule) | accepted; rename T5 and design a real exclusion test |
| 8 | Underdetermination unmeasured: nobody checks that the gold rule is the only rule consistent with the shown worlds | accepted |
| 9 | Analogies: cross-situational learning fits arm N (constant pairing), not arm A; Harnad's grounding is non-symbolic (worlds are symbols); symbol scripts / "pet" are decoration | accepted; FT §5.29 now says the design came first and the analogy is loose |
| 10 | Citations: PMC3281824 is Griebel & Oller 2012 (not Pilley & Reid); arXiv 2305.19928 is unrelated (sequence labelling); 2510.03178 says "memorisation of naming patterns", not "retrieval keys" | **confirmed** (Europe PMC, arXiv API); corrected in both papers and here |
| 11 | ASPBench does not argue against opaque tokens for our goal; our own pilot does: in a from-scratch model every word is opaque and arm N still recalls 95.7 % — fixed binding, not English meaning, causes recall | accepted; proposed 2×2 token kind × binding (fixed/variable) instead of three arms |

**Most informative next experiment (reviewer):** evaluation only on the existing 33c/34 checkpoints, 2×2 minimal pairs — seed names
vs all fresh names × seed block shape intact vs one rule logically changed — measuring whether the output follows the prompt or the
seed; plus the same on never-trained blocks P8–P13. **Falsifies "names are keys"** if seed names with a changed rule are translated
correctly while fully renamed intact blocks still yield seed prose (then the shape is the key).
BabyLM: Qwen3-0.6B is pretrained (outside the word budget) and the small model learns no natural language and has no log-likelihood
evaluation — only a workshop paper outside the competition fits; frame it as "binding variability as a data intervention against
shortcut recall, solver-checked", with a dose curve and a clean split.

## W lab: symbols from Wiktionary (20.11.2026)

**Goal (user, 20.11.2026):** "ein LLM auf Logik aufbauen statt aufs Nachplappern" — a model that researches through a SearXNG
instance and answers questions, with the logic in symbols and symbolic regression. Decision: Qwen3-0.6B reads and translates
first (question → goal, snippet → facts, result → answer), clingo reasons with rules found by symbolic regression; an own
from-scratch model (BabyLM-like) follows with the same symbolic interface. First step: the lexicon.

**Data.** kaikki.org wiktextract raw file (enwiktionary dump 2026-10-01, extracted 2026-10-30; Ylonen, LREC 2022), filtered to English:
865,721 senses of 614,416 words without inflected/alternative forms and proper names; split by word (10 % never trained, 0 overlap).
Lexical relations are sparse except synonyms: hypernyms on 6,914 senses (+6,375 entries), synonyms 548,337 links on 100,540 senses.
Synonym union over words collapses polysemy: 17.7 % of 147k words in one component (mutual links only: chains up to 2,592) →
symbols must be per sense.

**Genus = logic inside the definition.** Two thirds of noun glosses have the Aristotelian form genus + differentia; the extracted
genus gives 351,989 `is_a` and 7,248 `part_of` facts (hand checks of 2 × 40 samples: ~85 % correct; misses are named in the VI).
The word graph is shallow (97 % depth ≤ 2) and has one circular core of 5,380 words — as dictionaries do: Vincent-Lamarre, Harnad
et al. (2016, arXiv 1411.0129) find a Kernel of ~10 %, a strongly connected Core, and a minimal grounding set of ~1 % from which
all other words can be defined. For "logic instead of parroting": only that grounding set has to be learned from data; every other
word is a rule over grounded symbols.

**SearXNG** (JSON API): 3 of 4 test queries answered by duckduckgo only (google, brave, startpage, wikidata blocked) → every
training and evaluation run replays cached search results.

Related: neural parsing + ASP reasoning (Yang, Ishay & Lee, Findings ACL 2023, arXiv 2307.07696); search calls trained by RL
(Search-R1, arXiv 2503.09516); proposal + verification beats direct program generation in rule induction (arXiv 2306.02797,
2509.01016); rule mining on facts (AMIE, AnyBURL); feature norms as differentiae (McRae 2005, Buchanan 2019).

## H13s pre-study (g1 diagnostic + g2 pilot, 20.11.2026; caveat: T2 was not held out, see the review above)

Seed 0, tiny GPT (0.83M), g2 at 5k of 20k steps: arm N (fixed names) — T1 93.8 %, T2 0.3 %, name trap T3 recall **84.3 %**,
T2-new 0 %; arm A (random binding) — T1 6.8 %, T2 13.3 % (class seen 15.4 %, **new 0 %**), T3 recall 3.7 %, renaming invariance 20.5 %
(N 0 %). g1 arm A continued to 20k: T1 15 %, T2 3.7 %. T5's old behavioural recall measure overstates recall (A 33.5 % "recall" with
0 % textual recall) — the review's objection holds empirically. Reading: names become retrieval keys at once; varied binding removes
recall but the small network does not induce rules for unseen behaviour classes. Working hypothesis for the research model: new rules
come from the symbolic search (the network proposes, the solver decides), not from the weights alone. g3 (clean split by behaviour
class, dose arms p100/p90/p50/p0, 40 runs on the AMD GPU since 20.11. 16:01 UTC, ~0.38 s/step with 4 in parallel) tests it.

## G8d-0b — the ceiling of conditioned proposals: PASSED (20.11.2026)

Spec fixed before the runs (PLAN_G8d.md): oracle proposer O1 (one-step lookahead over up to 24 candidate edits per mutation, its
probe evaluations free by design), arm Z, seeds 0–9, budget 15,000, against the stored uniform runs (U = runs1 Z) on the 12 hard
development tasks (median U search cost ≥ 300); cost = evaluations to the first exact solution, unsolved = 15,000 (censored).
**Median over tasks of median-U / median-O1 = 2.76 (gate ≥ 1.5); 9 of 12 tasks ≥ 1.5** — bank_fraud 14.5×, hospital_exposure 8.1×,
logistics_served 5.5×; no gain on garden_crowded (both mostly unsolved), sports_ranking 1.09 (U 0/10 solved, O1 5/10 — censoring
understates it), games_rps 1.32. With G8d-0 (the information is there: within-parent AUC 0.77 for structure + behaviour) this earns
G8d-1: a learned conditioned proposer, confirmatory on a new blind task set, C vs its permuted control Cs as the primary contrast.

## W lab: D0 → R1, can the model understand a document and give it back? (20.11.2026)

200 Wikipedia paragraphs (2WikiMultiHopQA dev, Apache-2.0), Qwen3-0.6B on an RTX 3070: read (paragraph → facts over 34 Wikidata
relations), write (own facts → text), reread. D0 = untrained with 2 worked examples (zero-shot it fails the format: 0 of 11).
R1 = LoRA r64, 2 epochs on 8,000 rows whose targets are every Wikidata claim of the entity that is STATED in the paragraph
(copy rule; lesson of GraphNarrative: mismatched targets teach invention), measured zero-shot with identical prompts.

| | D0 (2-shot) | R1 (0-shot) |
|---|---|---|
| understand recall | 0.676 | 0.706 (p = 0.44) |
| reproduce recall | 0.549 | **0.676** (McNemar 37:11, p = 0.0002) |
| extracted facts stated in the text | 0.648 | **0.976** |
| own round trip (Jaccard) | 0.435 | **0.915** |
| answer tokens, 600 calls | 80,100 | **33,428** |
| wall time | 1,371 s | **788 s** |

Training on text-faithful targets nearly removes invention and stabilises the round trip; recall moves little. (The lever named
here first — all 29,822 rows — turned out WRONG, see below.)

**R1-full (all 29,822 rows) is worse on the round trip (correction).** Same 200 paragraphs, paired per gold fact: understanding
unchanged (142 vs R1's 144, p = 0.82), reproduce 123 vs 138 (discordant 5:20, McNemar exact p = 0.004), Jaccard 0.834 vs 0.915;
facts stated in the text 97.9 % in both, 42.6 tok/s. 18 of the 20 extra losses are the reread of the model's OWN template sentences
("Puka Puka is in Peru." → country_of_citizenship; "The father of Jake Scott is Ridley Scott." dropped): the read rows only ever
contain Wikipedia paragraphs. Fix for the next kit: cycle rows, the templated text read back into the same facts (CycleGT-style). Related: GenIE (constrained extraction), REBEL, CycleGT (cycle training), round-trip consistency (ACL 2026 Industry).

## Q1: the logic of multi-hop questions — induced, then checked against gold evidence (20.11.2026, interim)

**Rule induction from data.** gp2 searches kinship rules for 2WikiMultiHopQA's inference questions from TRAIN data alone (no
reference program): a world = 4 target-relation questions + 4 distractor questions, people renamed e1…en, entity-disjoint
sampling (otherwise true but unlabelled pairs across one family make the closed-world gold wrong), questions whose two evidence
triples are not linked dropped (counted). Counterexamples come from held-out DEV worlds. First batch (relations with ≥ 90 train
questions, seeds 0–2, budget 15,000): every finished run solved and found the intended chain, e.g.
`target(V0, V1) <= father(V0, V2) & mother(V2, V1)` (paternal grandmother); accuracy of the first rule on all dev questions of the
relation 0.996–1.000. One seed found an equivalent recursive form (`inv1`), which the solver evaluates identically.

**Logic upper bound** (`q1_oracle.py`): gold evidence triples and the gold relation chain, every inference step a clingo rule
(chain join; `#min`/`#max` over parsed dates; lifespan; `#count`; equality of meanings; the induced kin rules). Python only reads:
entity linking (normalised names, token Jaccard ≥ 0.75 or containment, never across different numbers — "16th Earl" ≠ "15th
Earl") and date parsing. The operator (min/max/same/count/lifespan) is read from the question after removing the candidate names
— otherwise "The **Last** Night of Scheherazade" turns "born first" into max.

| dev type (n) | logic upper bound | what the misses are |
|---|---|---|
| compositional (5,236) | 97.8 % | names of one person with no overlap ("Theoderic"/"Theodoric", "Mikheil"/"Michael") |
| comparison (3,038) | 99.4 % typed sense (97.4 % first sense, 95.1 % without lexicon) | ties at year precision, Britain vs United Kingdom |
| bridge_comparison (2,751) | 99.2 % typed sense (98.6 % first sense, 97.8 % without) | nicknames ("Joe"/"Joseph De Grasse") |
| inference (1,549) | 76.7 % (94.7 % of the questions with an induced rule) | 294 questions without a rule yet (second batch running) |
| **all (12,576)** | **95.9 %** | |

**Word meaning decides equality.** "Are X and Y from the same country?" fails on spelling: Canadian/Canada, American/United States,
Greek/Greece. A lexicon step reads the first Wiktionary sense of each value ("Of, belonging to, or relating to Canada" → Canada;
"A citizen or national of the United States of America") into `mean(value, place)`, and equality becomes a rule over meanings.
First sense only: false "no" 138 → 67 (comparison) and 43 → 22 (bridge), **0 false "yes"**; any of the first three senses gets
13 + 4 more right but makes 1 false "yes" — the sense order of a dictionary carries information. But the first sense is the
wrong rule for proper nouns ("America" sense 1 is the supercontinent, sense 2 "A country in North America; in full, United States
of America"). **The relation picks the sense** (a selectional restriction: the value of `country` names a country or its people):
form references followed (U.S. → US → United States), else the first country sense of the proper noun ("Former name of the
Democratic Republic of the Congo" for Zaire), else the first demonym sense. Typed: comparison **99.4 %**, bridge **99.2 %**, false
"no" 7 and 3, false "yes" 0; all types 95.9 %. This is the W lab's lexicon doing work inside the logic: symbols get their meaning
from definitions, and the relation they stand in chooses which definition.

**Reading.** With gold evidence the logic is nearly complete; the open part is reading (entity linking, word meaning, the
question → goal translation). 2Wiki's "Who is the father of X?" is answered over mother → spouse — a default, not a valid rule
(the mother's spouse may be a stepfather); an induced rule of that kind must be marked defeasible.

## A2 — gp2 on Popper's own example tasks: Popper wins clearly (20.11.2026)

Protocol fixed before the runs (`research/symbolic_regression/a2/PROTOCOL_A2.md`, amendments 1–2: memory caps after a swap
incident, a 16-entry solver cache checked for equivalence); scored by `score_a2.py` exactly as the protocol defines it. 32 usable tasks
of Popper v5.0.1 `examples/`, gp2 seeds 0–4 vs Popper 3 repetitions, 600 s each; "solved" = complete and consistent on all listed
examples.

| | Popper | gp2 |
|---|---|---|
| tasks solved (≥ 1 run), all 32 | **28** | 11 |
| tasks with ≥ 5 negatives (29) | **25** | 8 |
| noisy tasks (4): none solved; balanced accuracy | 0.74–0.94 | 0.52–0.79 |
| both solved (11): gp2 program smaller or equal | | 5 (horseshoe 10 vs 71 literals, dont-touch 4 vs 8) |
| median time to first solution where both solved (11) | **1.3–2.4 s** | 0.4–314 s |

gp2 runs killed at the memory cap (12, mostly tasks with 10^5 facts) count as unsolved. Where gp2 fails, its best program usually
fits most examples (balanced accuracy 0.5–0.98) but not all: the stochastic search does not close the last cases of wide rules
(buttons-next 52 literals, gt-centipede 40) that Popper's systematic search with its bias finds in seconds. On its home turf the
dedicated ILP system is far better; gp2's strengths stay where G8b showed them (small relational mechanisms, sometimes smaller
programs). Consequence for the research model: rule induction should not rely on gp2 alone — next, Popper on our 2Wiki kinship tasks
(sibling-in-law needs the two-clause disjunction gp2 missed in 3 of 3 seeds). No held-out test here (the protocol names it):
"solved" is fitting the listed examples, not the law.

### Q1 kinship rules: Popper vs gp2, and why recall alone misleads (20.11.2026, interim)

Same training worlds for both (built by the same code and seeds); Popper sees only the 30 training worlds, gp2 additionally gets
counterexample worlds from dev. Evaluation on 2Wiki dev with **recall** on the relation's own questions **and false hits** on the
questions of every other relation (`kin_eval_rules.py`):

| relation | gp2 | Popper | false hits |
|---|---|---|---|
| grandparents (4), father-/mother-in-law | 3/3 seeds, recall 0.996–1.0 | 3/3, same rules, ~2 s each | 0 |
| sibling-in-law (two clauses) | 0/3 at 15,000 evals | 3/3, recall 1.0 | 0 |
| uncle, gender-free | 0/3 (refuted by aunt counterexamples) | recall 1.0 | **89 % of aunt questions** |
| aunt, gender read from text | (running) | seed 0: `female(V1)` in both clauses, recall 0.78 | **0** |
| father ↔ stepfather (mother → spouse) | 0/3 | rule = the other's rule | 93–100 % on each other |

Three lessons. (1) Popper's systematic search finds the disjunctions gp2 misses, in seconds — the A2 result repeats on our task.
(2) A rule's recall says nothing about what else it derives: the gender-free uncle rule is "perfect" on uncle questions and calls
aunts uncles; gp2's refusal was the honest outcome, because its counterexamples contained aunts. (3) Some distinctions need a
predicate the facts lack: **gender** is read from text — pronouns of the person's own paragraph (99.5 % precise, but only 3.9 % of
answer persons have their paragraph in the context) plus the Wiktionary meaning of given names and titles ("A female given name",
"Countess: the wife of an earl") — 63.7 % coverage at 99.1 % precision; with it Popper's aunt rule has no false hits. Biological vs
step-parent is not observable in these facts at all: 2Wiki's "father" answers over mother → spouse are a default.

**Rules chosen on train, scored on dev.** One rule per relation is selected on the TRAIN split (score = correct own answers / (own
questions + false hits on other relations); below 0.5 the system abstains): 13 Popper rules, the uncle rule from gp2 (with
`~female` on the mother branch), stepfather and stepmother abstain (their observable chain is the parents'). With these rules and the
gender read from text, the logic upper bound on 2Wiki dev rises to **inference 91.4 %** (from 76.7 % with gp2's rules alone) and
**97.7 % of all 12,576 questions**. Remaining inference misses: 24 abstentions, 15 unlabelled two-hop questions, 14 ambiguous and
59 empty answers (entity linking). Caveat: gp2's counterexample worlds come from dev, so the uncle rule (42 dev questions) is not
strictly held out; Popper's rules and the selection used train only.

## Plan R2 step 1: data and checkers for "rules into the model" (20.11.2026)

Plan in `docs/PLAN_R2.md`. Built on CPU, no training yet.
- **Way A (the model writes the rule):** 16,000 synthetic tasks in 8 families (chain of 2 and 3, inverse, two-clause disjunction,
  unary filter, default negation, recursion, join) over fresh symbols; two small worlds per task, closed-world examples, the
  generating program as teacher and verifier = the same clingo check as gp2. Popper reproduces the teacher in 14 of 16 sampled tasks
  at the same (minimal) size in ~2 s; it fails the negation family (no negation in this configuration).
- **Way B (the model applies given rules):** 21,579 derivation traces from 2Wiki TRAIN questions — goal, used facts, name links,
  rule applications whose ground instances clingo computes, values, comparisons, answer. A step checker validates every line against
  the prompt alone; on a 1,200-trace sample it rejects all corrupted traces (wrong answer, invented fact, falsified value, dropped
  rule step) and accepts 98.4–100 % of the gold traces (the 1.6 % it rejects are kept out of the training data, so data and reward
  agree). It will serve as the evaluation and as the GRPO reward.

### Q1 step 3: the model reads, the logic answers (20.11.2026)

R1-full reads the gold supporting paragraphs of 400 dev questions (100 per type); the same clingo logic, rules and word senses answer
from the read facts (the goal still from gold). **EM 57.3 % / F1 59.7 %** vs **96.8 % / 97.0 %** from gold evidence on the same
questions: bridge comparison 87 %, comparison 78 %, inference 35 %, compositional 29 %; 42 tok/s, 79–209 answer tokens per question.
The loss is reading, mostly recall of the one relation the question needs: in 36 of 100 chains the second-hop fact (e.g. a place
of death) is not read. Of the chains read completely, the misses are answer form ("Peekskill" vs "Peekskill, New York"; once the
reader is more precise than the gold: "26 September 188 BC") and one linking error ("Jean d'Estrées" merged with "Jean II
d'Estrées" — Roman numerals now count as numbers). Next: goal-directed reading (only the goal's relations in the read prompt).

**Which reader?** On the same 400 questions the untrained base model with two examples reads as well as R1-full (EM 58.3 vs
57.3 %; 233 vs 229 correct, discordant 60:56, McNemar p = 0.78). What R1's training bought is efficiency: 59,759 vs 206,106 answer
tokens, 2–5 s vs 6–12 s per question, no loops (the base reader looped in 139 of 1,000 reads, stopped by the loop detector). The two
readers fail on different questions: the union of their facts reaches **EM 66.5 % / F1 69.4 %** (266 vs 229, p < 0.0001;
comparison 94 %, bridge 95 %). Two filters did not help: requiring the subject to be the paragraph's entity (no change) and the
copy rule (object must occur in the paragraph; −1.75 points, it hurts date comparisons). Recall of the needed relation remains the
bottleneck; the logic tolerates extra facts well in comparisons but chains turn ambiguous (two granularities of one answer).

**Why reading training did not raise accuracy — omission taught by our own copy rule.** Per relation, R1-full reads directors,
dates and performers almost perfectly (0.96–1.00) but citizenship only 0.16 (the untrained reader 0.84) and country of origin 0.03.
The R1 targets kept a Wikidata value only when its label or an alias occurs in the paragraph; Wikipedia writes "a French director",
the label is "France". Against 2Wiki's own evidence on the training paragraphs, only 16.4 % of the citizenship facts and 11.5 % of
the country-of-origin facts were in the targets — the training taught the model to leave them out (GraphNarrative's lesson, inside
our own rule). With Wikidata's demonyms (P1549, 417 countries) as surface forms the coverage is 84.5 % and 83.5 %, every other
relation unchanged (kit R1d: 53,603 facts instead of 45,196). Goal-directed reading (only the goal's relations in the prompt) made
it worse (EM 54.5 vs 57.3 %, p = 0.027) — the trained reader never saw a short relation list. Lesson for every kit: check target
coverage per relation against an independent gold before training.

**Question → goal without gold (Q1 step 4, 21.11.2026).** Until now the goal (start entity, relation chain, candidates, bridge and
attribute relations) came from the gold evidence. It is now induced symbolically from the train questions, without a model: a
question's template is the question with the chain-start entities masked; a template whose train goal is unique (≥ 90 %) predicts
it. On dev the templates are regexes over the bare question (no gold on the dev side; the most specific match wins). Two rules were
added after looking at 16 lost dev questions (named, so the numbers below are not blind): goals that differ only in the attribute
("from the same country": country of origin for a film, of citizenship for a person) become one goal with both attributes, and a
slot span that the oracle's linking does not join to any subject ("20 Centimeters" vs "20 centímetros") takes the subject with the
highest token Jaccard (≥ 0.5, unique).
- Goal equal to the gold goal, all 12,576 dev questions: 97.0 % (template found for 97.3 %; inference 99.4, bridge 99.8,
  compositional 97.7, comparison 92.2 % before the attribute union).
- Oracle with gold facts, all dev: **95.1 %** with the template goal vs 97.7 % with the gold goal (compositional 93.2 vs 97.7,
  inference 87.4 vs 91.5, comparison 98.9 vs 99.4, bridge 98.8 vs 99.2).
- Full pipeline on the 400 questions of step 3 (union reader): **EM 67.5 % / F1 71.0 %** with the template goal vs 66.5 / 69.4 % with
  the gold goal — the gold goal bought nothing here. Question → goal → read facts → clingo with induced rules now runs without any
  gold input on dev. Remaining loss: templates where a slot swallows a relation ("Where did <E1> graduate from?" matching "X's husband
  graduate from") and 2Wiki's own label noise ("founder of" stored as `founded by` or `has part`).

**R2-small Part B, confirmatory (21.11.2026, 10 seeds per arm, `PREREG_R2_small.md`).** A tiny GPT (0.83 M parameters) writes one-step
derivations over synthetic worlds; arm ctx gets the rules in the prompt under fresh names, arm mem must recall a fixed library.
- **H-B1 fails:** depth 4–5 (never trained) is 0 % faithful in BOTH arms, every seed (Mann-Whitney U 50, p = 1.0). Answer-only
  accuracy there is 15 % (ctx) / 17 % (mem) — about chance with 8 entities.
- **H-B2 fails:** in distribution (depth 1–3) ctx reaches 16.6 % faithful vs mem 82.6 % (CI of the difference −80.0 to −47.1 points).
  Per depth ctx 34 / 13 / 3 %, mem 88 / 81 / 79 %. Seven mem seeds exceed 91 %, one (s3) failed at 10.5 %.
- **Note 1 (descriptive):** even the FIRST THREE use lines of a depth-4–5 item are valid in only 0.02 % (ctx) / 1.1 % (mem) of items —
  although each of them alone is a depth-1–3 problem the model solves in distribution. The failure is not that step 4 is new; a goal
  with 4–5 literals already derails the first step. That is what Part C's step index targets (running since 01:51 UTC).
- **Decision as pre-registered:** rules are trained as memorised competence; at this scale the model does not learn to APPLY a rule
  read from the prompt. The solver stays the applier in the agent, the trace is explanation, not mechanism. Kit R2 therefore gives
  half its synthetic way-B rows with rules, half without (`PREREG_R2_kit.md`).
- Limits: one tiny model size, fresh symbols, 20,000 steps; Qwen with pretraining may read rules from the prompt where this model
  cannot (the 2Wiki traces of kit R2 test exactly that).

**Literature for the rules-in-context failure (21.11.2026).** Hu et al., "Case-Based or Rule-Based: How Do Transformers Do the Math?"
(arXiv 2402.17709): fine-tuned transformers reason case-based even with a scratchpad; Rule-Following Fine-Tuning (rules in the input,
the model RECITES and then follows them step by step) took models trained on 1–5-digit addition to 12 digits with over 95 %, over
40 points above scratchpad — our ctx arm gives rules but never makes the model recite the rule before grounding it. Lazić, Fowl,
György, Szepesvári, "To See the Unseen" (arXiv 2604.21632): in propositional reasoning with unseen variable names, the unembeddings
of unseen tokens collapse to nearly one vector during training, so several unseen symbols become indistinguishable (worse with tied
embeddings); a copy-friendly architecture change, data diversity and freezing/resetting (un)embeddings restore generalisation. Our
ctx arm draws fresh names s10–s98 per item with tied (un)embeddings — the same failure mode. Both are candidate fixes for a Part D
(small model first) if Part C does not rescue ctx.

**R2-small Part A interim and Part D (21.11.2026 ~02:25 UTC).** solve@k on H13 g3's T2 (rule classes never trained), seeds 2–3 of
2–9, kept checkpoints at step 19,000 (the trainer deletes its final resumable checkpoint, so 19,000 is the last kept one — greedy
and sampling use the same checkpoint): greedy 0–1 %; 16 samples at T 0.8 with clingo as the verifier reach 4–8 % in arms p0/p50/p90
(≈ 6–8× greedy) and ~0 % in p100. Not yet the pre-registered test (8 seeds). Part D (`PREREG_R2_small_D.md`, fixed before any Part C
result) is queued on the same pod after Part C: ctxR (the model recites the clause before grounding it, after Hu et al.) and ctxF
(fresh-name (un)embeddings frozen at initialisation, after Lazić et al.), 10 seeds each, against Part B's ctx on depth 1–3.
- (21.11.2026 ~03:40 UTC) Counting a goal as right when the template's attribute union contains the gold attribute, the templates
  give the right goal for 98.8 % of the 12,576 dev questions (12,425; template found for 12,462). A guard against slots that swallow
  a relation ("X's husband" inside <E1>) was tested and rejected: 12,413 right — it also blocked correct matches.

**Literature for the way-A expert-iteration stage (21.11.2026 ~06:35 UTC; search-result level, full texts not read).**
SLR (arXiv 2506.15787) synthesises ILP tasks with automatically generated validation programs and trains models by SFT or RL on
the symbolic judge's feedback; its tuned Llama-3-8B leads its benchmark — the closest published design to our way A. A 2026 CEUR-WS
paper (Vol-4244, paper 33) trains small open models with GRPO with a SWI-Prolog interpreter as the reward. ReST-EM (Singh et al.,
arXiv 2312.06585): sample, keep binary-verified solutions, fine-tune, repeat; a course summary of the paper reports the first
iteration gives the largest gain and later ones can hurt when fewer problems remain solvable; a follow-up (arXiv 2403.09472) samples
32 per question and keeps at most 10 per problem. Our pre-registered stage (one round, k = 8, keep the shortest exact sample per task,
gate ≥ 50 solved of 1,800) matches the one-iteration finding; keeping several exact samples per task is the documented alternative if
the first round helps.

**Kit R2 run 1, first result and a confound in our own generator (21.11.2026 ~07:10 UTC).** Qwen3-0.6B after one SFT epoch on kit R2
writes exact rules for 2Wiki kinship dev tasks (two dev worlds per task, clingo checks both): names arm 368/368, fresh arm 257/368
(69.8 %); the untrained base 0/235 on the first 235 items (3060 run, both arms). Fresh-arm failures: two-clause rules (mother 0/30,
father 6/30, aunt 0/8) and argument orientation in grandparent chains (17–19/30). **Confound:** `gen_kin_rules.py` numbered the fresh
symbols in the sorted order of the real predicate names, so with only a handful of predicate sets p1 is nearly always `child` or
`father` — the "fresh" arm can recognise the relation from its examples and recall the trained rule instead of inducing it. The 100 %
of the names arm can likewise be recall by name (H13). Added before any of its answers (exploratory, named): the same 368 worlds with a
random symbol number per predicate and task (`--random-fresh`, prompts sha256 599b6e31…), tuned and base answers queued. Synthetic
way-A tasks (`gen_rules.py`) are unaffected: their symbols carry no meaning by construction.
- Synthetic way A (symbols meaningless by construction), run 1 vs base: held-in families 17/300 exact (base 0/300), held-out chain3/join
  0/200 (base 0/200). Per family: recursion 15/50, disj 1/50, filter 1/50, chain2/inverse/neg 0/50. The answers have the right SHAPE
  (chain, two clauses, filter, negation, recursion) but the wrong PREDICATES: gold `p2(X,Z) & p4(Z,Y)`, answer `p2(X,Z) & p1(Z,Y)`. SFT on
  teacher rules taught the rule shapes, not the choice of predicates from the example worlds; recursion succeeds most because it has
  one predicate to choose. Together with the kinship confound this says: the model is a SHAPE proposer; binding the predicates is a
  search the solver does in milliseconds (chain2: 4 × 4 choices). Next design candidate (to pre-register before testing): the model
  proposes a shape with variables for predicates, clingo grounds the choice against the examples.
- Exploratory, after reading the answers (`shape_bind.py`): keeping each answer's rule shape and letting clingo re-bind its predicate
  symbols to the task's predicates of the same arity, run 1 reaches 145/300 on held-in families (exact as written: 17) — chain2 41/50,
  recursion 35/50, disj 26/50, filter 24/50, neg 19/50, inverse 0/50 (the model writes the forward orientation; orientation is part of
  the shape) — and still 0/200 held-out (it never proposes a chain3 or join shape: no composition of trained shapes). Honest baseline:
  a proposer that simply tries every trained shape, with the same binding, would solve every held-in family, and Popper solves all of
  them in seconds. The model's possible value is shortening that search (one shape instead of all), not finding rules a search
  cannot — which is where PLAN_R2's way A must now be measured (shape-proposal accuracy and solver calls saved).

**R2-small Part C, confirmatory (21.11.2026, 10 seeds per arm, `PREREG_R2_small_C.md`).** Writing `step k: <goal literal k>` before
every rule application does not open depth 4–5: faithful 0 % in every seed of both index arms (H-C1 memI vs mem, H-C2 ctxI vs ctx:
U 50, p = 1.0 each). In distribution the index costs nothing and may help a little (memI 89.6 vs mem 82.6 %, CI of the difference
−8 to +27 points; ctxI 19.3 vs ctx 16.6 %); the first three steps of a long goal stay invalid (memI 0.9 %, ctxI 0 %). Decision as
pre-registered: no step index in kit R2 — run 1 (without index) is the kit, run 2 is not trained; for this model size the depth limit
is architectural and the solver applies chains longer than trained. Part D (recitation, frozen fresh-name embeddings) started on the
same pod at 07:22 UTC. Numbers: `research/symbolic_regression/r2small/results_partC.json`.

**Kit R2 run 1, way B on 2Wiki dev (21.11.2026 ~08:00 UTC; 400 questions, prompts = question + facts + rules for kinship).**
| facts in the prompt | answer correct | trace faithful |
|---|---|---|
| gold evidence + union-reader facts as distractors | 311/400 (77.8 %) | 188/400 (47.0 %) |
| union-reader facts only | 230/400 (57.5 %) | 137/400 (34.3 %) |
On the same reads the solver applying the induced rules with the template goal reaches EM 67.5 % — the solver as applier beats the
model as applier by 10 points. Faithfulness is lowest in comparisons (29/100 faithful, 82–86 correct): every training target with a
date comparison had `value:` lines (4,012 of 4,012) but the model writes them in 22 of 305 answers — it puts the values into the
`compare` line instead ("(2003) > (1943)"). Restoring value lines from the compare line's own values (no other change) makes 70/100
and 67/100 comparison traces faithful: the values are right, only the redundant line is skipped. The format said the same thing twice
(CLAUDE.md rule 6: two ways to one result are a logic error); next kit: the values live only in the `compare` line and the checker
verifies them there against the facts. Bridge comparisons do not recover this way (9/91, 6/94) — a different gap, to inspect.
- Bridge comparisons recover the same way once the restored value lines use the attribute (as trained), not the path: 9 → 29/91
  (gold+read) and 6 → 27/94 (read). A checker bug surfaced on the way: a trace with `same: "A" = "A"` set canon[A] = A and the
  resolver looped forever (it would have hung a GRPO reward). Fixed (cycle guard, no self-mapping); all 21,577 valid gold traces stay
  faithful.

**Literature after kit R2 run 1 (21.11.2026 ~08:30 UTC; three research passes, key quotes checked by me in the full texts or abstracts).**
*Right shape, wrong predicates.*
- SLR (Helff et al., arXiv 2506.15787 v6; full text read, quotes verified in the downloaded HTML): ILP from entailment with a
  validation program; three scores — syntax, OverallScore (all positives entailed, all negatives refuted) and PartialScore ("the
  fraction of examples … correctly classified", a "continuous signal of progress"). Levels 1–5 use **mirror sampling**: "For each
  positive example, a corresponding 'mirror' negative is created by randomly altering the rule-specific atoms" — the examples differ
  only where the rule looks. GRPO on a 1.5B model: LRL 0.0 → 5.6, "training was halted at level 7 due to reward collapse"; the bottleneck
  is "semantic rather than syntactic". Qwen3-0.6B reaches LRL 0.2 without reasoning (their Tab. 15, as reported by the reading pass).
  No analysis of wrong-predicate choice as an error class.
- Pennino et al., "The Interpreter as Teacher" (CEUR-WS Vol-4244 paper 33, CILC 2026; full text): GRPO with a Prolog interpreter as
  reward on GSM8K→Prolog; the 0.5B model is "unable to learn in zero-shot (0.00 …)"; one demonstration "acts as a syntax anchor,
  enabling 0.13 accuracy" (verified).
- Qiu et al. (ICLR 2024, 2310.08559; full text per the pass): LMs are good hypothesis proposers, poor appliers; with a symbolic
  interpreter in the loop GPT-4 goes e.g. MiniSCAN 0.0 → 85.0. Symbol tuning (Wei et al., 2305.08298, abstract verified): fine-tuning with
  arbitrary symbols for labels gives "up to 18.2% better performance on the List Functions benchmark" and "large improvements in
  following flipped-labels". DeepCoder (1611.01989, abstract verified): a network predicts which functions occur, enumeration uses that
  order — "an order of magnitude speedup over the strong non-augmented baselines". HYSYNTH (2405.15880, verified): a grammar fitted to
  LLM samples guides bottom-up search, "solving 58% of the tasks overall, compared to 40% for unguided search and 6% for LLMs without
  search".
- Not found: a paper that trains a model to first state which predicates are consistent with the examples (an evidence step) —
  that idea stays a hypothesis.
*Skipped trace lines.*
- Liu et al., "Can Language Models Learn to Skip Steps?" (2411.01855): models trained on complete steps drop steps on OOD sets and
  that hurts; no in-distribution dropping reported — ours is stronger (22/305 after one epoch). Deng et al. (2405.14838): content far
  from the answer is internalised most easily. Chen et al. (2502.18001): padding with non-informative steps does not help small students
  (Gemma 2B 46.62 padded vs 47.61). RFT (2412.14780): constant upweighting of tokens fell below plain SFT (44.5 vs 52.5); our own tiny-GPT
  study found oversampling better than any token weighting (VI insight a4a7f164).
*Consequences for the next kit (to pre-register before training):* (1) mirror-sampled negatives in way-A tasks so the separating
predicate is visible in the data; (2) the model proposes the shape (and optionally a predicate ranking), clingo binds/searches
(DeepCoder/HYSYNTH pattern; our 145/300 is the lower bound); (3) one representation per fact in traces — values only in the compare
line; (4) for RL: PartialScore-style dense reward, no or low KL, tasks at a level the 0.6B model partly solves (reward collapse).
Never-trained shapes (0/200) need those shapes in the curriculum or the search grammar — none of the methods creates them.

**Kit R2 run 1 as a reader (measure 3; 21.11.2026 ~08:45 UTC).** On the 400 step-3 questions (template goal, clingo with induced
rules): kit 228 vs R1-full 229 correct (McNemar p = 1) — the pre-registered "no worse than R1-full" holds. The mix moved: comparison
78 → 94 (p = 0.0004) and bridge 87 → 96 (p = 0.035) improved (the demonym-aware R1d replay), compositional 29 → 17 (p = 0.0075) and
inference 35 → 21 (p = 0.029) got worse; reading recall of the needed facts for chains ≈ 0.52–0.56. Reader unions: R1-full ∪ base
2-shot EM 67.5 % (best so far), kit ∪ base 65.5 %, kit ∪ R1-full 67.75 % — the kit does not raise the union. Reading the chain facts
(father, director, place of death …) is still the bottleneck of the pipeline.
- Solver calls (PREREG_R2_kit addendum 5, greedy answers of run 1 only; `solver_calls.py`): the model's shape with clingo binding
  solves 145/300 held-in tasks in 13.2 calls on average (median 10); enumerating the six trained shapes solves 300/300 in 84.7 (median
  85.5); never-trained shapes 0/200 for both. The registered criterion (fewer calls at the same solved share) is not met; as a first
  stage before enumeration the model would save roughly 30 % of calls (estimate ≈ 59 vs 85) — milliseconds in absolute terms. In a
  search space this small the model is not worth keeping as a proposer; the K = 8 samples (queued) can raise its solved share.

**Where the pipeline loses chains, and the official metric (21.11.2026 ~09:50 UTC; exploratory, on the 400 step-3 dev questions).**
- *Are the needed facts in the text?* Of 1,009 gold evidence triples, 994 have their subject's paragraph in the context and 941 (93 %)
  are stated there (object string or a surface form of it); the union readers read 910, and 855 of the 941 stated ones. Misses
  concentrate in country of origin (23 stated, 4 read) and place of death/birth in chains (16 stated, 10 read; 30 stated, 25 read).
  So the reading ceiling is high; the reader skips stated facts of a few relations.
- *Compositional failures with read facts and the gold goal* (100 questions): correct 35; several values with the gold among them 19
  (surface variants: "North Hollywood" / "North Hollywood, Los Angeles", "Fougères" / "Fougères, Ille-et-Vilaine"); needed fact not
  read 15; wrong single value 14 (incl. "unknown" read as a value); wrong span granularity although both facts were read 7 ("Giza" vs
  "Great Pyramid of Giza"); no answer although both read 4 (bridge entity named differently, e.g. "Alfonso VI" vs "Alfonso VI of León
  and Castile").
- *Official metric.* The 2Wiki evaluator v1.1 (github.com/Alab-NII/2wikimultihop, `2wikimultihop_evaluate_v1.1.py`) scores answer EM/F1
  as the maximum over the gold string plus the aliases and demonyms of `answer_id` from `id_aliases.json` (in the `data_ids.zip`
  release linked from the README), after SQuAD normalisation. Our EM so far used the gold string only. Re-scored (`official_score.py`):
  ours 67.5 %, official gold-only 67.25 %, official with aliases 68.25 % (F1 71.3 %) — our numbers were slightly conservative and
  remain comparable. The alias file is noisy (e.g. Q16 Canada lists "One Law for the Woman"), a named limit of the official metric.
- *Tie-break (exploratory, chosen after seeing these errors — not a result):* when several values are derived and the shortest is
  contained in every other, answer the shortest. Compositional 36 → 48 % (official with aliases 54 %), all 67.5 → 70.5 % (72.0 %).
  It must be fixed in a pre-registration and tested on questions whose reads have not been seen before it may be reported as a gain.
- *Inference failures* (100 questions, read facts, gold goal): correct 42; fails even with the gold facts 11 (kin programs miss paths
  such as father = mother's spouse or a sibling's father, and spelling variants "ab"/"ap"); needed fact not read 15 (mother 10, spouse 8,
  sibling 5, father 5 missing over all failures); no answer although both facts were read 9 (the bridge person is named differently in
  the two reads, e.g. "Sir Mountstuart Grant Duff"); wrong single value with both read 9 (span granularity "Marie I de Coucy" vs
  "Marie I de Coucy, Countess of Soissons", or a competing read); several values 9. Levers, in order of size: alias-aware linking of
  the bridge entity (≈ 13 questions over compositional + inference), reading of mother/spouse, the missing kin paths, span choice. None
  needs training; all are measured only on these 400 questions so far.

**G8d-1 started (21.11.2026 ~10:52 UTC; PREREG_G8d1.md frozen, commit 1695158).** Question: does a proposer that reads the CURRENT
candidate's computed vectors (free behaviour F0 + exact structure S, the representation that won G8d-0) make gp2's rule search cheaper
on tasks nobody tuned on? 40 new blind tasks (subagent author who opened only the notation file; kinds a/b/c 10/15/15; no name or
anonymised-shape overlap with the 33 development tasks), policies U (uniform), P (static operator prior), C (frozen SF model chooses
operator and rule), Cs (C's scores permuted per decision), 10 seeds; primary C < Cs (one-sided Wilcoxon over task medians). Seeds
reduced from the plan's 20 to 10 before the freeze (smoke cost). Smoke on development tasks found and fixed a cache bug in the new
arm code; the hash check caught an outdated g8d0.py on the second host before any run. Literature placed (research for G8d-1):
neuro-guided GP biases instructions before the run (Liskowski et al. GECCO 2018), NEON proposes WHERE to edit with a GNN saliency map
(arXiv 2502.04568), LLM mutation operators (ELM; GESR arXiv 2605.10685, theory only), a neural clause evaluator for Aleph (Di Maio &
Shavlik ICDM 2003); not found: a learned, candidate-conditioned edit proposer tested against a permuted-score control on blind tasks.

**Plan R3 drafted (PLAN_R3.md, commit 1db3c4a).** Consolidation of kit R2 run 1, R2-small B–D, the Q1 analysis and run 34 into one
next kit: way A as ranked shape proposals with clingo binding, unseen shapes from the search, short way B with values only in the
compare line, reader rows for the relations the readers miss, random fresh symbols. Its open parts wait for Part E, Part D, the EI gate,
G8d-1 and the fresh-question Q1 test.

**Part F frozen and queued (21.11.2026 ~11:35 UTC; PREREG_R2_small_F.md, commit c75fa2c).** Iterative one-step derivation on the tiny
model, after ProofWriter (arXiv 2012.13048: depth-3 training, depth-5 test, iterative 87.8 % vs all-at-once 27.4 %) and the looped-
transformer line (Fan et al. ICLR 2025; arXiv 2604.07822, 2610.27628; 2609.33144 warns that extrapolated answers need not come with
faithful steps). Arms stepH (the harness binds each literal) and stepM (the model keeps goal + derived facts) against Part B ctx
(testD faithful 0 %); starts on the RunPod pod after Part D.
**Names as retrieval keys — what the literature offers (research 21.11.2026).** Code models break when identifiers are renamed; CREAM
(arXiv 2207.11104) trains on misleading identifiers (counterfactual) and gains robustness, most on small data; ContraBERT (arXiv
2301.09072) finds renaming augmentation the weakest of its operators because renamed copies stay close to the originals; arXiv
2510.03178 grades renaming from alpha-renaming to opaque tokens as a probe. Consequence (PLAN_R3.md): counterfactual rows — a known
name bound to a different rule in the prompt — instead of more plain renaming (run 34: 600 renamed blocks, P7 renamed 5/8 in both seeds).

**Symbols instead of names — and vectorised symbols (research 21.11.2026 ~11:50 UTC, on the user's reminder that renaming was to be
solved by symbols and by vectorising them).** Four routes in the literature:
1. *Canonical renaming before the model* (de Bruijn idea): alpha-equivalent inputs become identical; exact invariance without
   training; the model loses name meaning (intended for symbolic tasks).
2. *Vectorised symbols* — Isik, Cinbis, Gol (ICML 2025, arXiv 2410.17161): a symbol's embedding = shared learned part + random part
   resampled every forward pass. On renamed LTL data the plain model falls to 34.1 % (12.1 % exact), the dual-part embedding keeps
   95.9 % (76.5 %), alpha-renaming augmentation 98.0 % (77.7 %); only the dual-part model extends to more symbols than trained.
3. *Invariance by construction* — Isik, Li (ICML 2026, arXiv 2601.23169): one weight-shared stream per symbol; renaming permutes the
   streams (Theorem 4.1); 100 % alpha-covariance, LTL renamed 98.2 % (79.7 % exact), best also with 80K training items; cannot emit a
   fresh symbol, cost O(S·L²).
4. *Why new symbols fail* — Lazić et al. (arXiv 2604.21632): unembeddings of unseen tokens collapse under weight decay + layer norm;
   freezing or periodically resetting them restores generalisation; Gemma 3's unused tokens are a poor initialisation (cos 0.78 vs
   0.09 at 1B). Our Part D arm ctxF (frozen random fresh-name embeddings) is a first test of this route.
Context alone can carry meaning: In-Context Algebra (Todd et al., ICLR 2026, arXiv 2512.16902) — per-sequence variable tokens, 99.4 %,
near-perfect on unseen groups, but only at width ≥ 512 (d 128: 13.3 %). Entity types help multi-hop reasoning (Gontier et al.,
TMLR 2022, arXiv 2201.01787: CLUTRR 88.8 vs 62.9 %) — the determinative idea (H13 arm D plan).
Consequence (hypothesis until tested, small model first): symbol embedding = learned CLASS vector (determinative) + random IDENTITY
vector resampled per sequence; canonical renaming in the pipeline now; for Qwen, added opaque tokens initialised from a class mean +
random, not from unused rows. Design of a Part G waits for Part D's ctxF result.

**Run 33c seed 43 and a correction (21.11.2026 ~12:15 UTC).** Seed 43 replicates seed 42 on every target (judge_same 40/40, paraphrase
36/40, pressure 30/30, formalize 20/20, invented certainty 0; judge_long 40/40, judge_xlong 38/40); paired, no set differs (largest:
package_worlds 15 vs 12, mid-p 0.125). Its single write_rules error is language_heldout:1 — one of the two prompt-invalid items with
doubled-object prose. **Correction:** the run-34 hypothesis that "a name trained at two arities loses its arity binding" rested on
exactly these two items and is withdrawn; kit33c has no ternary rows and shows the same error. What stays: renamed critical P7
predicates fail in run 34 (both seeds) and run 33c seed 43 alike (P7 5/8) — the names-as-keys problem the symbol work targets.

**Kit R2 run 1: random fresh symbols and synthetic depth (21.11.2026 ~12:40 UTC).**
- *Kinship rule writing with random fresh symbols* (exploratory rf set, same 368 dev worlds, symbol numbers drawn per task): tuned
  17/368 exact, base 0. The earlier fresh-arm figure of 257/368 came almost entirely from the sorted numbering of the fresh symbols —
  the model recalled the position, not the rule. With symbols it cannot recall, rule writing generalises to 4.6 %.
- *Synthetic way B, measure 2* (600 items, 60 per depth): faithful traces with rules in the prompt d1 43/60, d2 25, d3 14, d4 5, d5 0;
  with library names d1 38, d2 24, d3 20, d4 4, d5 0; base 0/600. The 0.6B model shows the tiny model's depth collapse, softened at
  depth 4 (5/60 vs 0 %). Part F (one step per call) is the registered test of the remedy.

**R2-small Part D scored (21.11.2026 ~14:05 UTC; PREREG_R2_small_D.md).** Neither mechanism helps the tiny model apply a rule given in
the prompt: reciting the rule before using it (ctxR) 15.5 % vs ctx 16.6 % testI faithful (MWU p 0.52); frozen random fresh-name
embeddings (ctxF, the collapse fix of Lazić et al.) 13.3 % vs 16.6 % (p 0.79; one seed collapsed to 0.3 %). Depth 4–5: 0 % in every
arm. As registered, rule application stays with the solver and no kit gets recitation rows (results_partD.json).
**Part G frozen and queued (PREREG_R2_small_G.md, commit 36dfede).** Vectorised symbols (class vector + a random vector drawn per
sequence for input and output, after arXiv 2410.17161) vs learned and frozen name rows, with a new test of 600 items whose rule names
never occur in training. Primary: unseen-name faithful dual > ctx. Runs on the 3070 host after the kit R2 queue.

**Kit R2: solve@8 and the EI gate (21.11.2026 ~14:50 UTC).** With K = 8 samples (T 0.8) the run-1 model writes an exact rule for 73
of 300 held-in tasks (greedy 17), still 0 of 200 never-trained shapes, and 32 of 368 kinship tasks with random fresh symbols (greedy
17). On the 1,800 fresh EI tasks it solves 442 at k = 8 (solve@1 71) — the registered gate (≥ 50) is passed. The exact samples are
skewed to recursion (198 of 300 tasks; neg 23, filter 29). The EI round (addendum 3: 1 epoch from the SFT adapter on the 442 verified
rows + 20 % replay) is queued on the 3070 before Part G; measured as solve@1 before vs after, paired.
- *Solver calls with samples (addendum 5):* the model's greedy shape plus its 8 sampled shapes, each re-bound by clingo, solve 269/300
  held-in tasks in mean 32.7 calls (median 24); enumerating the six trained shapes solves 300/300 in 84.7 (median 85.5); the model needs
  fewer calls on 168 tasks. Greedy alone had 145/300 in 13.2. The registered criterion (fewer calls at the same solved share) is not
  met; as a first stage before enumeration the model saves calls (exploratory reading).

**Q1 pipeline levers on 400 fresh questions (21.11.2026 ~16:10 UTC; PREREG_Q1_levers.md).** Official 2Wiki answer EM with aliases:
no levers 67.5 % (development 68.25 % — the baseline replicates), tie-break 71.0 % (14 gained, 0 lost, exact one-sided McNemar
p = 0.00006, H-L2 holds), title anchoring alone 67.25 % (0 gained, 1 lost), both 70.75 % (14 gained, 1 lost, p = 0.0005, H-L1 holds).
All gains are compositional questions (41 → 55); comparison, bridge comparison and inference are unchanged (inference −1 with the
anchor). As registered, both levers join the pipeline; the anchor contributes nothing on fresh questions (its +2 on the development
set did not replicate) — dropping it would be a new decision for the next registration. Results: research/symbolic_regression/q1/
results_levers_fresh.json.

**Wiktionary lexicon — words as symbols (state 21.11.2026 ~16:30 UTC; data on the GPU host under the Wiktionary lab directory).**
- *Every sense is a symbol:* 865,721 English senses as clingo facts `sense(Sym, Word, Pos)` (kaikki/wiktextract raw dump, enwiktionary
  2026-10-01, CC BY-SA), file `lex_facts.lp`.
- *Genus rules:* 351,989 `is_a` and 7,248 `part_of` facts from noun glosses ("a/an … NOUN that/which/of …", "kind/type/sort of Y",
  "part/member of Y"); hand check ≈ 34/40 correct (errors: prepositions, "member of one of …", participle phrases, adjective/noun
  ambiguity); shallow hierarchy (depth 0–2 for 97 %), one circular core of 5,380 words plus 111 two-word cycles.
- *Definitional graph and grounding set* (`defgraph.py`, 467,420 headwords, edge u → v when u occurs in v's gloss): Kernel 9.8 %,
  Core 90 % of the Kernel, greedy minimum feedback vertex set **2.44 % (11,423 words)** — an upper bound. Vincent-Lamarre, Harnad et
  al. (TopiCS 2016, arXiv 1411.0129) report Kernel ~10 %, Core ~75 %, minimal grounding set **~1 %**. The "about 1 %" is the paper's
  figure; ours is 2.4 % until a better feedback-vertex-set search and a lemmatiser (Wiktionary form_of links) tighten it. First
  grounding words: make, form, set, act, person, point, line, state, place, something … (frequent and concrete, as arXiv 1308.2428).
- *Used:* word senses chosen by the relation's range, not by sense order (America sense 2, demonyms) — comparison questions 99.4 % with
  gold facts; the demonym gap explained why R1 reading training did not raise QA accuracy.
- *Not done:* synonym clusters (one symbol for several words), the tighter grounding set, importing the lexicon symbols into the VI or a
  kit, and the planned tiny-GPT word-meaning experiments W0/W1 (meaning from example sentences vs from the name).
- *Caveat:* "only the grounding set must be learned" holds for the definition structure; understanding a defined word means following
  definitions over several hops, which our models do not do reliably (tiny GPT depth 4–5: 0 %) — the solver has to follow them.

**Kit R2 expert-iteration round, solve@1 (21.11.2026 ~17:07 UTC — first written as "~17:15", corrected: the scoring ran 17:04–17:08 UTC; PREREG_R2_kit addenda 3 and 5).** One epoch from run 1's adapter on
the 442 clingo-exact EI rows (+ 20 % replay), then greedy answers; scored with `score_kit_r2.py` (way A exact, both worlds, clingo) on
the CPU of the AMD host, references kept off the GPU host. Run 1 re-scored in the same call reproduces 17 / 0 / 625 (fresh 257).
- **held-in:** before 17/300, after 15/300 (before-only 8, after-only 6; one-sided McNemar "after > before" p = 0.79) — **no gain**.
- **held-out (chain3/join):** 0 → 0.
- **kinship dev:** 625 → 593/736 (before-only 64, after-only 32; p = 0.9997): the sorted-fresh half drops 257 → 225, the named half
  stays 368/368. EI on the model's own verified predicate choices did not teach the data-driven choice; it cost recall on kinship.
- **kinship, random fresh names (rf, 17:10 UTC):** 17 → 24/368 (before-only 4, after-only 11; p = 0.059) — not significant at
  α 0.05; direction opposite to the sorted-fresh half (257 → 225). Hypothesis only: EI weakened the use of sorted names as a cue,
  which costs where the cue helps and helps a little where it misleads.
- **Solver calls (addendum 5, ei-done 17:45:50 UTC, scored 17:46–17:49 UTC on the AMD CPU):** model = greedy + K = 8 shapes with
  clingo binding, enumerate = the six trained shapes in fixed order. held-in: model 269 solved / 32.7 calls (before) → 259 / 31.1
  (after), enumerate 300 / 84.7; held-out: 0 for every strategy (chain3/join are not among the shapes); kinship random fresh: model
  64 / 5.2 → 107 / 6.3, enumerate 246 / 7.2. The registered criterion (fewer calls at the same solved share) is met nowhere.
  **Combined, descriptive (`combo_calls.py`: the model's shapes first, then enumeration):** held-in 300 solved at 47.0 calls
  (before) / 47.7 (after) vs 84.7 — the model's value is the ORDER, -45 % calls at full coverage; EI adds nothing. Kinship rf:
  248 / 249 solved at 7.6 / 8.1 calls vs 246 at 7.2 (enumeration is already cheap there).
- **held-in by family (descriptive, before → after, of 50 each):** chain2 0 → 2, inverse 0 → 0, disj 1 → 1, filter 1 → 1, neg 0 → 1,
  recursion 15 → 10. Run 1's exact answers were almost all recursion; EI (whose 442 rows were 45 % recursion, 198) lowered exactly
  that family and moved none of the others. With five of six families at ≤ 2/50 the model starts below the level STaR names as a
  precondition (few-shot above chance, Zelikman et al. 2022, arXiv 2203.14465); RLIE (arXiv 2510.19698: LLM proposes, a regularised
  logistic regression selects) and LLM-built language bias for ILP (arXiv 2505.21486) keep selection outside the generator — the
  same division our numbers point to.
- Reading (as fixed in addendum 5): training on 442 self-verified rows does not move exact solve@1; the predicate choice stays with
  the solver (clingo binding / gp2), the model proposes shapes only. Next lever is the solver-call measure, not another EI round.

**Data-ranked binder for way A, confirmatory (21.11.2026, PREREG_binder.md frozen 18:07 UTC, run 18:07–18:09 UTC on the AMD CPU).**
600 fresh tasks (`gen_rules.py --seed 61`, sha256 a7d114ee…, 8 families × 75), no model anywhere. Binder = rank every (shape,
binding) pair by the geometric mean of marginal data shares (does the positive pair's X/Y value occur at that argument position of
the bound predicate), computed from facts and positives only; clingo checks in that order.
- **H-BR1 holds:** six trained families, binder-ranked vs fixed enumeration: fewer calls on 448 tasks, more on 1 (sign test
  p = 3e-133); 450/450 solved both, mean calls 5.73 (median 3) vs 83.68 (median 85.5). By family (mean calls, enum → binder):
  chain2 9.4 → 1.2 (59/75 at the first call), inverse 24.4 → 1.9, disj 51.2 → 10.1, filter 113.3 → 9.6, neg 141.4 → 7.9,
  recursion 162.3 → 3.7.
- **H-BR2 holds:** with chain3 and join added to the shape grammar the binder solves 150/150 tasks of the two families no model or
  earlier strategy ever solved (one-sided 95 % Clopper–Pearson lower bound 0.980), mean 18.1 calls (chain3 8.4, join 27.8); the
  trained six cost 7.07 instead of 5.73 calls with the larger grammar.
- **Reading:** predicate choice from data is a symbolic job done in milliseconds by marginal statistics + clingo; the fine-tuned
  0.6B model (held-in exact 17/300, model-first 32.7 calls) is not needed for it, and unseen shapes come from a grammar, not from the
  model. The model's place is translation (question → goal, text → facts), where Q1 shows it works. Named limit: synthetic random
  worlds; next check on real relations (2Wiki kinship: 122 of 368 rf tasks are outside the six shapes).
Files: research/symbolic_regression/binder/ (scripts, binder_test.json, binder_summary.json).
- **Amendment 1 — covering binder, H-BR3 holds (frozen 18:12 UTC, run 18:12–18:13 UTC).** 122 old kinship tasks needed two clauses
  with four different predicates. FOIL-style sequential covering on the binder score (`binder_cover.py`) on 375 FRESH kinship tasks
  (`gen_kin_rules.py … --split dev --random-fresh --seed 61`, fresh arm; KIN path in the copy pointed at the kin directory, nothing
  else changed): **374/375 solved at 2.7 calls** (one-sided 95 % CP lower bound 0.987), every relation 100 % except sibling-in-law
  29/30. For comparison on the old rf set: fine-tuned model K = 8 64–107/368, six-shape enumeration 246/368. Descriptive: covering
  alone on the synthetic seed-61 set 458/600 (chain3 0 and recursion 8/75 lie outside its clause list); grammar_global solves those —
  the union of the two symbolic strategies solves every family tested.

**Q1 fresh 400: where the answers are lost (21.11.2026 18:32 UTC, descriptive).** Same pipeline (title anchor + tie-break, frozen
`official_score.py`) with the GOLD evidence triples as reads: official alias EM **94.0 %** vs 70.75 % with the model's reads. Per
question: 278 right both ways, 98 right only with gold facts (inference 48, compositional 39, comparison 8, bridge 3), 19 wrong both
ways, 5 right only with read facts. In the 98 reading-loss questions the unmatched gold triples are mostly not missing relations: 61
have the relation and subject read but the OBJECT written differently ("Alfonso VI" vs the next paragraph's title "Alfonso VI of León
and Castile"), 41 another object, 11 the relation not read at all; 23 gold objects do not occur in the subject's paragraph at all
(2Wiki takes them from Wikidata — no reader can get them). Top relations: father 32/61 unmatched, mother 18/26, place of birth 14/14,
spouse 11/18, place of death 9/9.
**Object-anchor lever rejected on the development 400 (18:33 UTC, never run on a test set):** rewriting an entity-relation object to
the context title sharing most name tokens (`official_score_v2.py --object-anchor`) lowers EM 72.5 → 71.5 % (inference 46 → 42 %;
5 lost, 1 gained) — relatives share name tokens (Mihnea Turcitul / Radu Mihnea, Beatriz / Leonor de Alvim, Jacob / Bernard of
Baden-Baden), so the father lands on the son's title. The subject anchor works because a paragraph is about its own title; objects
have no such guarantee. A second variant (--object-backlink: keep a candidate title only if a fact read about it names the subject back) is worse still,
69.25 % (inference 37 %, compositional 51 %; 18:35 UTC, development only) — relatives name each other. Consequence for R3: the object form must come from reading (reader rows whose object is written as the
linked entity's canonical name where the paragraph gives it), not from a name-token rule.

**R2-small Part F, confirmatory (PREREG_R2_small_F.md; ALL DONE F 19:00:44 UTC on the RunPod RTX 3070, 10 seeds per arm).** One
derivation step per call; stepH = the harness binds each goal literal, stepM = the model keeps goal and derived facts.
- **H-F1 fails:** testD (depth 4–5) faithful stepM 0.0 % vs ctx 0.0 % (MWU U 50, p 1.0).
- **H-F2 fails:** stepH 0.03 % vs ctx 0.0 % (U 60, p 0.24).
- In distribution (depth 1–3) both are worse than Part B's ctx: stepM 1.8 % vs 16.6 % (CI of the difference −18.9 to −11.6 points),
  stepH 10.5 % (−10.6 to −2.5). First three use lines of a depth-4–5 item valid: stepH 0.22 %, stepM 0.0 %, ctx 0.02 %.
- **Decision as pre-registered:** neither holds → depth stays with the solver, way B is not extended. Together with Parts B–D and the
  binder result: at this size the model neither applies rules over several steps nor chooses predicates from data — clingo derives,
  the binder induces, the model translates. Files: research/symbolic_regression/r2small/analysis_F1.json, analysis_F2.json.

**Correction to the Q1 loss analysis above (21.11.2026 19:04 UTC).** A third object-link variant on the development 400
(`--object-subset`: rewrite only when every name token of the object occurs in a unique context title with equal marks) gives 72.25 %
vs 72.5 % — no gain either. So "object written differently" (61 unmatched triples) is mostly NOT what loses those questions: the
pipeline's own entity linking already joins such forms, and the counted triples overlap with other errors in the same question. The
earlier sentence "the object form must come from reading" overstated it. What holds: of the 98 reading-loss questions 76 have every
gold fact stated in the subject's paragraph (22 contain a Wikidata-only fact), so perfect reading of STATED facts is worth up to
+19 points (70.75 → ≤ 89.75 %); the losses are wrong objects (41), unread relations (11) and the mixture per question — a reading
quality target for R3, not a linking rule.

**Reader diagnosis for R3 (21.11.2026 19:20–19:36 UTC, development 400 only; `research/symbolic_regression/q1/stated_recall.py`).**
Measure: recall of STATED gold facts per relation (object occurs in the subject's paragraph) and CONFLICT (the reads also hold a value
for the same subject and relation that matches no gold object). Results (recall / conflict, of 927 stated gold facts):
R1-full 80.5 % / 10.0 %, kit R2 run 1 81.5 % / 9.8 %, base 2-shot 83.6 % / 18.3 %, union R1-full+base (the Q1 reader) 90.9 % / 21.4 %,
union kitR2+base 92.2 % / 21.4 %, union kitR2+R1-full 89.0 % / 12.6 %.
- **R1-full taught omission:** its read targets (built 20.11 16:31, before demonyms were fetched at 23:33) contain a country fact in
  only 2,032 of 10,151 rows whose paragraph has a nationality word; R1-full recalls country of citizenship 8/55 (base 43/55) and
  country of origin 1/28. Kit R2's r1d rows (with demonyms, 3,132/3,376) repair it: 40/55 and 23/28.
- **Kit R2 lost father:** 83 → 53/97 vs R1-full (14 of the lost facts not written at all, 3 written as mother). Hypothesis only:
  kit R2's kinship rows, where 2Wiki "father" is derived as the mother's spouse, taught the reader not to read father.
  Data check (19:37 UTC, CORRECTED 20:05 UTC): the first count divided kit R2's father facts by all 10,000 r1d rows, half of which
  are WRITE rows (English text answers) — wrong. On read rows only: kit R2 245 / 4,999 (4.9 %) vs R1 705 / 14,911 (4.7 %), the same
  density. Remaining candidate (untested): kit R2's 1,369 rows with father as a RULE target (derive 919, write_rules 450, 150 of
  them inferred_father).
- **Kin roles conflict in every reader:** mother 20–33 conflicting values per 52 stated facts, father 24–37 per 97, spouse up to 21/34.
- **Recall is not the target alone:** union kitR2+base has the highest recall but lower EM than the Q1 union (70.75 vs 72.5 %;
  compositional 48 vs 55 %), with the same conflict rate — the measure misses some harmful extra facts.
R3 reader rows therefore: R1 targets with demonyms (R2's fix), father kept explicitly (no derived-father rows in the reader task),
kin role contrast rows (paragraphs naming parents, spouse and children together), each read row also scored for conflicts; the R3
reader is judged by pipeline EM on a NEW fresh set, with stated recall and conflicts as diagnostics.

**Q1 fresh 400: the 24 questions wrong even with gold facts (21.11.2026 22:01 UTC, descriptive; first written as 22:05, corrected at 22:02).** 14 inference (12 no answer, 2
wrong), 7 compositional (5 without a matching goal template), 2 bridge-comparison, 1 comparison. The unanswered kinship cases are
evidence noise, not rule errors: the kinship rules are right (paternal grandmother = father ∘ mother, kin_selected.jsonl), but 2Wiki's
gold triples name the chain's middle person differently from the next triple's subject ("Charles III of Spain" / "Charles I",
"William Willoughby, 6th Baron …" / "William Willoughby", a subject string '"Not to be confused with Elizabeth of Vermandois'). With
READ facts the title anchor rewrites subjects to paragraph titles, which the gold run cannot (gold triples carry no paragraph). So the
94.0 % ceiling is a slight underestimate, and nothing in the residual calls for training — at most 5 compositional templates are
missing (a goal-template coverage item for the pipeline).

**Reader-fact consistency filters, development 400 only (22:34 UTC, exploratory; official_score_v2.py).** Wrong kin values in the Q1
union reads (mother/father/spouse with a value matching no gold object) are mostly NOT in the subject's paragraph (65), another person
of the paragraph (40), or the subject itself (17). (a) `--kin-filter` (drop mother=male / father=female by the question's gender table,
and kin facts with object = subject) removes 13 + 3 facts and changes no answer: 72.5 % → 72.5 %. (b) `--grounded` (keep an
entity-relation fact only if every name token of its object occurs in the paragraph it was read from): 72.5 → 73.0 % (inference 46 →
48 %), 3 questions gained, 1 lost — small; added to the R3r analysis as a DESCRIPTIVE arm only (PREREG_R3r amendment 3).

**R2-small Part H, confirmatory (PREREG_R2_small_H.md; ALL DONE H 21.11.2026 23:53:03 UTC on the RunPod RTX 3070, 10 seeds per
arm; read 22.11 00:02 UTC).** Arms mem (library recalled by name) and memCF (half recall, half counterfactual: library names bound to
OTHER rules written in the prompt).
- **H-H1 holds:** testCF faithful to the PROMPT's rule memCF 45.1 % vs mem 0.5 % (exact one-sided MWU U 100, p 5.4e-6).
- **H-H2 fails:** testI (recall) memCF 74.75 % vs mem 94.9 % (95 % bootstrap CI of the difference −26.7 to −12.5 points).
- Descriptive: testD (depth 4–5) 0 % in both arms, as in Parts B–G; memory-following on testCF mem 7.1 %, memCF 0.3 % — the mem
  model mostly writes neither rule on counterfactual items (answer accuracy there 15.2 %, about chance).
- **Decision as pre-registered (H-H1 holds, H-H2 fails):** reading is bought with recall — R3 keeps given-rule and recalled-rule tasks
  apart with an explicit marker. Descriptive note: 45 % prompt-rule reading under misleading names is far above Part B's 16.6 % for
  rules under fresh names (related, not identical test items): training WITH counterfactual names teaches reading the prompt better
  than training with fresh names alone. File: research/symbolic_regression/r2small/analysis_H.json.

**G8d-1 (PREREG_G8d1.md + amendments 1–2), main policies scored 22.11.2026 01:21 UTC.** 40 blind tasks × 10 seeds × U/P/C/Cs = 1,600
runs on three CPU hosts, merged by first finish (`collect_d1.py`: workstation 749, AMD 273, second host 578; 297 duplicates); hash check OK;
0 missing runs. 30 eligible tasks, 16 hard.
- **H1 (primary) fails:** C < Cs — Wilcoxon p 0.70 (C better on 12, worse on 9; median Cs/C 1.0).
- **H2 holds:** C < P — p 0.009 (16 vs 4; median P/C 1.05).
- **H3 fails:** C < U — p 0.69 (11 vs 9).
- Hard stratum: C < Cs p 0.94, C < P p 0.12, C < U p 0.94. No-harm check outside the hard stratum: median U/C 1.52 (≥ 0.9, no harm).
  Solved shares: C 310, Cs 317, P 300, U 315 of 400. Wall seconds per run: C 746, Cs 550, P 186, U 169 (the model's cost).
- Decision path as pre-registered: H1 fails → decided by O1/U in the hard stratum (≥ 1.5: the information exists but the model does
  not deliver it; else the line ends). The O1 runs (hard tasks, seeds 0–4, 80 runs) started on the first host at 01:21 UTC.
  Files: research/symbolic_regression/g8d/d1_score_main.json, d1_collect.json.

**R2-small Part G, confirmatory (PREREG_R2_small_G.md; "done" 22.11.2026 03:15:02 UTC on the RTX 3070 host, 30/30 runs exit 0;
analysed 03:31 UTC with the frozen analyze_g.py f49e0ac5…).** Names as interchangeable vectors (dual: class vector + per-sequence random
identity, input and output) vs learned name rows (ctx) vs frozen random rows (ctxF), 10 seeds each.
- **H-G1 fails:** faithful on names never seen in training (testU) dual 3.9 % vs ctx 0.0 % (exact one-sided MWU U 60, p 0.24); dual is
  the only arm above 0 on unseen names, but not significantly.
- **H-G2 fails:** in distribution (testI) dual 4.0 % vs ctx 19.9 % (95 % bootstrap CI of the difference −21.4 to −9.5 points).
- Descriptive: ctxF testI 14.0 %, testU 0 %; depth 4–5 0 % in every arm (as in Parts B–H).
- **Decision as pre-registered (H-G1 fails):** names are normalised OUTSIDE the model (canonical renaming in the pipeline); the model's
  embeddings are not changed in R3. Together with Part H: the data remedy (counterfactual names) teaches reading the prompt (45 %),
  the representation remedy does not (dual 4 %). File: research/symbolic_regression/r2small/analysis_G.json.

**R3r reader test, confirmatory (PREREG_R3r.md + amendments 1–3; fresh2 baseline reads done 22.11.2026 04:37:48 UTC, R3r reads from
the pod 00:51; scored 04:40 UTC on the AMD host with the frozen official_score.py 7f9170e9…, score_r3r.py db326200…).** 400 fresh2
questions (100 per type), official alias EM, title anchor + tie-break.
- **H-R3r1 holds:** NEW = union(R3r, base 2-shot) 70.75 % vs OLD = union(R1-full, base 2-shot) 66.0 % — 30 questions right only in
  NEW, 11 only in OLD, exact one-sided McNemar p 0.0022. By type (NEW / OLD of 100): inference 53 / 43, comparison 95 / 89,
  bridge-comparison 86 / 83, compositional 49 / 49.
- Descriptive: single readers R3r **73.0 %**, base 56.25 %, R1-full 56.0 % — R3r alone beats both unions. Stated-fact recall /
  conflicting values: R3r 91.3 / 9.8 %, base 80.6 / 19.9 %, R1-full 78.3 / 10.9 %, OLD 88.7 / 22.5 %, NEW 94.6 / 22.0 %: adding the base
  reader raises recall but doubles the conflicts, which costs more answers than it gains. Per relation R3r vs R1-full: country of
  citizenship 50 vs 7 of 62, mother 42 vs 29 of 48, father 104 vs 95 of 113, spouse 21 vs 14 of 24.
- Descriptive arm (amendment 3, --grounded): OLD 67.0 %, NEW 72.0 % (31 vs 11).
- Limit named in amendment 2: the R3r training was interrupted at step 19,000 and resumed from checkpoint 18,500.
- **Decision as pre-registered:** kit R3's reader rows are the R3r rows; the deployed Q1 reader becomes R3r (+ base per the
  registration). Next registration (descriptive finding → test): R3r ALONE vs union(R3r, base) on a new fresh set.
  Files: research/symbolic_regression/q1/r3r/r3r_test.json, stated_recall_fresh2.json.

**R2-small Part E, confirmatory (PREREG_R2_small_E.md, commit 9fe0d30 of 21.11 08:34 UTC; ALL DONE E 22.11.2026 07:10:14 UTC on the
AMD host, 20/20 runs; analysed 07:32 UTC with analyze_e.py sha256 e882b54427d783f9…, written 21.11 08:35 UTC before any run and unchanged
since; shape_bind.py e3986935…).** Mirror worlds (SLR-style contrast, mix) vs independent worlds (indep) for way-A rule writing, 10 seeds
each.
- **H-E1 fails:** testI exact mix 3.9 % vs indep 4.2 % (exact one-sided MWU U 47.5, p 0.58).
- **H-E2 fails:** testM exact mix 4.0 % vs indep 4.3 % (p 0.58).
- Descriptive: shape-exact on testI 43.1 % (mix) / 44.8 % (indep) — both arms write the right shape about half of the time and fail
  at the predicate choice, as kit R2's Qwen did; testD (chain3, join) 0 / 1,000 in both; recursion is the best family (61–69 / 500).
- **Decision as pre-registered (neither holds):** R3 is designed without mirror tasks. With the binder result (PREREG_binder), the
  predicate choice is symbolic anyway. **R2-small is complete:** Parts B–H all pre-registered; only Part H's data remedy (counterfactual
  names) changes what the tiny model reads; derivation depth, recitation, frozen or vector names, iteration and mirror contrast do not.
File: research/symbolic_regression/r2small/analysis_E.json.

**G8d-1 O1 ceiling and decision (22.11.2026 07:40 UTC; amendment 3).** 80 O1 runs (16 hard tasks × seeds 0–4) on three hosts, merged with
the main runs (1,680 runs; workstation 789, AMD 290, second host 601; 311 duplicates by first finish; 0 missing); H1–H3 unchanged after the
re-merge (p 0.70 / 0.009 / 0.69). **Median O1/U in the hard stratum 0.707** — the oracle needs 71 % of U's search cost, i.e. it beats U
by 1.41×, below the pre-registered 1.5× (O1/U ≤ 0.667). Per task (U → O1 median O2): split_ticket 3,857 → 534, reachable_port 11,712 →
2,395, task_readiness 15,000 → 6,205, pen_exposure 14,053 → 4,329, but 6 of 16 tasks are censored at the budget for both (15,000 = 15,000),
which pulls the median toward 1 (descriptive).
**Decision as pre-registered:** H1 failed and O1 does not beat U by ≥ 1.5 → one-step guidance does not pay at this scale; **the G8d line
ends.** Unseen rule shapes come from a shape grammar + binder (PREREG_binder), not from a guided gp2 search.
Files: research/symbolic_regression/g8d/d1_score_final.json, d1_collect_final.json.

### R3r2 scored — the dedicated reader alone does NOT beat the union on fresh3 (22.11.2026 09:14 UTC, date -u)
PREREG_R3r2 (frozen 04:42 UTC before any fresh3 read). Reads on the RTX 3070 host: R3r 0-shot done 08:17:36, base 2-shot done 09:13:24
UTC (run.log). Union built by the frozen score_r3r.py (db326200) in the registered order (R3r then base); answers by the frozen
official_score.py (7f9170e9, --title-anchor --tiebreak shortest) on the workstation with clingo 5.8.3 (the 3070 host has no clingo).
| arm | official alias EM | bridge_comp | comparison | compositional | inference |
|---|---|---|---|---|---|
| ALONE (R3r) | 70.25 % | 95 | 95 | 40 | 51 |
| UNION (R3r, then base) | 71.0 % | 96 | 97 | 45 | 46 |
| base 2-shot alone | 57.5 % | 87 | 80 | 32 | 31 |
**H-R3r2 fails:** right only in ALONE 20, only in UNION 23, exact one-sided McNemar p = 0.73. Decision as registered: the union stays
the deployed reader. Stated-fact diagnosis (stated_recall.py, 935 stated gold facts): ALONE recall 89.2 % / conflicts 11.3 %, base
83.7 % / 15.3 %, UNION 94.3 % / 18.9 % — the same pattern as fresh2 (union reads more, contradicts more), but on fresh3 the extra
recall pays on compositional questions (+5) and the extra conflicts cost on inference questions (−5); they cancel.
**Correction of an expectation:** the fresh2 descriptive lead of R3r alone (73.0 vs 70.75 %) did not replicate (70.25 vs 71.0) —
a single-set descriptive difference of 2 points was noise, which is why it was registered and tested before being used.
Consequence for kit R3: the reader rows stay R3r rows; the open lever is the CONFLICT rate of the union (kin-role values on inference
questions), not recall — a conflict filter in the pipeline (prefer the fine-tuned read when both readers give the same relation for
the same subject) is a pipeline step to test on development data, not a training target.
Files: research/symbolic_regression/q1/r3r/fresh3/ (score_*.json, per_*.jsonl, test_R3r2.json, stated_recall_fresh3.json).

### Reader merge: primary-first beats the plain union on development data; PREREG_R3m frozen (22.11.2026 09:19 UTC, date -u)
After R3r2 failed, the fresh3 diagnosis pointed at the union's conflicts, not its recall. Two pipeline steps were tried on fresh2
(development data now): **pref** — a base triple is kept only where R3r gives no triple with that relation for a subject sharing a
token — 70.75 → 75.25 % (21 vs 3, p 0.00014; inference 53 → 67; conflicts 22.0 → 12.35 % at recall 94.6 → 93.1 %); **snap** (copy
errors snapped to a paragraph span) changed 0 answers and was dropped (two guards were added after seeing it damage dates glued to
footnote digits and demonyms). The fresh2 union reproduced the AMD-host score exactly on the workstation (70.75 %).
A sample of R3r's remaining misses on fresh3 (12 gold facts) shows mostly 2Wiki evidence not stated in the text (Poland, Queensland,
Wessex, Childwickbury Manor) or a more specific correct read (Stoke St Gregory for Somerset), few real misses (born in New York;
"Queen consort of") and one copy error ("Brautat" for "Brita") — the training lever on reading is small now.
PREREG_R3m (docs/PREREG_R3m.md, frozen 09:18 UTC, commit e847a3c): H-M1 PREF > UNION, H-M2 PREF > ALONE on a new set fresh4
(dev_fresh4_400.json sha 448abff0…, disjoint from all four earlier sets), Holm; reads queued on the 3070 host behind the RAG-1c reads
(run_q1fresh4.sh). **Descriptive, after the freeze, on fresh3 (the set that suggested the idea — not evidence):** PREF 74.75 % vs
UNION 71.0 % (18 vs 3) vs ALONE 70.25 % (20 vs 2); by type 96 / 98 / 50 / 55.

### Where the merged reader still loses (fresh2 dev) and a domain filter that did not help (22.11.2026 09:39 UTC, date -u)
The 99 questions PREF gets wrong on fresh2, by their weakest gold fact (stated_recall.py logic): stated but not read 39, read correctly
but answered wrong 27, gold fact not stated in the text 22, read with a conflicting value 11. A sample of 16 "stated but not read"
holds ~6 real reader errors (father/son swapped, mother/spouse confused, a wrong child, an invented place of death, a missed director)
and ~10 gold noise, granularity (Mumbai vs India) or aliases (the read name is right, the gold uses another). The 27 "read correctly"
losses are mostly answer form (St. Thomas College vs "St. Thomas College, Thrissur"; 3 December 1322 vs 1322; 'Saint Arnulf' vs
'Arnulf' — official alias EM) and 8 bridge comparisons; in one the base reader gave the FILM a date of birth ("Gentlemen Prefer Blondes
(1953 film)", 1953), which beat the director's 1952.
**Domain filter (reader_domain.py), two versions, both on fresh2 only:** v1 (a subject with any work relation is a work; person
relations of works and placeholder values dropped) fell to 23.5 % — the base reader writes "country of origin" for people, so most
people became works. v2 (majority vote of work vs person relations, country of origin no signal, ties kept) = 75.25 %, 1 vs 1 — no
effect; dropped. No further variant was tried. Training lever left on reading: kin-role direction (father/son, mother/spouse) —
already the target of R3r's kin-contrast rows; the rest is gold noise and answer form.

### PREREG_R3m scored — primary-first merge of the two readers holds on new data (22.11.2026 13:10 UTC, date -u)
fresh4 (400 new 2Wiki dev questions, disjoint from all earlier sets). Reads on the user's RTX 3060 (amendment 2; 09:55–12:51 UTC, exit 0,
400 rows each; hashes as frozen), union / pref built with the frozen score_r3r.py (db326200) and reader_merge.py (b4964509), answers
by the frozen official_score.py (7f9170e9, --title-anchor --tiebreak shortest) on the workstation.
| arm | official alias EM | bridge_comp | comparison | compositional | inference |
|---|---|---|---|---|---|
| UNION (R3r, then base) | 70.0 % | 93 | 93 | 48 | 46 |
| ALONE (R3r) | 73.5 % | 97 | 92 | 47 | 58 |
| **PREF (primary-first merge)** | **75.5 %** | 94 | 93 | 57 | 58 |
**H-M1 holds:** PREF > UNION, 27 vs 5 questions, exact one-sided McNemar p 5.7e-5. **H-M2 holds:** PREF > ALONE, 12 vs 4, p 0.038
(Holm: 5.7e-5 ≤ 0.025, 0.038 ≤ 0.05). Decision as registered: the deployed Q1 reader is R3r + base merged primary-first; the base
call is kept. Development on fresh2 gave +4.5 points, fresh3 (descriptive) +3.75, fresh4 (confirmatory) +5.5 over the union.
Goal Z1 (≥ 80 %) is not reached yet: 75.5 %, gold-fact ceiling ~94 %.
Files: research/symbolic_regression/q1/r3m/fresh4/.

### PREREG_kit35 primary scored — synonym-renamed seed blocks teach copying a meaning-near name (22.11.2026 17:09 UTC, date -u)
Run 35 (kit34 + 600 synonym-renamed seed-block rows; trained on a RunPod RTX 3070, stage A 11:05–13:17, stage B 13:17–16:46 UTC;
adapters sft 4c483d43…, logic 1483f832…) and run 34 (kit34s/out_logic c9c356cb…) answered on the SAME pod.
- **H-K1 holds:** SYN-HO (64 seed blocks, each with one name replaced by a held-out synonym never in any training text) correct
  run 35 42/64 vs run 34 32/64; only run 35 13, only run 34 3; exact one-sided McNemar p 0.011. By block: P6 13 vs 6 of 22, P5 5 vs 3
  of 11, P3 5 vs 4 of 6; P1, P2, P4, P7 unchanged (4/4, 2/3, 6/9, 7/9).
- **H-K2 fails:** p67ablate P6+P7 run 35 12/16 vs run 34 11/16 (1 vs 0, p 0.5) — p6_author_renamed fixed (writer); p6_all_renamed and the
  three P7 renamed variants (unchecked, confirmed_by, all renamed) still wrong. P7 stays 5/8.
- No-harm check (15.11 targets on the full catalogue): answers still running on the pod; reported when done.
Reading: training with near-synonyms of seed names teaches the model to copy the prompt's name in many seed-shaped blocks, mostly in
P6 (the acceptance/duty block); the P7 provenance block resists — hypothesis: "unverified"/"verified" are defined BY each other there
(unverified = not verified), so renaming one of them breaks a pair the model learned as a unit.
Files: research/philosophy/kit35/results/.

### 23.11.2026 — Z2 strand: g8e result, portfolio prereg, literature in full text, helper-proposer Phase 0 (committed 14:01:59 UTC, git commit time)
**Catch-up.** The log had no entry since 22.11. 18:09; these are the steps of this strand since then. Every one has its own document
on branch sr-binder.
- **binder-G2 on g8e:** H-G1 fails (14 fewer / 18 more / 8 tie, p 0.589), so binder-G ends under the two-failures rule. Scored 06:35
  UTC with the frozen scripts. Doc: docs/SR_BINDER_G8E.md; classes of the 25 qualifying tasks: (viii) 9, (iii) 8, (ix) 5.
- **Portfolio binder-G2 + gp2 on a third blind set g8f:** docs/PREREG_portfolio_g8f.md, frozen 08:35:01 UTC (sha256 16bbbb8b…, commit
  7f810e4).
  - P1/P2 are co-primary with Holm; B = 3,200 was chosen on dev data.
  - Related work read in full beforehand: Gomes & Selman 2001; SATzilla JAIR 2008. Sources not read are named there.
  - Runs started 08:35 UTC; **running, not scored**.
  - Descriptive bound: even the per-run best of both engines beats gp2 on only 25/40 (G8d-1) and 15/40 (g8e) dev tasks, so Z2's
    35/40 is out of reach for any schedule of these two engines.
- **Z3-2:** PREREG_Z3_2 amendments 3, 3b (commits 5083ecf, bce2d3b, d66eb0e) change the schedule only.
  - The 3070 jobs run back to back after WG2, until 08:00 UTC on 24.11; same code (c317bf0a), order and seeds.
  - 3b corrects 3's wrong reason (R3 no longer uses the 3070) and its estimated heading time.
- **Paper:** a separate SR_PAPER.md written from abstracts (936a17d) duplicated this branch's papers and was reverted (f25168f). Its
  content went into DIVISION_OF_LABOUR_PAPER.md (93273af): §2.3, §2.4, and a new §2.8 "Can a model learn to find rules by itself?".
  - §2.8 rests on four systems read in FULL TEXT (DreamCoder, AlphaGeometry, FunSearch, LLM-SR; quotes checked at line numbers;
    supplements not read), and five at abstract level only.

**User decision (about 11:2x UTC; my earlier note "12:3x" was a wrong estimate):** try a learned helper proposer — a small model
proposes ONE helper definition when the binder stalls, and clingo verifies. The coordinator confirmed this session as owner. The
full texts changed the design before any code:
- DreamCoder's network does not propose helpers; its library comes from symbolic compression of found solutions. This becomes a
  baseline.
- AlphaGeometry finds its auxiliary constructions by traceback over random premises, not from a hand-written shape generator.

**Phase 0 (development only, nothing frozen; code research/symbolic_regression/hp/ on sr-binder, commits a42a034, 460678e):**
- `hp_gen.py` — traceback generator after AlphaGeometry.
  - It samples a random signature and a random layered theory; negation is only of lower layers, and the recursive step is
    h(A,B) <= h(A,N0) & q(N0,B) with an optional guard. clingo derives on 12 worlds.
  - The target is a top-layer derived predicate; its dependencies are traced back.
  - Pruning drops any rule or literal whose removal leaves the TARGET's extension unchanged (AlphaGeometry prunes vacuous auxiliary
    points the same way). The novelty flag compares against the inputs and binder-G2's templates.
  - 3 positive controls pass: a closure and a reach set are found as templates, a guarded pair closure is novel.
  - First version: tautologies (h <= h), rules that never fire (p & ~p) and disconnected literals. Fixed before any use.
  - Measured: about 11 rows/s on one core, 1.3–1.7 KB per row; about 40 % of tries give a row, and the rejects are counted by reason.
- **Finding: extension-novelty is the wrong criterion.** Many generated helpers are plain conjunctions binder-G2 can write inline. The
  right criterion is empirical: does binder-G2 solve the task without the helper?
- `hp_binder.py` — binder-G2 (frozen file unchanged) with helpers injected by wrapping Vocab.__init__. Graded score: 1 if solved, else
  the share of gold positives the accepted clauses derive (FunSearch's "rich" signal).
  - Injection was verified on hp2_4: the helper's extension is right, the gold program is exact, and its clause scores 1.0 and is
    generated at size 4.
  - But that level holds 227,189 tie-rich candidates, so 3,000 evals are too few. The engine after the proposal limits what any
    proposer can show (AlphaGeometry's DD+AR plays this role there).
- First comparison: 20 generated tasks × {no helper, gold helper}, budget 3,000, on the AMD host.
  - The gold helper rescues hp2_2 (no helper: memory kill; gold: solved at 5 evals) and hp2_14 (2,927 evals unsolved → solved at 124).
  - 5 tasks need no helper.
  - 3 stay at graded 0 even with the gold helper (binder-G2's search, see above).
- **Error and its cause (stated plainly).** 12 runs were OOM-killed by their 6 GB cgroup on the AMD host between 12:30 and 12:59 UTC,
  and the user saw it in monitoring. I had not measured peak memory first, although the same kill had already happened on the first CPU
  host. All jobs were stopped at 13:08:09 UTC; production containers were not affected.
  - **Cause, measured in one container:** binder-G2 builds each clause size level whole before it evaluates it
    (`levels[size] = list(cands.of_size(size))`). On the small task hp2_9 the levels hold 1,923 / 28,913 / 410,044 candidates at sizes
    3 / 4 / 5 (about ×14 per level). A task not solved by size 4–5 reaches level 6 and needs many GB, whatever the evaluation budget.
  - hp2_10 grew about 0.7 GB/min until the new RSS watchdog ended it at 12,004 MB with exit 3, with no cgroup OOM.
  - My first sampler stopped that measurement wrongly at 798 MiB (the pattern `*GiB*` matched the limit text "16GiB"). That is
    corrected and was reported.
- **Fixes:**
  - The watchdog (exit 3 at 75 % of the container limit, with reason and peak) runs in every job.
  - **Named generator limit:** ≤ 4 inputs, ≤ 2 constants, ternary inputs only over entities. The engine is unchanged.
  - Runners start no job after 21:20 UTC; everything on the AMD host is gone by 22:25.
- `hp_mine.py` — DreamCoder-style library from FOUND solutions only (gp2 + binder on G8d-1 and g8e): 1,218 programs, 313 helper
  definitions, 125 templates, 8 in ≥ 2 tasks.
  - The library contains transitive closure (6 tasks) and the guarded pair closure (contract_signature_deadlock, pki_trust_chain), a
    class-(iii) shape gp2 invented and binder-G2 lacks.
- `hp_format.py`: prompt mean 327 tokens (max 627), completion 39 (whole program) / 21 (helpers only), vocabulary 60.
- `hp_overlap.py`: 0 of 50 generated tasks equal a G8b-1 / G8d-1 / g8e task as a whole program; 2 share a one-predicate shape with
  G8b-1. A size threshold goes into the prereg. g8f is checked only after its scoring.
- **Next (asked of the coordinator, not started):**
  - the oracle ceiling on the 9 g8e dev tasks binder-G2 never solved, with the reference helpers, budget 15,000;
  - 20 capped generated tasks × {none, gold}.

  Both on the AMD host, 6 containers, the watchdog on.

### 23.11.2026 — helper-proposer Phase 0 results (committed 16:28:56 UTC, git commit time; doc research/symbolic_regression/hp/PHASE0.md on sr-binder, af3211a)
- **Oracle ceiling, the main result** (descriptive, development data, 3 seeds). The 9 g8e tasks binder-G2 never solved (registered
  0/27) were run with the reference's helper predicates injected, budget 15,000. Result: 5 of 9 tasks and 14 of 27 seeds solved.
  - contract_signature_deadlock: 28 evals in every seed.
  - newsroom_publishable: 206–217.
  - photo_archive_levels: 326–2,437.
  - carpentry_sole_source: 1,063–1,289.
  - webshop_coupon_scope: 2 of 3 seeds.

  newsroom, photo_archive and carpentry are solved by NO current engine; gp2 is censored on all three. Not solved:
  - phone_part_substitutes (graded 0, cause not examined);
  - scaffold_stability (its helper depends on the answer, so the oracle is incomplete);
  - plumbing_dry_taps and translation_pivot (memory guard even with the helper; this supports the Hypothese that their registered
    kills are binder-G2's level materialisation).
- **Generated tasks** (20, capped generator, none vs gold, budget 15,000): helper not needed 7; helper rescues 1; memory guard in both
  modes 7; other 5. In the generated distribution the zone where the helper decides is thin, and binder-G2's memory is the binding
  constraint.
- **Safety:** 67 jobs from 14:21 to 16:27 UTC: 0 exit 137, 0 kernel cgroup-OOM lines (journalctl -k since 14:21:18), 25 watchdog stops
  (exit 3), 2 timeouts. The production VI's embedding latency stayed at 0.49–1.50 s.
  - Correction to my earlier baseline: a whole-buffer dmesg count ("3") is not a kill count; the ring buffer drops lines. The time-bounded
    journalctl count since noon was 12.
- **Open for Phase 1 (not decided):**
  1. the engine after the proposal: a streaming binder or gp2 with helpers would be a new engine, so its own prereg, and the sources on
     bounding the search are to be read first;
  2. targeting training data to the zone where the helper decides;
  3. the ceiling bounds the gain; it does not show that a learned proposer reaches it.

### 23.11.2026 — portfolio g8f scored (scored 20:30:43 UTC by date -u; doc docs/SR_PORTFOLIO_G8F.md on sr-binder, 3977b57)
- **Runs:** gp2 U 08:35:28–18:14:57 UTC, 390/400 (vegan_candles 10 × CENSOR after memory kills, the frozen retry rule);
  binder-G2 08:35:39–20:25:11 UTC, 393/400 (guild_examiners 7 × wall limit in both tries), 0 binder memory kills.
- **Integrity:** the 8 hashes of portfolio_g8f.sha256 OK before scoring; the gp2 files checked against the GPU host's SHA256SUMS
  (18:19:12 UTC); scored with the registered command; an independent recount written from the prereg text gives the same statistics
  and p values for P1 and P2.
- **Result (A):** H-W1 (P1, 19/14/7, raw and adjusted p 0.0247) and H-W2 (P2, 18/7/15, raw p 0.0047, adjusted 0.0094) both hold after
  Holm. Candidate per prereg: **P2**. Z2 missed (18 and 19 of 40, needed 35), as predicted. Adoption and any Z2 re-definition are the
  user's decisions; the coordinating session puts them to the user.
- **Readings (descriptive):** binder-G2 alone beats gp2 U on g8f (19/14/7, p 0.028; on g8e p 0.589), and P1's counts equal binder-G2's
  own in every kind, so the effect leans on the set. P2's gain over P1 is kind a (gp2 start phase), the SATzilla pre-solving pattern
  the prereg predicted. VBS 21/40: no schedule of the two engines reaches Z2. 6 kind-c tasks unsolved by every arm.
- **Overlap check** (helper-proposer Phase 0, allowed only now): against g8f, 0 of 50 generated whole programs equal a reference;
  3 rows of s2 share a one-predicate shape (PHASE0.md §4).
- **Limits:** one blind set and author; P1 rests on a binder effect that reversed between g8e and g8f; trajectories, not one program.

### 24.11.2026 — Z3-2 scored (scored 01:31:15–01:31:26 UTC by date -u; doc docs/SR_Z3_2.md on sr-binder, 3c63ede)
- **Runs:** 3070 queue Q0, Qmem s0, Qmix s1, Qmem s2, Qmix s3, Qmem s4, all exit 0; queue end 01:21:23 UTC; vision llama-server
  restarted, chat probe OK 01:21:34. 3060: Qmix s0, Qmem s1, Qmix s2, Qmem s3, Qmix s4, all exit 0, 23.11. 08:03–21:22 UTC (STATUS.md
  e6e5d88). Every LoRA run trained its full epoch.
- **Integrity:** 3070 hash list 31/31 OK (checked in a container; the adapters are root-only); the 3060 results 6/6 per job OK on
  both hosts and equal to STATUS.md; analysis code, data and comparator hashes equal the frozen list (z3q.py per amendment 2).
- **Result (A):** H-Q1 holds (Qmix testCFN 0.557 vs tiny 0.011, MWU U 50, p 0.00033). H-Q2 holds (testI +0.068, CI [0.041, 0.096]).
  Goal Z3 missed (testCFN 0.557 < 0.85). Independent recount identical.
- **Decision per prereg:** one more registration of this approach is allowed, and it is the last. The lever comes from the
  descriptive data, before that freeze: the depth curve (testCFN 0.74 / 0.52 / 0.41) points at multi-step reading; the prereg names
  r 64, more epochs and more cf items. Not chosen; sources to be read in full text first; go from the coordinator and the user.
- **Correction (logged at the time):** my 3070 job ETAs on 23.11. used training seconds instead of job wall time; qmix jobs took
  about 135 min, not 117. Corrected to the coordinator at 00:11 UTC.

### 24.11.2026 — g8f: an ambiguous CENSOR sentence in the prereg (recounted 08:32:02 UTC by date -u; sr-binder fb414bb)
- The coordinating session recounted g8f and Z3-2 with its own scripts: identical to mine. It named one wording issue.
- The prereg sentence "Both: if gp2 is unsolved or missing … CENSOR" can be read literally to censor runs binder-G2 solved within B.
  The frozen scorer and the P1 rule ("If it has a verified exact program by then, the value is its evaluations") follow the
  portfolio reading: gp2 never runs after a binder solve.
- My own recount of the literal reading: 47 runs on 8 tasks change (binder-G2 solved within B, gp2 unsolved; none with a missing
  gp2 file). P1 14/14/12, p 0.2296; P2 13/7/20, p 0.0727; neither would hold after Holm. Same numbers as the coordinator's.
- No rescoring; the registered scorer decides. Named in SR_PORTFOLIO_G8F.md and as a limit in the paper §2.3. Lesson for later
  preregs: write the cap on the portfolio's value, not on one engine's trajectory.

### 24.11.2026 — Z3-3: the user's go, and a correction of my Z3-2 reading (step count 08:58:50 UTC by date -u)
- The user said: "ja, starte Z3-3 mit mehr mehrschrittigen Lese-Beispielen". The lever came from my reading of the depth curve.
- Before designing it I counted single steps in the 5 Qmix generations (z3/stepwise_z3_2.py, z3/failbody_z3_2.py; inputs hash-equal
  to RAW_RESULTS.sha256). **Correction:** my reading "the gap is in multi-step reading, not in single rule application" was wrong.
  Each testCFN step succeeds with about 0.73 at every position (0.741; 0.726/0.711; 0.752/0.718/0.767), so the depth curve is
  compounding (0.74ⁿ). No broken links. 84 % of the wrong grounded steps apply another trained library body.
- Hypothese: the 12 trained bodies became templates; more varied bodies, not more depth, is the matching lever. Deeper items still
  add step instances per row, but over the same 12 bodies, where testCF is already about 0.96 per step.
- Put to the user before any prereg is drafted, because the lever is the user's choice and was based on my wrong reading.
- Corrected in SR_Z3_2.md (struck through, section "Step-level analysis") and in the paper §2.4.

### 24.11.2026 — Z3-3 drafted: many rule bodies (draft 09:32 UTC by date -u; sr-binder e8df432; not frozen)
- User decision after the correction above: "ja, nimm Option 1 mit verschiedenen Rümpfen".
- **Read in full text before the draft:**
  - Chan et al. 2022 (2205.05055): the number of classes, together with burstiness, drives in-context vs in-weights learning.
  - Kirsch et al. 2022 (2212.04458): memorisation → task identification → learning-to-learn, at about 2^13 tasks.
  - Raventós et al. 2023 (2306.15063): a task-diversity threshold at 2^14–2^15 tasks; below it the model is Bayesian over the
    pretraining tasks.
  - Zhang et al. 2022 (2205.11502): statistical features; change only one thing in the generator.
  - Dziri et al. 2023 (2305.18654): compounding errors, a failure bound rather than p^n.
  - For Raventós and Zhang, the web text came only in part; the missing sections were read from the PDFs (pdftotext).
- **Correction:** SR_Z3_2.md said the p^n depth curve is "as Dziri et al. describe". After reading their Sec. 4, it is our own
  independent-step model, consistent with their argument. Struck through and corrected there.
- **Design:**
  - Two levels of body diversity, both without the 12 test bodies: qb60 (60 standard-shape bodies) and qbwide (216, with every
    argument orientation).
  - Only the bodies change against Z3-2 qmix: same R, 15,000 reading rows, depth thirds, type mix, names, recipe and budget.
  - H-B1: each arm > qmix on testCFN (exact MWU, Holm). The goal is counted per arm. This is the last registration of this approach.
- **Checks:**
  - Z3-2 qdata rebuilt with all 5 frozen hashes equal.
  - New data: every pool body occurs; no test body and no test prompt.
  - The gold round trip is 100 %.
  - analyze_z3q3.py dry run on relabelled Z3-2 outputs reproduces the step counts.
- **Bug caught before use:** the 3070 runner first mapped qbwide to the data dir "qdata3/bwide" (shell `${arm#q}`). Replaced by an
  explicit case before any run.
- **Waiting:** the coordinator's review, a 3070 smoke-test slot, and a decision on the 3060 peer and the exchange-repo push.

### 24.11.2026 — Z3-3 frozen, amended twice, smoke test passed, 3060 task pushed (date -u)
- **09:38 UTC token audit** (3070 host CPU): 0 bad rows in either arm. The longest target is 93, so the budget of 186 holds by Z3-2's
  rule too. The longest row is 777 tokens (Z3-2: 743).
- **09:39:39 UTC frozen**, sr-binder d410e57, prereg sha cebaa7bd…. The coordinator's two review points are included: the
  historical control as a named limit, and the MWU thresholds.
- **Amendment 1** (d1d99e2), a correction found by the coordinator: `mwu_one_sided`'s exact p depends on ties, and my table was the
  tied case. Without ties: U 23 → 0.0159, 22 → 0.0278, so the first arm under Holm needs U ≥ 23. The computed p decides.
- **Amendment 2** (f0b5c7b): pools.json was written with write_text, which gives CRLF on Windows, so the 3060 hash check would
  have failed. Fixed with newline="\n"; the Linux output is byte-identical.
- **Smoke test** on the 3070, 09:41:53–09:58:25 UTC, exit 0; vision server probe OK at 09:58:35.
  - Memory probe on the longest rows: 7.35 / 7.26 GB.
  - 200 steps in 792.8 s (3.96 s/step).
  - dev_cf 0.44, dev_recall 0.54 (dev values, not evidence); 0 budget hits.
- **09:59 UTC** TASK-Z3-3 and the code pushed to the exchange repo (db02a66), with the user's go relayed by the coordinator. Six
  files, synthetic data only.
- workstation's root partition was full (193 MB free). I removed 1.3 GB of my own scratch data and reported the rest to the coordinator.

### 24.11.2026 — Literature: how SR finds formulas, and SR in the thinking of a small model (11:00 UTC, date -u)
- The user asked how symbolic regression finds new formulas, and how the 0.6B model could apply SR in its thinking mode.
- Four readers read about 45 primary sources: classic and neural SR, LLM SR systems, search in thinking, and tool-integrated
  reasoning. The parts read only partly are named in the paper.
- Result in DIVISION_OF_LABOUR_PAPER.md §2.9. In short:
  - Successful SR has an exact evaluator, a complexity prior, a structure/constant split, decomposition or a library, and feedback
    from failure.
  - "Discovery" in these papers is rediscovery.
  - Models check badly in their heads (PAL 72.0 → 23.2; SatLM 69.4 → 54.5). So clingo always gives the verdict.
  - Small models gain from training inside an external loop (PiT-PO 1B: 3.28 → 99.95).
  - Agentic tool use fails at 8–14B (SR-Scientist).
  - Traces with failures teach search (Stream of Search 51.3 vs 25.7 %).
- Proposal (H): first the 0.6B as a proposer inside a clingo loop (distillation + RL in the loop), then "SR in thinking" with
  clingo calls in the trace, measured against it at equal budget. Each step gets its own pre-registration.
- T1 pilot (same day): the teacher's think mode costs 84 s per request vs 2.4 s plain, at about equal quality on 3 tasks. Plain was
  chosen for the measurement at 18:00 UTC.

### 24.11.2026 — Afternoon: L1 data built, Z3-3 queue on the 3070, workstation reboot, T1 starter relaunched (date -u)
- **Z3-3 on the 3070:**
  - qb60:1 ended 12:16:00 UTC, exit 0: 1,875 steps, peak 7.48 GB, 1 budget hit in 3,000 generations. Probe OK at 12:16:12.
  - af's slot ran 12:17:43–12:35:14. Then qbwide:1, qb60:3 and qbwide:3 started at 12:35:14 (deadline 25.11. 06:00, the
    coordinator's go).
- **L1 preparation (user: "ja mache das so"):**
  - g8g was written by an independent author agent: 40 tasks, check PASS. Hashes are in sr-binder c7b11ec; I am not reading it.
  - 20,000 generated tasks became 79,592 training rows (direct 20,000, repair 39,709, relabel 19,883), 276 MB in ~/Dev/data/sr-l1
    (sr-binder 3105294).
  - L1 stops here until the user's go.
  - **Correction:** I did not record the time of the user's "ja mache das so" with date -u. It lies between 11:00:42 and 11:42:01
    UTC (commits). The "~11:25" in the VI status was an estimate.
- **T1:**
  - Amendment 1 (4f22825): the guard drops the VI-search check (coordinator: the production VI stalls for unrelated reasons).
  - workstation rebooted at 13:16:55 UTC (kernel 7.0.0-38 → 7.0.0-43); my detached T1 starter and the scratchpad were lost.
  - Relaunched 13:23:36 UTC as a user systemd unit (t1-launch, linger on), after checking all hashes (PLAN_T1, amendment 1, guard,
    teacher: OK).
  - Caught before 18:00: inside a systemd unit ssh had no agent (publickey denied), so the guard would have paused all night. The
    unit now carries SSH_AUTH_SOCK, and ssh tested inside a unit returned rc 0.
  - Known cosmetic fault: the launcher's own hash-check line uses paths relative to the wrong directory and will log a failure. The
    check was done by hand instead (above).
- **Second workstation reboot at 14:13:36 UTC (apt upgrade):** the transient t1-launch unit was gone again.
  - ssh from workstation failed through the sss known-hosts proxy ("Connection closed by UNKNOWN port 65535").
  - Relaunched 14:27:38 UTC as a persistent, enabled user unit. It starts after a reboot, resumes (teacher.py skips finished rows)
    and exits after "all done".
  - The guard's ssh goes through a PATH wrapper with ProxyCommand=none, sss known hosts and the <admin> key, so it needs no agent.
  - Tested in a unit without an agent: MemAvailable 3.48 GB, io 14.89 %, probe 0.44 s. gpu-host-3 is below the 4 GB guard limit
    now, so T1 may pause at 18:00.
- **3070** (coordinator: the card must be free by 21:00, the user's booking runs 21:30–06:00): qbwide:1 was at step 1,781 at 14:28
  UTC. Estimated ends: qbwide:1 about 14:51, qb60:3 about 17:07, qbwide:3 about 19:22 UTC.

### 25.11.2026 — Z3-3 scored (05:31:15–05:31:32 UTC by date -u; sr-binder docs/SR_Z3_3.md)
- **All 10 jobs exit 0 on the first try.**
  - 3070: 24.11. 10:01–19:19 UTC.
  - 3060: 24.11. 10:03 – 25.11. 05:27 UTC. The 3060 built qdata3 itself, and its hashes passed, so amendment 2 worked.
- **Every hash was checked before scoring:** frozen code and data, the amendment-2 files, the 3060 runner, and all result lists.
- **Result:**
  - H-B1 holds for qb60 (0.726, U 24, p 0.0079) and qbwide (0.629, U 22, p 0.028) against Z3-2 qmix 0.557.
  - Goal Z3 is missed.
  - H-B2 is not shown.
  - Recount with scipy and my own bootstrap: identical.
- **Decision per prereg:** body diversity helps reading but not enough. This was the last registration, so the approach ends.
  Continuing the in-model route to Z3 is the user's decision.
- **Descriptive:**
  - The template hypothesis of Z3-2 is supported: steps applying another trained body fall from 959 to 43 / 34.
  - The new bottleneck is grounding: cited facts that the world does not hold (757 / 1,072).
  - qbwide is worse than qb60.
  - Seed 4 is low in both arms; qbwide s4 stops at depth 3–4 on testD.
- **T1 runs on past 08:00** (coordinator, amendment 5): hard stop 11:00 UTC, resume at 18:00 if unfinished. At 05:29 UTC 979 of
  1,280 rows were done.

### 25.11.2026 — Consolidation day: user decisions, paper, Z3 research and the Z3-G proposal (date -u)
- **08:31:01 UTC:** the user's decisions arrived through the coordinator.
  1. Document Z2 and Z3 in DIVISION_OF_LABOUR_PAPER.md.
  2. "Z3 weiter machen, aber vorher wie immer im Internet recherchieren".
  3. Z2: the L1 decision follows after T1.
- **Paper (6353c95, 034cb55):** the summary gains Z3-3; a new §2.10 covers the T1 and L1 state. session-af added §2.11 CT S0 (Z12)
  in 13a46a4.
- **Research, full text** (three readers; parts read only partly are named in their reports):
  - faithful step-wise reasoning: SI, Faithful Reasoning, ProofWriter, LAMBADA, LogicGuide, NLProofS, Lightman, LogicReward;
  - constrained decoding and copying: GCD, Outlines, GopherCite, pointer networks, Lookback Lens, CAD, FactTune, Context-DPO, CANOE,
    induction heads, Jelassi;
  - small-model errors: Allen-Zhu 2.1/2.2, Ruis, Anil, McLeish, Fan, RuleTaker, Zhang, Yue, Spurious Rewards.
- **Diagnostics of Z3-3** (f6f2bc3): 670 of 673 hallucinated atoms are near misses. In 433 of 650 steps the model picks a wrong target
  entity and confabulates a matching body.
- **Proposal PROPOSAL_Z3G.md** (c877293): a new approach, "grounded selection". Body atoms are selected from the given facts by
  constrained decoding.
  - Stage G-a re-decodes the 10 Z3-3 adapters, paired, with no training.
  - Stage G-b only if G-a misses the goal.
  - Sent to the coordinator for the user's go. Nothing is frozen and nothing runs.

### 25.11.2026 — Z3-G stage a scored (11:07:29–11:07:50 UTC by date -u; sr-binder docs/SR_Z3G_a.md)
- **Go and freeze:** the user's go arrived at 08:48:46. Smoke on dev 09:00:00–09:00:25. PREREG_Z3G_a frozen at 09:01:31 (5f66431).
- **Runs:** 15 re-decoding jobs on the 3070, 09:01:41–11:06:37, all exit 0. Vision probes OK at 10:07:18 and 11:06:49. The card was
  free before the 12:00 hard end.
- **Result:**
  - H-G1 fails: qb60 testCFN 0.7273 constrained vs 0.7270 unconstrained, sign-flip p 0.125.
  - H-G2 fails.
  - The goal is missed.
- **Mechanism:** the constraint removed every "fact not given" failure (757 → 0) but turned them into existing-but-wrong facts
  (64 → 818). This confirms the diagnosis that the model chooses the wrong entity before it writes the body.
- **To the user:** whether and how Z3 continues (a fix on the choice: select-then-infer order, whole-fact scoring, or training,
  stage G-b).
- **T1:** hard-stopped at 11:00 UTC with 1,275/1,280 rows and 96 request_failed (g8e 13, G8d-1 83). It resumes at 18:00 UTC with
  the amendment-4 retry. No outcome has been counted.

### 25.11.2026 — Z3 paused (12:01 UTC by date -u)
- The coordinator recounted Z3-G a: identical.
- User decision, relayed: "Pause Z3, rules to clingo". Reading a given rule goes to clingo (division of labour); Z12 arm G
  (§2.11) tests it. Z3 rests until Z12 S1 has results. The coordinator updates the GOALS row.
- Recorded in SR_Z3G_a.md and paper §2.4, with a link to §2.11. No Z3 run is planned.
- T1 resumes at 18:00 UTC; the L1 decision follows with its result.

### Z1 taken over; diagnosis, literature, step 0 (25.11.2026, date -u 08:30–12:28 UTC; branch z1-reader)
User decision "Z1 verfolgen wir weiter" (relayed 08:30:54 UTC); owner now the vi-facts session. Everything below is development
evidence on the spent sets fresh3/fresh4; files in research/symbolic_regression/q1/z1/.
- **Reproduction:** PREF on fresh4 rebuilt from the peer's reads (r3r 6323e31b…, base c1d032ee…) with the frozen scripts — 75.5 %,
  per question identical. Gold-fact ceiling on fresh4 94.5 %.
- **Diagnosis (DIAGNOSIS_Z1.md):** 83 reading losses — missed 38, not stated 19, read ok but answered wrong 19 (about 13 answer
  form), conflict 7; 31 of 44 missed gold facts are in neither reader. A relation type guard (the Z5 lead) changes 0 answers on both
  sets; a perfect GOLD arbiter between the two readers gives +0.25 (fresh4) / +2.0 (fresh3). No pipeline step over today's reads
  reaches +18.
- **Literature (LITERATURE_Z1.md, 15 papers in full text):** voting on executed results works (MBR-EXEC, Spider 50.8 → 63.6, Table 2,
  checked in the PDF); hard constrained decoding hurts sub-3B models; solver-error repair fixes syntax, not meaning; 2Wiki gold is
  Wikidata with a string-presence check (Ho et al. 2020 §3.2).
- **Step 0 (PLAN_Z1_step0.md frozen 09:01:28 UTC; RESULT_Z1_step0.md):** R3r sampled K = 8 (T 0.7, top_p 0.8, top_k 20) on 198
  questions (98 PREF-wrong + 100 right), clingo answer per sample, majority vote (MBR-READ). 3070 slot 12:00:11–12:27:02 UTC; vision
  probe OK 12:27:17. **Gain 10 of 98, harm 1 of 100, extrapolated net +6.98 per 400 (threshold +12 → NO-GO); coverage of unread
  stated gold facts 9/42 = 21.4 % (< 30 % → teacher path proposed).** K = 8 batched costs 3.47 s per paragraph, about one greedy
  read. Next (needs a go): step 0b, a ≤ 9B teacher reads the same 462 paragraphs to measure its coverage of the 42 facts.
