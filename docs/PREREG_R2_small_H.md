# PREREG R2-small Part H — counterfactual library names: does training with misleading names make the tiny model follow the rule in the prompt instead of the name? (frozen 21.11.2026 by PREREG_R2_small_H.sha256, before any Part H run beyond a 300-step smoke test)

**How it came about.** Names act as retrieval keys: in Part B arm mem (library rules recalled by name) is 82.6 % faithful in
distribution, arm ctx (rules written in the prompt under fresh names) only 16.6 % — the model recalls, it does not read. H13 (fixed
names recalled in 84–96 % of name traps) and kit R2 run 1 (kinship 257/368 with sorted fresh symbols, 17/368 with random) show the same
for larger models. CREAM (arXiv 2207.11104) trains with counterfactual identifiers so that a model must read the definition. Part G
attacks the same problem by representation (names as per-sequence random vectors); Part H attacks it by data.

**Data** (`gen_cf_h.py`): Part B synth_v1 unchanged plus cf items — a Part B ctx item whose rule names are replaced by LIBRARY names
r1–r12 such that no rule the chain uses carries its own library name (a derangement; distractor rules get the remaining names). The
prompt's rule decides; a memoriser is misled. Every cf item's gold target is asserted faithful to the prompt's rules
(`gen_traces_synth.check`). cf_train 15,000 (depth 1–3), cf_testI 600 (depth 1–3), cfmix_train = 15,000 Part B mem train items +
the 15,000 cf train items, shuffled (random.Random("cfmix")).

**Arms:** **mem** — Part B mem training (mem_train, no rules in the prompt); **memCF** — cfmix_train (half recall, half
counterfactual reading). Model, schedule, decoding as Part B (H13 `gpt.py`, d 128, 4 layers, 4 heads, AdamW 2e-3, cosine, batch 32,
20,000 steps, greedy), seeds 0–9 per arm; trainer `r2train_h.py`.

**Tests:** testI = Part B mem_testI (recall, depth 1–3), testD = mem_testD (depth 4–5), testCF = cf_testI.
**Scoring:** `analyze_h.py` (scoring of `analyze_r2b.py`): faithful = every use line a ground instance of the named rule — on testCF the
rule written in the prompt — chained in goal order, answer = last object. **Memory-following** on testCF = faithful to the LIBRARY
rule of each name and not to the prompt's rule. Checked before the freeze: the 600 cf gold targets are memory-following in 0/60
sampled; 40 constructed library-following outputs are detected 40/40 (1 of them coincides with the prompt's chain → counted as both).

**Hypotheses (unit = seed, final step, α 0.05):**
- **H-H1 (primary):** testCF faithful memCF > mem — one-sided exact Mann-Whitney U over 10 + 10 seeds.
- **H-H2:** testI faithful memCF not worse than mem — 95 % bootstrap CI of mean(memCF) − mean(mem) (10,000 resamples, random.Random(0))
  has lower bound > −0.05.
- Descriptive: memory-following on testCF per arm (expected high for mem); testD (expected 0 as in Parts B–G); by depth.

**Decision:** H-H1 and H-H2 hold → counterfactual names are added to kit R3's data (Qwen: rules under library names bound to other
rules in the prompt) so the model reads instead of recalling, without losing recall. H-H1 holds, H-H2 fails → reading is bought with
recall: R3 keeps them as separate tasks with an explicit marker (rule given / rule recalled). H-H1 fails → at this size the data
remedy does not teach reading (Part B ctx already stalls at 16.6 %); renaming stays outside the model (canonical names in the
pipeline) and Part G's representation result decides alone.

**Named limits:** tiny width (d 128); memCF sees each kind of item half as often as the single-task arms; cf names come from a
library of 12, so a model could learn "a library name in a prompt means read" — testCF cannot separate that from reading in general
(Part G's testU with unseen names can).

**Smoke test (before the freeze, not evidence; done 21.11.2026 ~16:55 UTC):** 300 steps on the CPU of the 3070 host, both arms, seed 0,
20 items per set — all three sets evaluated, the model writes rule names in the trace format, the analyzer reads them (every value 0
after 300 steps, as expected).
**Compute:** the RunPod RTX 3070 pod of Parts B–F after Part F, 2–3 parallel runs (same GPU type as Parts B–G); cost stated to the
user before; fallback the 3070 host after its queue.
**Hashes (sha256):** gen_cf_h.py 33f3b2c4feb73102… · r2train_h.py f423b7f2331e762c… · analyze_h.py a2876e93ab73f414… · analyze_r2b.py f66ac148a07fac0a… · score_r2b.py 92edf37fff81a94a… · gen_traces_synth.py 3e93170f14c548ae… · gpt.py 76e53aaaf238bed0… · synth_h/cfmix_train.jsonl 341f4f52e7ac4183… · synth_h/cf_testI.jsonl 87c4700e871cc382… · synth_h/cf_train.jsonl cd07d0542f494f8e… · synth_h/ctx_testD.jsonl 239065fc5ce15acd… · synth_h/ctx_testI.jsonl 5c7f99b3eb196d8b… · synth_h/ctx_train.jsonl 06827120ec23436c… · synth_h/mem_testD.jsonl 8c3c30345b4217ef… · synth_h/mem_testI.jsonl 4ffd3dc94e2044ba… · synth_h/mem_train.jsonl dff2ae0b9589c064… · synth_h/library.json 2d397770e27eba4d….
