# PREREG R2-small Part C — explicit step index for depth generalisation (fixed 20.11.2026 ~22:45 UTC, before any Part C run)

**How it came about (stated, not hidden):** written AFTER the interim look at seed 0 of Part B (`PREREG_R2_small.md`): both arms
reach faithful derivations in-distribution (mem 85/70/63 %, ctx 34/13/1.5 % at depth 1/2/3) but 0 % at depth 4–5; at depth 4–5
the model writes only 2–3 use lines and already the FIRST step ignores the goal (wrong rule, wrong entity). Part C is therefore an
exploratory follow-up motivated by one seed; Part B's hypotheses and decision stay as pre-registered and are evaluated at 10 seeds.

**Idea.** The next goal literal is addressed by position; with longer goals the addressing breaks. An index hint makes each step a
copy: before every rule application the model writes `step k: <goal literal k with the bound entity substituted>`, e.g.
`step 2: r10(e4, X2)`, then `use r10: … ⇒ r10(e4, e2)`. In the RASP-L view (Zhou et al., ICLR 2024, arXiv 2310.16028) every next
token becomes a short program (copy literal k, copy the last bound entity); scratchpad format matters (arXiv 2305.19466).

**Data.** Identical worlds, goals and answers as Part B (same generator, same seeds; only the target format differs):
`gen_traces_synth.py synth_idx --train 30000 --test 600 --index-hints`, arms ctxI / memI; sha256 prefixes ctxI_train d1d62ae2…,
ctxI_testI f4927e33…, ctxI_testD 6f4673ca…, memI_train a647928b…, memI_testI c9af4c95…, memI_testD f37ccf70….
Tokenizer adds `\d+` (step numbers; the Part B tokenizer would drop bare digits). Trainer `r2train_c.py` = Part B's trainer with
arms ctxI/memI and one vocabulary per part. Model, optimiser, steps, seeds 0–9: unchanged.

**Measures.** As Part B (faithful accuracy, answer accuracy, per depth, testI and testD); the checker ignores `step` lines and checks
every use line, the chaining and the answer exactly as in Part B.

**Hypotheses (unit = seed, 10 per arm):**
- **H-C1 (primary):** testD faithful accuracy memI > mem (Part B), one-sided Mann-Whitney U, α 0.05.
- **H-C2:** testD faithful accuracy ctxI > ctx (Part B), same test.
- Descriptive: per-depth curves; testI cost of the hint (memI vs mem, ctxI vs ctx on depth 1–3).
**Decision for kit R2:** if H-C1 or H-C2 holds, way-B targets in kit R2 carry the step index; otherwise the depth limit is
architectural for this scale and the agent keeps the solver as the applier for chains longer than trained.
**Named limits:** exploratory (motivated by one interim seed); Part B and Part C runs are sequential on the same GPU type.

## Deviation 1 (21.11.2026 ~03:02 UTC, before any Part C result was read) — operations only
Four parallel runs did not fit the 8 GB GPU with the longer index-hint targets: memI s0, ctxI s2 and memI s1 died with CUDA out of
memory between 02:04 and 02:07 UTC. The queue was replaced by one with at most 3 parallel runs (`run_r2small_c2.sh`, allocator
`expandable_segments`); the failed runs resume from their last checkpoint (memI s0, s1) or restart (ctxI s2). Data, model, steps,
seeds, hypotheses and tests are unchanged; Part D's queue was set to 3 parallel runs as well before it started.
