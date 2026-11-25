# PREREG R2-small Part D — can the tiny model learn to APPLY a rule from the prompt? (fixed 21.11.2026 ~02:20 UTC, before any Part C result and before any Part D run)

**How it came about (stated, not hidden):** written after the confirmatory Part B result (`PREREG_R2_small.md`; 10 seeds): with
the rules in the prompt under fresh names (arm ctx) the tiny GPT reaches only 16.6 % faithful derivations in distribution (depth
1–3) against 82.6 % when it recalls a fixed library (arm mem); depth 4–5 is 0 % in both. Two published mechanisms predict this and
name a fix each; Part D tests both on the identical items.

**Background.**
- Hu et al., arXiv 2402.17709 ("Case-Based or Rule-Based"): transformers fine-tuned on arithmetic reason case-based even with a
  scratchpad; Rule-Following Fine-Tuning — rules in the input, the model recites the rule and then follows it step by step — took
  models from 1–5-digit to 12-digit addition with over 95 %, over 40 points above scratchpad.
- Lazić, Fowl, György, Szepesvári, arXiv 2604.21632 ("To See the Unseen"): during training the unembeddings of rarely seen /
  role-equivalent tokens collapse to nearly one vector, so several such symbols become indistinguishable; freezing or resetting
  (un)embeddings, data diversity and a copy-friendly change restore generalisation. In arm ctx the 89 rule names s10–s98 are
  role-equivalent by construction (a fresh assignment per item).

**Arms (10 seeds each, seeds 0–9; model, optimiser, steps, tokenizer and evaluation exactly as Part B; comparison arm = Part B's
ctx runs, not re-run):**
- **ctxR (recite):** the same items as Part B's ctx (worlds, goals, prompts and answers byte-identical — checked: 30,000 / 600 / 600
  of 30,000 / 600 / 600), but before each `use` line the target writes the clause of the prompt's rule it applies:
  `rule: s46(X, Y) <= p2(X, Z) & p6(Z, Y)` then `use s46: p2(e4,e6), p6(e6,e1) ⇒ s46(e4, e1)`. Data: `gen_traces_synth.py synth_rec
  --train 30000 --test 600 --recite`. The checker ignores `rule:` lines (it checks every use line, the chaining and the answer, as
  in Part B).
- **ctxF (frozen names):** Part B's ctx data and vocabulary unchanged; the embedding and unembedding rows of the 89 fresh-name
  tokens s10–s98 are restored to their initial random values after every optimiser step (verified: those 89 rows unchanged in
  both matrices after training, all other rows moved). Trainer `r2train_d.py` (= `r2train_c.py` + arms ctxR/ctxF).

**Hypotheses (unit = seed; one-sided exact Mann-Whitney U against Part B's 10 ctx seeds; α 0.05 each, no correction — two
separate mechanisms, each with its own decision):**
- **H-D1:** testI faithful accuracy ctxR > ctx.
- **H-D2:** testI faithful accuracy ctxF > ctx.
- Descriptive: per-depth curves, testD faithful and answer-only, testD first-three-steps validity (as Part B note 1), ctxR's rate of
  recited clauses that match the prompt's rule text exactly.
The primary measure is testI (depth 1–3, in distribution) because Part B's ctx already failed there; depth 4–5 is reported, not tested.

**Decision.** If H-D1 holds: every kit target that applies a rule given in the prompt (2Wiki inference rows, synthetic ctx rows)
recites the clause before the `use` line — in the next kit if kit R2 has already started. If H-D2 holds: name-collapse is the
mechanism; for Qwen this is informative rather than actionable (LoRA leaves the token embeddings frozen anyway), and the fresh-symbol
arms of the kits draw names from a larger, more diverse pool. If neither holds: rule application stays with the solver.
**Named limits:** exploratory follow-up of one confirmatory result; one tiny model size; synthetic fresh-symbol worlds; runs after
Part C on the same GPU type.
