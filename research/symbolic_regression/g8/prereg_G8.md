# Pre-registration G8 — does a library of formal mechanisms help an evolutionary search solve problems of other domains?

Written 2026-11-19 after pilots on seed 99 only (search parameters tuned there, arm-neutral), before any run of seeds 0–9.
Frozen by sha256 (prereg_G8.sha256: this file, g8_tasks.py, g8_eval.py, g8_search.py, nearest.json) and a VI record.

## Question
Exaptation = a mechanism built for one purpose solves another. Text similarity did not find transferable mechanisms (G5–G7). G8 asks
whether STRUCTURE does: library rule blocks (kollektiv P1–P13, messung M1–M6, code P1–P7 — built for an AI collective's evidence
rules, measured-only acceptance and code architecture) mapped onto the vocabulary of six problems from other domains (software
review, package cycles, monitoring, laboratory, data provenance, parliament), searched by an evolutionary algorithm with the solver
as fitness (genetic programming, Koza 1992; FunSearch / AlphaEvolve without an LLM; structure mapping, Falkenhainer/Forbus/Gentner 1989).

## Setup (frozen code)
- Tasks: g8_tasks.py (6 tasks, own vocabulary, hidden REFERENCE used only to compute gold answer atoms; visible constants only for
  sensor_state). Train worlds 30 (`worlds(task, 30, 1000+seed)`), held-out worlds 50 (`worlds(task, 50, 5000+seed)`).
- Search: g8_search.py — budget 10,000 evaluations per run, of which 3,000 are a start phase that samples candidates and keeps the
  best 40; then steady-state evolution (tournament 3, crossover 0.2, 1–2 mutations, replace-worst). Fitness = mean answer-atom F1 on the
  train worlds − 0.001 · size. Every individual is safety-repaired before evaluation (all arms). Solved = a program exact on all 30
  train worlds AND all 50 held-out worlds; the run stops at the first solve and records the evaluations used.
- Arms (only the start phase and S's operator set differ):
  - L: start candidates = mechanisms of any library block (a rule, p = 0.5 with the block's rules defining its body predicates),
    randomly mapped onto the task vocabulary;
  - Z: start candidates = random rules over the task vocabulary (control);
  - T: start candidates = mechanisms of the single library block nearest to the task description by bge-m3 (nearest.json, computed
    before any run: release_gate kollektiv:P13, dependency_cycle code:P6, sensor_state kollektiv:P4, trusted_reading code:P7,
    lineage_root kollektiv:P13, bipartisan kollektiv:P4);
  - S: like L, but the only operators are remap and remap_target (pure structural transfer).
- Seeds 0–9 for every task and arm: 240 runs.

## Outcomes and tests
- Unit: (task, seed) pairs, 60 per arm comparison.
- H1 (primary): L solves more pairs than Z — exact two-sided binomial (sign) test over the pairs where exactly one arm solved.
- H2: L needs fewer evaluations than Z — sign test over pairs, an unsolved run counts as BUDGET + 1 (ties dropped).
- H3: L solves more pairs than T (structure beyond the text-nearest block) — as H1.
- Holm over H1–H3, α = 0.05. Refutation of the idea: L ≤ Z in solved pairs, or H1 not significant after Holm.
- Secondary (descriptive, no test claim): S vs Z and S vs L solved pairs; per task solved counts; the origin block of every L
  solution (all are co-opted by construction — no library block was built for these tasks); a manual reading of a sample of
  solutions for whether the origin's mechanism is still visible in the program.
- Expected from the pilot (seed 99, not part of the test): bipartisan solved by L via kollektiv:P10 at 1,839 evaluations, not by Z;
  release_gate solved by both (~6,500); lineage_root by neither.

## Limits named in advance
- Six tasks written by the experimenter, who also knows the library: a task may resemble a library mechanism because the author saw
  it. Mitigation: the tasks are standard problems of their domains; the reference programs use their own helper names.
- One search algorithm, one budget; a negative result refutes this search, not every form of structural transfer.
- No LLM in the loop; a FunSearch-style proposer (and an MTP-trained proposer on the lineages) is the next step only if H1 holds.
