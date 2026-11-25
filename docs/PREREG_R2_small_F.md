# PREREG R2-small Part F — iterative one-step derivation: does the tiny model reach depths it never trained if it derives one step per call? (fixed 21.11.2026 ~11:30 UTC, before any Part F run beyond a 300-step smoke test)

**How it came about (stated, not hidden):** R2-small Parts B and C: with rules in the prompt the tiny model derives depth 1–3 chains in
distribution (ctx testI faithful 16.6 %) but never a depth 4–5 chain (testD faithful 0 % in every arm and seed). Literature read on
21.11.2026: ProofWriter (Tafjord et al., arXiv 2012.13048) — trained on depth 3, tested on depth 5, the all-at-once prover reached
27.4 % (CWA) proof accuracy, the iterative one-step prover 87.8 %; looped / recurrent-depth transformers (Fan et al., ICLR 2025;
arXiv 2604.07822; 2610.27628) extrapolate in depth when the number of iterations grows with the instance, while 2609.33144 warns that
correct extrapolated answers need not come with faithful intermediate steps. Plan R3 (PLAN_R3.md) wants short way-B calls; this part
tests the idea on the from-scratch model first (rule "small model first").

**Data:** the Part B ctx items (synth_v1, `expected.sha256`), turned into one-step items by `gen_steps_f.py` (hashes in
`expected_f.sha256`, regenerated and checked on the GPU host). Training uses only depth 1–3 train items; the test items are the
unchanged Part B ctx testI (depth 1–3, new worlds) and testD (depth 4–5, compositions never trained).
- **stepH** (harness bookkeeping): each call sees facts, rules and ONE goal literal with its bound subject
  (`Goal: answer(Y) <= s98(e5, Y)`), target = one use line; the harness binds the next literal's subject to the derived object
  (60,000 train rows).
- **stepM** (model bookkeeping, ProofWriter's iterative form): each call sees facts, rules, the WHOLE goal and `Derived:` (the heads
  derived so far), target = the next use line, or `answer: X` when every goal literal is derived (90,000 train rows).

**Model and training:** exactly Part B/D — H13 `gpt.py` (d 128, 4 layers, 4 heads, RoPE), AdamW 2e-3, cosine, batch 32, 20,000 steps,
seeds 0–9, greedy; trainer `r2train_f.py` = `r2train_d.py` with the arms stepH/stepM and an iterative evaluation (stepH: one call per
goal literal; stepM: until `answer:` or depth + 3 calls). The evaluation writes the joined trace (use lines + answer line) as `gen`,
scored by the frozen Part B analyzer `analyze_r2b.py` (sha f66ac148…; `gen_traces_synth.check`: every use line a ground instance of
the named rule over given facts, chained in goal order, answer = last object).

**Hypotheses (unit = seed, one-sided exact Mann-Whitney U over 10 + 10 seeds, α 0.05; the comparison arm is Part B ctx, same data,
model, schedule, seeds and GPU type, its stored results):**
- **H-F1 (primary):** testD faithful stepM > ctx.
- **H-F2:** testD faithful stepH > ctx.
- Descriptive: testI faithful and answer accuracy; testD by depth (4, 5); calls per item; answer-only accuracy vs faithful (the
  2609.33144 warning); stepH vs stepM.

**Decision:** If H-F1 holds, R3's way B is trained and run as one step per call with the model keeping the chain; if only H-F2 holds,
the chain bookkeeping stays with the harness/solver and the model is trained on single steps; if neither, depth stays with the solver
and way B is not extended.
**Named limits:** one tiny model size; synthetic chains of depth ≤ 5 over 8 entities; the Part B ctx comparison was trained in an
earlier batch (same code path and settings); stepH partly measures the harness (its depth-4/5 calls have the depth-1 format by
design) — that is the point of the arm, not a hidden advantage.

**Smoke test (before the freeze, not evidence):** 300 steps on the pod's CPU, 20 test items per set, seed 0 — the loop runs (stepH: one
call per literal, 4 calls for a depth-4 item; stepM stops at `answer:`), the frozen analyzer reads the joined traces; accuracy 0 as
expected after 300 steps.
**Hashes (sha256):** gen_steps_f.py 2bd022b24bb8b5fc… · r2train_f.py 7cda238ed2c02c97… · expected_f.sha256 6cc6833cc4003689… ·
analyze_r2b.py f66ac148a07fac0a… · score_r2b.py 92edf37fff81a94a… · gen_traces_synth.py 3e93170f14c548ae… · gpt.py 76e53aaaf238bed0… ·
run_r2small_f.sh dc0a9e5702c2bf5f06c72a6bd3bb35e6ba6961c1223736b3368077db8bc76036 (exchange repo r2small/, regenerated data checked against expected_f.sha256 before training).
