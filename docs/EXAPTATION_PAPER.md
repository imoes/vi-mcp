# Exaptation in an agent memory — can a VI find a mechanism learned for one purpose that helps another?

Working paper, vi-mcp, 2026-11-18. Every number names how it was obtained. Evidence levels: **A** own measurement, reproducible
(script, command, fixed data); **B** primary source read in full; **C** abstract, press or excerpt only (named as such). A claim without
evidence is marked **hypothesis**. All experiments below were pre-registered (hash and commit before any outcome) unless marked
exploratory.

## 0 Summary

Exaptation is a feature that helps in a role it was not built for (Gould & Vrba 1982). The unified-shader GPU — built so that vertex
and pixel work share one kind of processor — became the general parallel computer on which deep learning was first trained; the
historical record is in §2. We asked whether a VI — a shared memory of AI agents that shows hints before actions and measures their
effect — finds such transfers in its own experience, and whether representing them in embedding space helps.

So far it does not. On a production copy (8–16 Nov 2026, ~15,500 labelled actions):
- hints shown **outside** the context they were learned in show no measurable effect (matched lift −0.7 ± 0.8 points over 10,572
  showings), and agents marked them misleading 75 times against 20 times helpful (§5.4);
- problem → fix relations as **embedding offsets** do not beat the plain nearest neighbour (ΔMRR −0.001 ± 0.046; §5.5), and in new
  contexts they hurt (n = 12, exploratory);
- the "mechanism" clusters the offsets form are mostly format artefacts (4 of the 5 largest).

The literature explains why (§3): retrieval is driven by surface similarity, soundness by relational structure (Gentner); offset
"analogies" are largely nearest-neighbour effects (Linzen); successful analogy systems separate purpose from mechanism and gate on a
near purpose (Hope et al.). What that literature has not done — outcome-measured transfer in a real, growing memory of problem → fix
episodes — is what a VI can add (§6). The first piece is built: every knowledge object now records what it was built for (§6.1).

## 1 Definitions

- **Adaptation** — a feature built for its current role. **Exaptation** — a feature that enhances fitness but was "not built by natural
  selection for its current role", either a prior adaptation or a nonaptation later co-opted; "adaptations have functions; exaptations
  have effects". **Secondary adaptation** — later shaping for the new role. **Preaptation** — a potential exaptation, not yet realised
  [1] (B).
- **In a VI:** an object (insight, rule, skill) has a **built-for** context — the hosts, tools, topics and errors it was learned in. A
  **co-opted use** is a use whose context lies outside built-for. It counts as an exaptation only if the use **helped**, measured as a
  matched lift (same instance, tool and host, ±24 h, ≥ 2 SE), never as a raw success rate (raw rates are confounded by failing hosts —
  the reason the VI's weight audit was corrected in 0.70.2).
- **Genius criteria** used throughout (project protocol): a candidate is **true** (its prediction, stated before the outcome, came true
  in a matched comparison), **novel to the collective** (not derivable from older objects and not found by any baseline or other
  generator), and **impactful** (a measured effect). Classes: known, talent (true but also found elsewhere), genius (true, novel,
  impactful), promising (true and novel, impact unmeasured), refuted, disputed, open.

## 2 The worked case: unified shaders → general GPU computing → deep learning (B)

- **Built for graphics.** NVIDIA's Tesla architecture (GeForce 8800, November 2006) unified vertex and pixel processing — 128 streaming
  processors in 16 multiprocessors, 768 threads per multiprocessor, 32-thread warps — motivated by graphics: unbalanced vertex/pixel
  load and the DirectX 10 geometry shader. The authors: "the generality required of a unified processor opened the door to a completely
  new GPU parallel-computing capability" [2] (B). The Xbox 360 GPU had "48 parallel unified shaders" in 2005 [3] (B); NVIDIA's own paper
  says "The XBox 360 introduced an early unified GPU in 2005" — G80 was the first unified **DirectX 10** GPU, not the first unified GPU.
  CUDA was already in G80's launch brief, so the step to computing was partly designed in: an adaptation plus the earlier exaptation.
- **The pure exaptation came first.** Before CUDA, general-purpose computing on GPUs recast problems "into graphics terms": arrays as
  textures, a screen-aligned quad, one fragment program per element, gather but no scatter, no integers, often dozens of passes; a
  Radeon X1900 XTX measured 240 GFLOPS against a 25.6 GFLOPS peak for a contemporary CPU [4] (B). A high translation cost — the
  functional shift needed a re-description of the problem.
- **The effect.** AlexNet: "between five and six days to train on two GTX 580 3GB GPUs", 60 M parameters, size "limited mainly by the
  amount of memory available on current GPUs", ILSVRC-2012 top-5 error 15.3 % against 26.2 % [5] (B). The chain graphics → GPGPU → CUDA →
  deep learning is our synthesis; [5] does not mention graphics.

## 3 Prior art: who connected exaptation, analogy and vectors before

| Source | What it did | Numbers (as printed) | What it means here |
|---|---|---|---|
| He, Lee & Lee 2024 [6] (B) | exaptation of a patent = content similarity (sentence-embedding cosine of abstracts) × field distance (1 − Jaccard of CPC codes) to each cited ancestor; 3,420,673 US patents 1980–2010 | E_min → CD5 0.0739 (+1 SD → +18.3 % disruption); many scattered sources predict LESS disruption | "exaptation in vectors", measured backward at creation; no outcome beyond citations |
| Mastrogiorgio & Gilsing 2016 [7] (B) | forward measure: share of later citing patents whose class lies outside the focal patent's classes and the uses envisioned at grant (non-anticipation); 19,076 patents | directions only (coefficients as images): inverted U in complexity, analogical ability + | the built-for record makes non-anticipation checkable |
| Hope, Chan, Kittur & Shahaf 2017 [8] (B) | separate **purpose** and **mechanism** vectors from 8,500 product descriptions (crowd-annotated, BiGRU) | precision@top 1 %: mechanism 0.739, TF-IDF 0.63; ideation: P(good idea) 0.71 [0.48, 0.87] vs 0.28 with near purpose + far mechanism | the effect came with a **purpose gate**; retrieval gain alone was small |
| SOLVENT 2018 [9] (B) | background/purpose/mechanism/findings annotations of 50 papers | purpose+mechanism vs all words: 0.92 vs 0.67 @K1 %; crowd labels "almost entirely" erase the mechanism advantage | domain words must be stripped before embedding |
| Gentner 1983; Gentner, Rattermann & Forbus 1993; Forbus, Gentner & Law (MAC/FAC) [10] (B) | analogy maps relations, not attributes; two-stage retrieval: cheap vector match (MAC), structure mapping (FAC) | soundness of analogies 4.16 vs surface 2.70, but recall 0.12 vs 0.53 | an embedding nearest neighbour is MAC without FAC |
| Mikolov et al. 2013; Linzen 2016 [11] (B) | analogy by vector offset; its critique | offset 65.6 %; but the nearest neighbour of b alone gives most of it (ONLY-B 0.70 on plurals; ADD tracks ONLY-B, r = 0.72) | our G5 is Linzen's effect on problem → fix pairs |
| Aamodt & Plaza 1994 [12] (B) | case-based reasoning: retrieve, reuse, revise, retain; CBR as "intra-domain analogy" | review, no data | a VI hint is copy-reuse; CBR predicts cross-context copy fails without adaptation |
| Webb, Holyoak & Lu 2023 [13] (B) | analogical reasoning in a large LLM | matrices OR 1.88 vs humans; story analogies humans better (OR 0.37); with distractor stories the model ignores the analog until told | LLMs map analogies in context but cannot retrieve episodes — the VI's job |
| Kang et al. 2022 [14] (B) | aspect-based analogy search for researchers | creative adaptation 53 vs 3, mediated by a PARTIAL purpose match | gate on the problem, vary the mechanism |
| Procedural-memory retrieval, arXiv 2511.21730 [15] (B, preprint) | LLM-written object-free summaries of agent trajectories | MAP 0.754 → 0.671 in distribution; judge = the same LLM, κ 0.178 with humans | abstraction costs in-distribution precision |

Absence found (three searches plus reference lists — a search result, not a proof): no study embeds LLM-extracted purpose and mechanism
of real problem → fix episodes and measures transfer by the **outcome** of the task it was transferred to.

## 4 Method

- Data: a production copy of a VI (16 Nov 2026), read-only. Cutoff **T = 2026-11-13**: methods see objects before T, are judged after.
- Controls in every experiment: random, popularity (preferential attachment), the plain nearest neighbour where embeddings are used,
  shuffled pairs; multiple tests with Holm.
- Pre-registration: the plan is written, hashed and committed before any outcome is computed; deviations are reported as such.
- Privacy: private and internal VI content stays on site; external models only see public material.

## 5 Experiments and results (level A)

### 5.1 Context: which structure predicts truth and impact? (G1, external data)
Impact4Cast concept graph (dated concept pairs, later citations), slices ≤2016 → 2017–19 and ≤2019 → 2020–22, 2 M never-connected pairs
each. A pair becoming connected (TRUE): AUC bridge × distance 0.889 / 0.891, popularity 0.853 / 0.857, pure distance **0.102** (anti-
predictive). Which new connection becomes top-5 % cited (IMPACT): all scores 0.46–0.53. Structure predicts truth, not impact.

### 5.2 Judged novelty vs executed success (G2, external data)
Ideas of a published human study reviewed before and after execution (n = 43 executed): judged novelty → executed effectiveness
Spearman ρ −0.142 [−0.475, 0.208]; → soundness −0.032. The study's own tables were reproduced exactly. Judged novelty does not predict
success.

### 5.3 Exploring more widely (G3)
Sampling candidates from softmax(score/T) on G1's pool: greedy gives 24× more true connections but no novel true ones; novel true and
"genius" (true ∧ distant ∧ top-5 % impact) rise with T up to uniform sampling, where the genius yield equals the base rate (21 / 2 M ×
10 k ≈ 0.105). Volume works; selection by these scores adds nothing. Formally undecided (power guard: 18 genius pairs in one slice).

### 5.4 Do hints help outside their origin context? (G4)
15,485 labelled actions, 17,468 hint showings. Matched lift: same context −1.0 ± 1.6 points (5,914 showings), cross context −0.7 ± 0.8
(10,572), cross tool +0.8 ± 0.3 (982 — mostly one remote-access fact shown before shell commands, a naming artefact). Direct agent
feedback: helped : misleading = 278 : 93 for same-context hints, **20 : 75** for cross-context hints. The pre-registered "worth building
mechanism edges" rule passed only on construct-invalid candidates (generic reflex templates with negative lift) and was set aside.
Limit: origin tags included tags added later — fixed by §6.1.

### 5.5 Problem → fix relations as embedding offsets (G5)
153 train / 96 test pairs (failed action → the next successful one in the same conversation; solution skills; documents with cause and
fix sections), embedded with the VI's embedding model. Retrieval of the true fix:

| method | MRR | R@10 |
|---|---|---|
| nearest neighbour of the problem (no offset) | 0.394 | 0.510 |
| mechanism offset (cluster of train offsets) | 0.393 | 0.562 |
| one global offset | 0.427 | 0.521 |
| midpoint | 0.366 | 0.500 |
| random | 0.020 | 0.052 |

ΔMRR (mechanism − nearest neighbour) −0.001, CI ±0.046, Holm 0.95. On test pairs from a context no train pair of the mechanism had
(n = 12): ΔMRR −0.167. Cross-context offset consistency was above shuffled pairs (0.032 vs 0.014, p 0.001), but four of the five
largest clusters were artefacts (call/result formatting, shell → shell, document section labels, dictionary-shaped skill fields); one
was a plausible mechanism (a browser tool fails → fall back to the shell, in 6 contexts).

### 5.6 Running
- **G5b** — the same pairs, first abstracted by a local LLM into context-free problem and fix mechanisms (each text alone, no leakage),
  then embedded and tested like G5. A second local teacher arm was stopped before scoring (user decision: the goal is to train the
  vector space, not to compare teachers).
- **G6** — a *trained* relation map (ridge regression p → s − p, i.e. a learned TransE-style relation) on raw texts and on the
  abstractions, with a learning curve (25–153 pairs), Linzen's direction-reversal control and 200 shuffled refits.

### 5.7 G7 — a domain-free purpose slot does not beat normal search (refuted, public data)
Pre-registered 19.11.2026 (sha256 e6b6f51f…, amendment 1 7f89073c…; arms of normal search frozen before any label). 500 pages of
unix.stackexchange.com (CC BY-SA, dump 2026-06-30), 100 queries (title + question), candidates only from a far domain (no shared SE
label), top 3 per arm. N = the VI's hybrid search (bge-m3 + BM25, rank fusion); R = random; P = cosine of domain-free purpose
sentences written by glm-5.3-flash from the question alone (1,000 calls, 0.041 USD); A = query purpose vs candidate purpose +
mechanism (the G5b replication). 994 deduplicated (query, candidate answer) items were judged blind by eight Claude subagents
(another family than the teacher; arms and hypothesis unseen): "would the technique, adapted, solve or substantially help?"

| per query, top 3 | N normal | R random | P purpose | A purpose+mechanism |
|---|---|---|---|---|
| `yes` (mean) | **0.07** | 0.00 | 0.04 | 0.04 |
| queries with a `yes` | 7 | 0 | 3 | 4 |
| `yes`+`partly` (mean) | 0.29 | 0.00 | 0.33 | 0.32 |
| queries with `yes`/`partly` | 25 | 0 | 27 | 25 |

- **H1 (P > N) refuted:** P better on 2 queries, N on 5, exact sign test p = 0.45 (Holm 0.45). With `partly` counted: 17 vs 13,
  p = 0.58. A vs N: 1 vs 4, p = 0.38.
- **H2 (N > R) supported:** 7 vs 0, Holm p = 0.031; with `partly` 25 vs 0, p = 6·10⁻⁸ — the judge discriminates, the floor is real.
- **Limit:** transferable far-domain mechanisms are rare in a pool of 500 (11 `yes` in 994 items), so the test has little power for a
  small gain; one judge family; one site. It agrees with G5b: abstracting into domain-free text does not find more transferable
  mechanisms than the plain hybrid search. Hope et al.'s gain came with crowd-annotated slots and a purpose gate inside one product
  domain; G7 does not reproduce it with LLM slots across Unix sub-domains.

### 5.8 G8 — an evolutionary search over rule blocks, stopped as invalid by construction
G8 (pre-registered 19.11.2026, sha256 f57c28bc…) asked whether a library of formal mechanisms — the rule blocks of the philosophy
packages kollektiv, messung and code — helps an evolutionary search (genetic programming with the solver as fitness) solve six
problems of other domains, against random start rules (Z), the text-nearest block (T) and mapping only (S). An independent review by
a second model (Claude Fable, read-only, file:line evidence) found it unable to show exaptation, and the runs were stopped at 119 of
240; no result is reported:
- the six tasks were library blocks with renamed predicates (e.g. the package-cycle task equals code:P2 down to its variable names,
  the bipartisan task equals kollektiv P10's `bridged`) — written by the experimenter, who knew the library;
- the random arm could not build helper predicates or recursion and drew malformed rules (56–91 % with a repeated variable), so
  "library beats random" would have compared well-formed with crippled rules;
- the library arm's solutions were draws of the start phase (lookup by enumeration, not evolution);
- "solved" was unsound: a non-recursive program passed the cycle task because no test world had a cycle of length 4;
- a mapping operator shared one variable for every missing argument; origin labels survived crossover;
- the unit of analysis is the task (n = 6; best two-sided sign test p = 0.031, 0.094 after Holm), not 60 (task, seed) pairs.
Lesson kept for G8b: tasks written blind to the library and graded by structural distance, a scrambled-library control of equal
shape, equal expressiveness for every arm (invented and recursive helper predicates), lexicase selection with a size archive,
canonical forms with a cache, and "solved" as equivalence on an exhaustively enumerated domain plus a stress check.

### 5.9 G8b-0 — symbolic regression over rules finds 5 of 6 mechanisms from data alone
Symbolic regression searches the space of formulas for one that fits data and stays short (genetic programming: Koza 1992; AI Feynman,
Udrescu & Tegmark 2020; PySR, Cranmer 2023; SRBench, La Cava et al. 2021). G8b transfers it to rule sets: candidates are ASP rules in
clingo-object notation; mutation changes predicates, variables, constants, literals and negation; crossover exchanges parts of rule
bodies with variable unification; the search may invent helper predicates, also recursive ones; selection is lexicase over the example
worlds (Helmuth, Spector & Matheson 2015) with an archive of the best fit per size; every candidate is reduced to a canonical form and
evaluated once. "Solved" means equal answers to a hidden reference on every world of an exhaustively enumerated small domain and on
200 larger stress worlds that hold values never seen in training; a failure there adds the counterexample to the training worlds.

Without any library (6 tasks, seeds 0–9, budget 20,000 evaluations): 42 of 60 runs solved —
| task | solved | median evaluations | what was found |
|---|---|---|---|
| trusted reading | 10/10 | 102 | the reference |
| dependency cycle | 10/10 | 107 | an invented recursive transitive closure, then the cycle test |
| sensor state | 10/10 | 2,349 | four-valued state with negation |
| release gate | 7/10 | 1,322 | ONE rule where the reference has two (size 7 vs 8) |
| bipartisan | 5/10 | 4,054 | the general law "a supporter of party P and one not in P" |
| lineage root | 0/10 | — | recursion plus a negated projection: not found |
Two lessons: exactness on a closed set of values admits a "talent" program that lists the known colours (it failed 44 of 200 worlds
with an unseen party once those were added); the search can find a SHORTER law than the human reference. Whether a library of
mechanisms from another purpose helps (exaptation) is G8b-1 (§5.10).

### 5.10 G8b-1 — a library of mechanisms helps by reuse as it is, not as a seed for modification
Pre-registered after two independent reviews (hashes of protocol, search, arms and scoring frozen before the first run and verified
before scoring). 33 everyday tasks written by an agent that never saw the library; four arms with the same search and the same budget
(15,000 evaluations after the start phase): **L** library, **XR** library rewired (variable occurrences permuted inside each rule —
same predicates, signs and lengths), **XL** library relinked (rules intact, references between rules redirected), **Z** random rules.
Seeds 0–9, 1,320 runs, no setup failure. Ten tasks are trivial (random rules solve them in the start phase in ≥ 8 of 10 seeds); the
tests run on the other 23. Unit = task; statistic = sum over tasks of mean rank differences, 10,000 sign flips, Holm over three tests.

| hypothesis | measure | result | Holm p |
|---|---|---|---|
| H1 search path: the wiring of L makes the search AFTER the start phase cheaper than XR | evaluations to first verified solution, pairs without a start-phase hit | median cost ratio XR/L 1.10, 95 % CI [0.93, 1.24] — excludes the smallest effect of interest 1.5: **not supported** | 0.28 |
| H2 lookup: L solves in the start phase more often | share of runs | L 25.7 % vs XR 10.4 % (XL 19.6 %, Z 0 %) | 0.0003 |
| H3 total cost | evaluations from the first start candidate | ratio 1.12 [1.05, 1.53] in L's favour | 0.0003 |

Solved within budget: L 94.3 %, XR 89.1 %, XL 93.9 %, Z 88.7 %. Secondary, without a claim: L vs random rules on total cost p = 0.49,
L vs XL p = 0.06. Robustness (amendment 1): 1,238 of 1,242 first solutions also hold on 1,000 new larger worlds per task; counting the
4 others as unsolved changes no conclusion (H1 p = 0.22, ratio 1.09 [0.95, 1.24]).

Reading: the library pays off as **co-option without change** — a mechanism from another purpose, mapped onto the new vocabulary,
solves the task as it is (Gould & Vrba's exaptation in the narrow sense). Its rule structure does not make the evolutionary search for
a *modified* mechanism measurably faster, and over all tasks random rules are not worse in total cost.

Provenance (the protocol's descriptive analysis; implemented after the data were seen, `provenance1.py`): share of first solutions
with a non-trivial rule matching a rule of the origin block under the renaming-invariant key —
| | found in the start phase | found by search |
|---|---|---|
| L vs its origin block | 87 % (n = 79) | 48 % (n = 219) |
| XR vs its UNSCRAMBLED origin block | 78 % (n = 41) | 46 % (n = 244) |
| XL vs its unscrambled origin block | 86 % (n = 65) | 46 % (n = 236) |
| L vs the mean of all other blocks | 20 % | 33 % |
Solutions found by search keep the origin's structure barely more often from the true block (48 %) than from its rewired copy (46 %):
the search arrives at the same structures whichever start it had — they come from the task, not from the lineage. 40 first solutions
had no recorded library origin (lineage lost, 13/17/10 in L/XR/XL) and 14 came from immigrants; both are left out and counted.

### 5.11 G8d — the candidate itself tells which edit helps (G8d-0 passed)
After G8c-0 (a static, even oracle, per-task operator prior saves too little: median ratio 1.40 < 1.5), the proposer must see the
CANDIDATE. G8d asks which representation of the current program predicts the single edit that improves it. Text embeddings were ruled
out by design: they embed names, and the proposer only sees anonymised identifiers. Candidates were computed, not trained: the
program's behaviour on its training worlds (F0: score, true/false positives and negatives — free in the search), an exact 1-hop context
encoding of its structure (S, name-free), and their combination; a vector-symbolic projection of S [22] and a contrastive encoder of
our own [21] were held back until S or F proved informative. Program embeddings from execution traces [19, 20] are the closest prior
work; ours are exact because the solver supplies the semantics.
Step 0: the search was copied with an edit log and replays 12 of 12 stored runs bit-identically; 660 runs (33 tasks × 10 seeds × two
arms) gave 1.12 M clean single-edit children. The gate was frozen before the data and measures the AUC **within the parent** — the
pooled AUC (0.81 for F0) rewards parent headroom, which no proposer can use. Two computational amendments (memory; at most 300 records
per run and an exact rank-based AUC, byte-identical on the pilot) came before any result. **Result:** within-parent AUC operator +
size 0.632, wiring-blind signature 0.704, structure 0.720, behaviour 0.746, **structure + behaviour 0.770** — margin +0.066,
task-bootstrap 95 % CI [0.017, 0.115], 83,733 edits from 31 tasks. Behaviour carries most of the signal; the information is real but
moderate. Whether it pays in search is G8d-0b (an oracle that knows the improving edit must make the 12 hard tasks ≥ 1.5× cheaper),
which is running. G8d-0 excludes names by design, so it says nothing about names; whether names act as retrieval keys is tested
separately (fine-tuning paper §5.27–5.29, hypothesis H12/H13) [23, 24].

## 6 What the VI changes

1. **built_for (implemented, branch built-for).** Every knowledge object records on its first save the context tags it was learned in,
   its instance, index and time; no later save or update changes it; objects stored before get the named state "unknown origin". It
   makes the forward measure of [7] possible: a later successful use outside built_for.
2. **Two-stage retrieval (proposal).** Embeddings as MAC (cheap candidates), a structural check as FAC — in clingo-object, over facts
   `mechanism(M)`, `instance_of(X, M)`, `near(A, B)` derived from the vector space — and the outcome as the judge. Hypothesis.
3. **What to deliver (proposal from [8, 12, 13, 14]).** Gate on a near problem/purpose first, then prefer a different mechanism; frame
   the hint explicitly as an analogy ("map X → Y"); deliver the solution path including failed attempts (derivational reuse), not only
   the result.

## 7 Next data

- Stack Exchange operations sites (Server Fault, Unix & Linux, Ask Ubuntu, Super User; dump of 2026-06-30, CC BY-SA, attribution kept
  per record): question + accepted answer as problem → fix pairs; questions closed as **duplicates** are human-confirmed "same problem,
  other words" pairs — across tags, gold analogies for exaptation. Being fetched on a separate machine.
- The training goal: the trained relation map (G6) and later an embedding fine-tune, then the facts it yields as part of the training
  language of a small language model trained from scratch.

## 8 Threats to validity

One production copy of about ten days, dominated by two sources; sparse direct feedback; G5 pairs are few (96 test pairs) and partly
format-laden; the embedding model is fixed; the teachers available locally are of one model family; external-data results (G1–G3)
are about scientific concepts and ideas, not operations. Prior-art numbers are as printed in the sources, several without tests of
significance.

## References

1. Gould, S. J. & Vrba, E. S. Exaptation — a missing term in the science of form. Paleobiology 8(1), 4–15 (1982).
2. Lindholm, E., Nickolls, J., Oberman, S. & Montrym, J. NVIDIA Tesla: A Unified Graphics and Computing Architecture. IEEE Micro 28(2) (2008); NVIDIA GeForce 8800 GPU Architecture Overview, TB-02787-001 (2006).
3. Xbox 360 system architecture, Hot Chips 17 (2005).
4. Owens, J. D. et al. A Survey of General-Purpose Computation on Graphics Hardware. Computer Graphics Forum 26(1) (2007).
5. Krizhevsky, A., Sutskever, I. & Hinton, G. E. ImageNet Classification with Deep Convolutional Neural Networks. NeurIPS (2012).
6. He, Lee & Lee. Innovation beyond intention: harnessing exaptation for technological breakthroughs. arXiv:2412.19662 (2024).
7. Mastrogiorgio, M. & Gilsing, V. Innovation through exaptation and its determinants. Research Policy 45(7) (2016).
8. Hope, T., Chan, J., Kittur, A. & Shahaf, D. Accelerating Innovation Through Analogy Mining. KDD (2017). arXiv:1706.05585.
9. Chan, J., Chang, J. C., Hope, T., Shahaf, D. & Kittur, A. SOLVENT: A Mixed Initiative System for Finding Analogies between Research Papers. CSCW (2018). doi:10.1145/3274300.
10. Gentner, D. Structure-mapping. Cognitive Science 7 (1983); Gentner, D., Rattermann, M. J. & Forbus, K. D. The roles of similarity in transfer. Cognitive Psychology 25 (1993); Forbus, K. D., Gentner, D. & Law, K. MAC/FAC: A model of similarity-based retrieval. Cognitive Science 19 (1995).
11. Mikolov, T. et al. Efficient Estimation of Word Representations in Vector Space. arXiv:1301.3781 (2013); Linzen, T. Issues in evaluating semantic spaces using word analogies. RepEval (2016). arXiv:1606.07736.
12. Aamodt, A. & Plaza, E. Case-Based Reasoning: Foundational Issues, Methodological Variations, and System Approaches. AI Communications 7 (1994).
13. Webb, T., Holyoak, K. J. & Lu, H. Emergent analogical reasoning in large language models. Nature Human Behaviour (2023).
14. Kang, H. B. et al. Augmenting Scientific Creativity with an Analogical Search Engine. ACM TOCHI (2022). arXiv:2205.15476.
15. Procedural memory retrieval benchmark for agents. arXiv:2511.21730 (2025, preprint).
16. Bordes, A. et al. Translating Embeddings for Modeling Multi-relational Data. NIPS (2013) *(abstract level)*.
17. Gu, X. & Krenn, M. Forecasting high-impact research topics via machine learning on evolving knowledge graphs. arXiv:2402.08640 *(dataset; G1)*.
18. Si, C., Yang, D. & Hashimoto, T. Can LLMs Generate Novel Research Ideas? arXiv:2409.04109; Si, Hashimoto & Yang, The Ideation–Execution Gap, arXiv:2506.20803 *(dataset; G2)*.

19. Wang, Su. Blended, precise semantic program embeddings (LiGer, 2019). https://arxiv.org/abs/1907.02136 ; Wang. Dynamic neural program embeddings (DYPRO). https://www.cs.columbia.edu/~suman/docs/similarity.pdf
20. Pei et al. TREX: learning execution semantics from micro-traces. https://www.cs.columbia.edu/~suman/docs/trex_final.pdf
21. Jain et al. Contrastive code representation learning (ContraCode). https://arxiv.org/abs/2007.04973
22. Kleyko et al. A survey on hyperdimensional computing / vector symbolic architectures. https://arxiv.org/abs/2111.06077
23. When Names Disappear: Revealing What LLMs Actually Understand About Code (arXiv 2510.03178, 2025). https://arxiv.org/abs/2510.03178
24. Wei et al. Symbol tuning improves in-context learning in language models (EMNLP 2023). https://arxiv.org/abs/2305.08298
