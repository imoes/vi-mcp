# PREREG R2-small Part G — vectorised symbols: can the tiny model use rule names it has never seen? (frozen 21.11.2026 ~14:10 UTC by PREREG_R2_small_G.sha256, before any Part G run beyond a 300-step smoke test)

**How it came about (stated, not hidden):** the user's plan was to solve renaming with symbols and to vectorise the symbols
(user, 21.11.2026: "das wollten wir doch mit den symbolen lösen … und wir wollten auch vektorisieren der symbole"). Evidence that names
act as retrieval keys: H13 (fixed names recalled in 84–96 % of name traps), run 34 and 33c (renamed P7 predicates 5/8 in three runs),
kit R2 run 1 (kinship rules with sorted fresh symbols 257/368, with random fresh symbols 17/368). Literature (research log 21.11.2026):
an embedding = shared learned part + random part resampled every forward pass keeps renamed LTL at 95.9 % where the plain model falls
to 34.1 % and extends to more symbols than trained (Isik et al., ICML 2025, arXiv 2410.17161); unseen-token (un)embeddings collapse
under weight decay + layer norm, freezing helps (Lazić et al., arXiv 2604.21632). Part D's arm ctxF (frozen random name embeddings) is
the first, weaker form of this idea; its result, read before this freeze: testI faithful 13.3 % vs ctx 16.6 % (per seed 0.003–0.18;
H-D2 one-sided MWU U 39.5, p 0.79 — failed), depth 4–5 0 % as everywhere. Frozen random rows alone do not help in distribution; dual
differs by drawing a NEW random vector per sequence (no name can be memorised) and by using it for the output logits too, and is
tested mainly on names never seen (testU), where learned rows have nothing to offer.

**Data:** Part B synth_v1 (rules in the prompt, rule names s10–s98 drawn per item) unchanged for training, testI (depth 1–3) and
testD (depth 4–5); new **testU** = the 600 testI items with every rule name of an item mapped, consistently within the item and at
random across items, to a name from s100–s199 — names that never occur in training (`gen_unseen_g.py`, seed 7, sha256 in
`expected_g.sha256`; gold targets 600/600 faithful under `gen_traces_synth.check`).

**Arms** (the only difference is how a rule name s<N> is represented; model, data, schedule otherwise as Part B):
- **ctx** — learned embedding and unembedding row per name (Part B). Unseen names keep their random initial rows.
- **ctxF** — those rows frozen at their random initialisation (Part D).
- **dual** — every name s<N> is an interchangeable symbol: input embedding = learned class vector + g_in · r, output logit =
  g_out · ⟨h, r⟩ + ⟨h, class_out⟩, where r is a random unit vector drawn per sequence and per name (consistent within the sequence,
  new for every training sequence; fixed by seed at evaluation). The name's own rows are not used. New names need no new parameters.

**Model and training:** H13 `gpt.py` (d 128, 4 layers, 4 heads, RoPE), AdamW 2e-3, cosine, batch 32, 20,000 steps, seeds 0–9 per arm,
greedy; trainer `r2train_g.py` = `r2train_d.py` with the three arms and the third test set; scoring by the frozen Part B analyzer
`analyze_r2b.py` (faithful = every use line a ground instance of the named rule over given facts, chained in goal order, answer =
last object).

**Hypotheses (unit = seed, one-sided exact Mann-Whitney U over 10 + 10 seeds, α 0.05):**
- **H-G1 (primary):** testU faithful dual > ctx.
- **H-G2:** testI faithful dual not worse than ctx: 95 % bootstrap CI of mean(dual) − mean(ctx) has lower bound > −0.05.
- Descriptive: ctxF on all three sets; testD (depth 4–5; expected 0 for every arm, as in Parts B–D); dual vs ctxF on testU.

**Decision:** If H-G1 and H-G2 hold, symbols are represented as vectors in the next kits: R3 adds opaque rule-name tokens to Qwen whose
input rows are a class vector plus a per-sequence random vector (an embedding hook), and evaluates with unseen names. If only H-G1
holds, the representation helps unseen names at a cost in distribution — R3 uses it only for fresh-symbol rows. If H-G1 fails, names
are normalised outside the model (canonical renaming in the pipeline) and the model is not changed.
**Named limits:** one tiny width (d 128; In-Context Algebra, arXiv 2512.16902, needed width ≥ 512 for context-only meaning — a
wider arm would be a separate registration); synthetic worlds; only rule names are symbols here (entities e1–e8 and base predicates
p1–p6, q1–q2 stay learned tokens).

**Smoke test (before the freeze, not evidence):** 300 steps on the pod's CPU, arms dual and ctx, 20 items per set — all three sets
evaluated, the dual model writes rule names, the analyzer reads the outputs.
**Compute:** the RTX 3070 of the CPU/GPU host used for the kit runs (same GPU type as the RunPod 3070 of Parts B–F; all three arms of
this part run there, so the comparison is within one host), 3 parallel runs, after the queued kit R2 jobs; launcher `run_r2g.sh` checks
the data and code hashes (`expected_g_run.sha256`) before starting.
**Hashes (sha256):** gen_unseen_g.py e4fe262b9326e584… · r2train_g.py 43fd3c103a50cb77… · analyze_g.py f49e0ac527a6bd3c… ·
analyze_r2b.py f66ac148a07fac0a… · score_r2b.py 92edf37fff81a94a… · gen_traces_synth.py 3e93170f14c548ae… · gpt.py 76e53aaaf238bed0… ·
synth_g/ctx_testU.jsonl 8a518b959647d83c…; synth_v1 files as in Part B's expected.sha256.
**Analysis:** `analyze_g.py synth_g results_g/*.json` (H-G1 one-sided exact MWU on testU, H-G2 bootstrap CI on testI, descriptives).
