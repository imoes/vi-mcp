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

## Timeline (19.11.2026)

| step | question | result | evidence |
|---|---|---|---|
| G8 | does a library of mechanisms speed up an evolutionary rule search? | **invalid by construction** — an independent review found the tasks were renamed library blocks, the random arm crippled, hits were lookups, "solved" unsound; stopped at 119/240 runs | paper §5.8; `g8/` |
| G8b-0 | can the search find known mechanisms from data alone, without a library? | **42 of 60 runs**, 5 of 6 mechanisms (an invented recursive closure among them; one law shorter than the reference); lineage_root never | paper §5.9; `g8b/result_G8b0.json`, `note_G8b0.md` |
| Popper baseline | how does an established ILP system do on the same tasks? | Popper v5.0.1 native 20/60, with assists 40/60; dependency_cycle 0/10 (GP 10/10) — Popper's optimal size-10 program was not general | VI insight (Popper baseline, 19.11.2026) |
| G8b-1 | exaptation, fairly: 33 tasks written blind to the library; library vs rewired vs relinked vs random | **library helps by reuse as it is** (lookup 25.7 % vs 10.4 %, Holm p = 0.0003); **not as a seed for modification** (H1 ratio 1.10, CI [0.93, 1.24] excludes 1.5); random rules not worse in total cost | paper §5.10; `g8b/prereg_G8b1*.md`, `result_G8b1*.json`, `robust1.json`, `runs1.tar.gz` |
| G9 | do rules found over the VI's own experiences predict future failures? | **no** (instance claude-code, 3 seeds): every seed fails the test-period gate; a 2-leaf tree beats it (F1 0.066 vs ≤ 0.032). Cause: selection on one validation day picked a predictor that drifted (0 of 75 on the test period); 69 training failures only | `g9/` (code only — the data are private experiences and stay local) |
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
- G8b-1: the provenance analysis promised in the protocol is not implemented yet.
- A2: results pending.
- G9 over all instances: running; G9b with MDL and window validation: next.
- G8c (proposer) and B3 (rules → weights): to be pre-registered.
