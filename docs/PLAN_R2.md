# Plan R2: the rules go into the model — two ways, one kit family (20.11.2026, plan, not built)

User decision (20.11.2026): "Die Regeln sollen ins Modell, plane beide Wege." Until now the model only translates (text → facts,
question → goal); rules are found by symbolic regression / ILP (gp2, Popper) and applied by clingo outside the model.

## Research behind the plan
- **LLM proposes, verifier decides (Way A).** ALBI (arXiv 2611.05039): an LLM writes Prolog hypotheses from background knowledge,
  examples and mode declarations; the verifier classifies failures as TOO_GENERAL (covers negatives) / TOO_SPECIFIC (misses
  positives) / SYNTAX_ERROR and returns counterexamples; 100 % on 30 Popper benchmark tasks in 1.4–1.7 iterations — but with frontier
  API models, 3–20× Popper's wall clock, and "no completeness guarantee"; no small or fine-tuned model tried. Hypothesis Search
  (Wang, Zelikman et al., ICLR 2024) and Qiu et al. (ICLR 2024, arXiv 2310.08559): LMs are good rule PROPOSERS but poor rule
  APPLIERS — iterative propose/verify/refine beats plain prompting.
- **Train on verified self-proposals.** STaR / ReST-EM / Lean-STaR (arXiv 2407.10040): sample, keep what the checker accepts,
  fine-tune, repeat; V-STaR (arXiv 2402.06457) also uses the rejected samples (verifier via DPO).
- **Train on solver derivations (Way B).** LoGiPT (arXiv 2311.06158): the pyke solver was changed to emit its reasoning actions
  (rule used/reused, bind, unbind, new fact, finish); 13B open models fine-tuned on these traces (ProofWriter 41,433 cases) beat
  Logic-LM with GPT-4 (89.5 vs 79.7 %) and avoid the NL→logic parsing errors (Vicuna-13B parsed only 17 %). ProofWriter (Tafjord
  et al. 2021): iterative one-step proofs are always verifiable, all-at-once proofs often are not. Small models collapse with proof
  depth (arXiv 2504.20213: a 1B model fell to 0.02 at depth 13).
- **Our own evidence.** H13: names become retrieval keys (recall instead of translation) — every task must have a fresh-symbol arm.
  A2 and Q1: Popper is the better teacher (28/32 vs 11/32; all 2Wiki kin rules in ~2 s); a rule must be judged by recall AND false
  hits on neighbouring relations. G8d-0b: an oracle proposer makes gp2's search 2.76× cheaper — the ceiling a learned proposer aims at.

## Way A — rules as the target (the model writes the rule)
Input: the predicates with arity (mode declarations), the background facts of a few small worlds (entities renamed), positive and
negative examples of the target. Output: a rule set in clingo-object (the notation the philosophy kits already train).
- **Data.** (1) synthetic rule tasks from a generator: a random target program (chain, two-clause disjunction, unary filter,
  default negation, recursion) over random predicates → worlds → examples; the generating program and Popper's minimal program as
  teachers; (2) the 2Wiki kinship tasks (train worlds only); (3) the G8/G8b task families; (4) Popper's example tasks — train
  subset only. Every task in two arms: meaningful names (father, director) and fresh symbols (p17, r3).
- **Repair turn** as in ALBI: the verifier's verdict (too general / too specific, 2 counterexamples) → the model revises.
- **Training.** SFT on teacher rules → expert iteration (k = 8 samples per task, clingo keeps exact ones, shorter-than-teacher ones
  preferred, retrain) → GRPO with the verifier as reward: exact = 1, minus false hits, minus size (the seed-as-reward machinery of
  the philosophy kits).
- **Measures.** Held-out task FAMILIES (shapes never trained: e.g. three-hop chains, a disjunction over a new predicate pair),
  held-out symbols; solved within k samples × repair rounds; verifier calls; against Popper (time) and gp2 (evaluations); and as
  gp2's proposer (G8d-1: the model replaces the uniform edit choice — cost ratio U/model vs the oracle's 2.76).

## Way B — derivations as the target (the model applies rules)
Input: question + facts + the rules from the library (given in the prompt, not memorised). Output: the goal, then one-step
derivations in LoGiPT/ProofWriter style, then the answer:
`use paternal_grandmother: father(e1,e2), mother(e2,e5) ⇒ target(e1,e5)` … `answer: e5`.
- **Data.** 2Wiki TRAIN questions (all four types) through q1_oracle with gold evidence; the trace comes from the clingo program
  itself: every rule gets a reified twin `step(rule_id, Head, Body…)`, so each step is a ground rule instance the solver derived.
  Synthetic worlds from Way A's generator add depth (2–5 hops).
- **Arms.** rules in context vs rules only seen in training (does it apply given rules or recall memorised ones?); fresh symbols.
- **Training.** SFT on solver traces → GRPO with a step checker: every step must be a ground instance of a given rule over given or
  earlier derived facts, the answer must follow from the steps (faithfulness by construction, not by claim).
- **Measures.** Accuracy without the solver vs the full pipeline (solver applies); faithful trace rate; depth generalisation (train
  ≤ 3 hops, test 4–5); tokens per question and tokens/s against qwen35b (user rule).

## How the two ways meet
The research agent: question → goal → rule in the library? → if not, Way A proposes one from examples, the solver checks it
(recall and false hits) and stores it → Way B applies it with a checkable derivation, or the solver applies it when the trace fails.
Rules then live in two places: as checked programs in the library (source of truth, never overwritten by the model) and as the
model's competence to write and apply them.

## Order (rules "Kleinmodell zuerst" and "Training konsolidieren" apply)
1. CPU, workstation: task generator, Popper teacher runs, trace exporter (reified rules), checkers for A and B. No GPU.
2. Small model first: the from-scratch tiny GPT (h13 gpt.py, ~5–10 M parameters) on the synthetic tasks, 10 seeds, both ways —
   it answers the cheap questions (does fresh-symbol rule writing generalise to held-out shapes at all; does rule-in-context beat
   memorised) before any Qwen run.
3. One consolidated kit R2 for Qwen3-0.6B: Way A and Way B tasks in one data mix (plus the R1 read/write rows so reading is not
   forgotten), arms as columns of the kit, not separate runs; SFT → expert iteration → GRPO.
4. Evaluation as above; then the agent loop on 2Wiki dev with R1-full reading.

## Pre-registration before step 2 (fixed then, not now)
Primary contrasts, seeds, held-out families and gates are written down before the first small-model run, as for G8d.
