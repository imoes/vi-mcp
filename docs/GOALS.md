> Nutzer-Überblick mit Erklärungen (Deutsch): [UEBERBLICK.de.md](UEBERBLICK.de.md)

# Goal catalogue (adopted by the user 22.11.2026 ~10:33 UTC — VI insight:2848f6aa, key goals:catalogue)

Leading goal: a small model plus symbolics that answers reliably — the model translates, clingo derives, rules come from symbolic
search. Outcome: (a) a better VI, (b) a BabyLM paper. Every experiment serves one goal below; otherwise it is not started.

| # | goal | measure | baseline (source) | target | test set | owner |
|---|---|---|---|---|---|---|
| Z1 | reading: text → clingo facts | official alias EM, 2Wiki Q1 | primary-first merge 75.5 % on fresh4 (PREREG_R3m, 47a6c14, 22.11) | ≥ 80 % (gold-fact ceiling 94 %) | a new unseen set each time | session-60 (continues, user 25.11) |
| Z2 | finding rules (symbolic regression) | tasks solved, clingo calls / evaluations | g8f portfolio P2 18/7/15 vs gp2, Holm p 0.0094, depends on the prereg CENSOR wording (3977b57, fb414bb); binder-G ended; VBS 21/40 | ≥ 35/40 blind tasks, fewer evaluations than gp2 (not reachable with gp2+binder) | new blind sets (g8g reserved for L1) | session-57 (T1 teacher, L1 proposer) |
| Z3 | rules into the model (user decision 20.11.) | recall of library rules AND reading a given rule in one model | Z3-3 qb60 testI 0.916 / testCFN 0.726 (a564398); Z3-G a constrained decoding 0.7273 vs 0.7270, p 0.125 (93fd66c) | both ≥ 85 % | unseen rules and names | PAUSED 25.11 (user): rule reading goes to clingo, tested in Z12 arm G; session-57 |
| Z4 | philosophy seed in the model | catalogue of 15.11. + P6/P7 8/8 | run 35 (kit35): H-K1 holds, no harm; pressure facts 29 → 23 watch item | all targets in one run | held-out worlds, synonym test set | session-7a (research + next kit, user 25.11) |
| Z5 | the VI answers fact questions better than AIKB | blind judge score | CLOSED 24.11: no content gain, findability shown, fact block not adopted (vi-facts 1add168, SUMMARY_Z5) | VI better on fact questions, no extra false refusal | — | closed |
| Z6 | VI two-hop retrieval | recall@4 on questions joining two objects | MET 22.11: both@4 81.1 % vs 6.4 % (PREREG_Z6 2e846bb) | +10 points vs today's hybrid | new two-hop set | coordinating session (application into vi_recall, pending user go) |
| Z7 | VI hints (prediction-error learning) | hint-label AUC on a temporal holdout, single-labeller label with both classes, AND stratified hold-back lift (revised with the user 22.11.2026 11:13 UTC: outcome AUC measures situation difficulty, not hint value) | outcome AUC 0.55; no valid hint label yet — the 0.84 within-action result (z7-router 114fdd4) used the heuristic adoption label, which failed its pre-registered placebo check (CORRECTED 11:37 UTC); hold-back lift −0.1 ± 1.1 pts | AUC ≥ 0.65 on DECLARED labels (open: labels come from the new feedback hook) AND positive hold-back lift (online A/B, pending) | within-action used labels; randomised hold-back | session-84 (router; AUC-jump analysis pending a production copy) |
| Z8 | own RAG | EM with own retrieval vs gold paragraphs | 65.75 vs 70.75 % (RAG-1) | gap ≤ 2 points | fresh2 / RAG-1c | coordinating session |
| Z9 | words as symbols (WG) | per PREREG_WG | MET: H-WG1–3 hold; WG2 H-WG2-4 not confirmed (rendering effect, WG2-X); WG3 running | per prereg | — | session-40 |
| Z11 | virtualised LLM | knowledge-probe correct + edit test | CLOSED 24.11: RAG stays the knowledge path; provenance readable 110/117; forget local after the cache fix (SUMMARY_Z11, main 4a0edfe) | kNN-LM ≥ LoRA on the probe AND edits take effect without training | — | session-7a (integrate Z1 + Z4 findings, user 25.11) |
| Z10 | BabyLM paper | submittable, confirmed results only | DIVISION_OF_LABOUR_PAPER.md (symbolic-regression branch), sections per goal | ready for the next edition | — | coordinating session |
| Z12 | thinking in clingo (user decision 25.11) | share of fresh family-D items solved in arm C1 (clingo loop ≤ 3 calls), greedy, budget 1,536; plus the prose arm at equal training | S0 untrained Qwen3-0.6B: C1 5/100, Pcot 16/100 (3 vs 14, p 0.0127; clingo-think b278cf7) | C1 ≥ 0.80 AND C1 > prose arm (exact McNemar) AND ≥ 0.70 at depth 5–7 | new CT items generated after the S1 prereg freeze | session-af |

Rules: every goal has a main test on unseen data, pre-registered before the run; an approach that fails twice in a
pre-registration ends (like G8d); this page shows the state of every goal and is updated after each result.
Priority: Z5 and Z4 first.

## Status log
- Z3 (25.11.2026, coordinator; recount of RESULT_Z3G_a.json 93fd66c): Z3-G stage a fails — fact-constrained decoding 0.7273 vs 0.7270 on qb60 testCFN (p 0.125), qbwide unchanged; "fact not given" 757 → 0 but "not an instance" 64 → 818: the 0.6B model picks the wrong target entity before writing the step. User decision: **Z3 paused**, reading a given rule is delegated to clingo (Z12 arm G).
- Consolidation day (25.11.2026, coordinator): user decisions — results into the right existing paper (new paper only if none); Z1 continues; Z3 continues with a new approach after research; Z4 research and continue; Z6 application to be clarified; Z10 continues; "thinking in clingo" becomes Z12; Z11 integrates the Z1 and Z4 findings. Z5 and Z11 closed 24.11; Z3-3 (last registration) scored 25.11, goal missed (VI insight:3ac1021a).
- Z5 (11:33 UTC, session-af, vi-facts commit 517fdd6, docs/RESULT_Z5.md, pre-registered PREREG_Z5 3ca0af0): **H1 not shown** — VI + NetBox
  1.63 vs AIKB 1.42 on the 19 fact + mixed questions (+0.21, 95 % CI −0.21 to +0.63; better 5, worse 2, equal 12). Secondary outcomes
  hold: false refusals 1 vs 3 (19 questions), hallucinations 1 vs 4 (all 49), derived answers median 5.1 s vs 134.6 s. Only 3 of 19
  were answered by derivation (2 right, 1 wrong template); 12 of 16 fallbacks because the base 0.6B classified real wording as "no
  fact question". Bottleneck = reach (question classification, relations only in prose). The 49 questions are used up for this strand.
- Z2 (11:35 UTC, session-72, branch sr-binder 42ca0da/dbb55f1, PREREG_binder_g8d): **H-G1 fails** (binder-G < gp2 U on 40 blind-task
  medians p 0.074; fewer evaluations 22, more 12, tie 6) — Z2 not met (22/40, target 35). Solved runs 302 vs 315 of 400; median of task
  medians 19.5 vs 98.75 evaluations; wall 13 s vs 169 s. By kind: a 4/10, b 12/15, c 6/15. Gaps: 7 trivial tasks where gp2 hits in its
  start phase (caps binder-G at 33/40 on this set by construction — question to the user), 7 missing mechanisms (undirected reach,
  mutual recursion, closure over a union, larger negated sub-conjunctions, reach with a negated guard, nested negation, negation of
  another answer), 3 inside the grammar but not reached, 1 needing 3 new variables. First failed pre-registration of binder-G; a second
  and last attempt needs a new blind set by a new author.
- Z7 correction (11:37 UTC, session-73): data.used is the heuristic adoption label (a shown hint's token reappears in one of the next
  3 successful actions), not the agent's declaration (data.declared, absent in the production copy). Pre-registered placebo (commit
  0e20f71): hints held back at random and never seen are "adopted" at 5.8 % vs shown hints 4.6 % (risk ratio 0.79, CI 0.62–1.03) — the
  label measures token commonness. The earlier report "Z7 first half met offline (0.82–0.84)" is WITHDRAWN. The same heuristic feeds
  scorer.label as a positive router/bandit label. Next: declared labels via the feedback hook (vi-mcp-9a), then the online A/B prereg.
- Z11 added (11:37 UTC, user decision): virtualised LLM — knowledge outside the weights in an editable kNN-LM token store; first test kNN-LM
  vs LoRA (run 3, probe 7/9 of 60) vs RAG on the same knowledge probe, plus an edit test; owner session-c1; internal data on own hosts only.
- Z8 (12:35 UTC, coordinator, sym-rag 5b6f5a3, PREREG_RAG1c): **H-R1c holds** — reader-guided second hop HOP@4 61.5 % vs SYM-0@4 56.75 %
  (19 vs 0, p 2e-6), all-gold@4 90.75 %; **H-R2c fails** — 4.5 points below gold paragraphs (ORACLE 66.0 %, CI −7.0 to −2.25; target
  gap ≤ 2). Remaining loss: distractor facts from retrieved non-gold paragraphs (old readers R1-full + base).
- Z1 (13:10 UTC, coordinator, vi-mcp-sr 47a6c14) PREREG_R3m scored on fresh4: primary-first merge 75.5 % vs union 70.0 % (27 vs 5, p 5.7e-5) vs R3r alone 73.5 %
  (12 vs 4, p 0.038) — both hypotheses hold; Z1 target ≥ 80 % not yet reached (75.5 %).
- Z5 round 2 (15:06 UTC, session-af, vi-facts 9cb8cea, PREREG R2 23bbdb6): on 118 sealed fact questions written by separate agents from
  randomly drawn documentation chunks, the frozen solver path fires for 3 (2.5 %; pre-registered prediction 5–20 % missed); precision
  where it fires is high (dev 7/7). Strategic finding: structured relations are asked in only 2.5–10 % of documentation fact questions —
  reach is set by the fact base, more templates cannot move it; the only lever is a prose reader (GPU + user go). Judging pending (needs
  3 AIKB answers after the WG queue ends).
- Z5 round 2 result (15:29 UTC, session-af, vi-facts 34a1b39; amendments 71e1ca5 comparator = AIKB /search/opensearch top 3, no LLM —
  user decision; a630e88 pack-numbering bug in the reference judge, re-run, first run VOID): **H1 not shown** — pairwise fact block +
  retrieved chunks vs retrieved chunks: 1 win, 1 loss, 1 tie (p 0.75); reach 3 of 118 test fact questions (2.5 %). Base Qwen3-0.6B as a
  prose reader (dev probe): facts from 1 of 23 chunks, garbled. Next: a prose reader on the RTX 3070 from ~02:15 UTC (user) — model choice
  pending (fine-tuned 0.6B vs Qwen3-8B Q4 via llama.cpp).
- Z6 result (16:34 UTC, coordinator, PREREG_Z6 2e846bb): **both hypotheses hold** — on 846 unseen two-hop questions (141 VMs) the title
  anchor + one mention hop finds both gold pages in the top 4 for 81.1 % vs 6.4 % for today's vi_recall hybrid search (+74.7 points,
  95 % VM-clustered bootstrap CI 68.1 to 81.0; 637 vs 5 questions, exact one-sided McNemar p 5e-182); every relation × language form
  113–116 of 141. Z6 met (target +10 points). Next: a vi-mcp change (entity/title anchor + hop in vi_recall) — the user's decision,
  with its own online check; limits: template questions, inventory relations only.
- Z4 (17:09 UTC, coordinator, PREREG_kit35 73cc9a6): **H-K1 holds** — synonym training: run 35 42/64 vs run 34 32/64 on held-out
  synonyms (13 vs 3, p 0.011; P6 13 vs 6 of 22); **H-K2 fails** — p67ablate 12/16 vs 11/16 (P6 7/8, P7 still 5/8). No-harm on the
  15.11 catalogue pending. Z4 (all targets + P6/P7 8/8) not yet met.
- Z11 primary result (20:12 UTC, session-c1, PREREG_Z11 cb7e2f4; counts re-derived by the coordinator from the blind grades + key,
  20:13 UTC, identical): 60 knowledge-probe questions, strict correct / partial / wrong — base 0/4/56, LoRA run 3 7/8/45, kNN-LM 8/6/46,
  RAG 41/11/8, kNN+RAG 1/17/42. **H1 holds** (kNN > base 8:0, p 0.0039); **H2 holds only as a point estimate** (kNN 8 vs LoRA 7,
  discordant 5:4, p 1.0 — not shown equal; the edit test is still open); **H3 fails** (kNN+RAG vs RAG 0:40 — the frozen mixture weight
  0.8 destroys copying from the documents; hypothesis, untested). RAG beats both weight/store variants (35:1 vs LoRA). Judge agreement with
  the run-3 grades 98.3 % (kappa 0.88/0.96). Z11 not yet met: needs the edit test.
- AIKB re-run (19:38 UTC, coordinator, not a Z goal — reference point for Z5/Z8): the 49 benchmark questions against today's AIKB, judged
  blind against the AIKB answers of 10.11: mean 1.694 vs 1.735, 4 better / 6 worse / 39 ties (sign test p 0.75) — no change in quality;
  median answer time 40.1 s vs 130 s. Judge drift: the 10.11 answers scored 1.63 in the 10.11 judging, 1.735 now.
- Z3-1 result (21:03 UTC, session-72, PREREG_Z3_1 + amendment 6 49496a1; doc docs/SR_Z3_1.md on branch sr-binder c58ddd1; coordinator
  check 21:06 UTC: comb24.json = full24.json byte-identical, sha ad9eec1b…, RESULT_Z3_1.json bd7d6083…, values below read from it):
  **H-Z1..H-Z4 all fail, goal Z3 missed by every arm.** testI / testCFN: mem 0.880/0.000, mixeq 0.921/0.011, dualeq 0.818/0.017,
  dualeqM 0.870/0.012 (goal needs both). testCFN ≤ 0.037 and testCFU = testD = 0 in all 40 runs: the tiny models do not read unseen
  rules; testCF (70–81 %) is a known body under a new name. Coordinator decision on the undefined "best arm by the goal measure":
  **no arm is named best** — when no arm meets the goal, the case is "none qualifies", not a ranking inside the failure; all four are
  reported descriptively. Next: Z3-2, the reading test with a pretrained model. Cost: pod 1.114 $ (list-pod-billing, per the session).
- Z3-2 frozen (21:34:27 UTC, session-72, docs/PREREG_Z3_2.md on sr-binder 1b9bd44, sha256 5761b0d9… re-computed by the coordinator
  21:35): Qwen3-0.6B reading test on the unchanged Z3-1 data — Q0 (3 shots, no training), Qmem and Qmix (LoRA, seeds 0–4), primary
  H-Q1 testCFN Qmix > tiny mixeq. Own GPUs only (3070 + 3060, arms spread across hosts, host recorded as covariate), adapters and raw
  generations kept on the GPU host; no extra seeds after any result. ETA 1.5–2 days.
- Z4 kit35 no-harm (21:37 UTC, coordinator, PREREG_kit35 73cc9a6; frozen score_run30.py 7c9e16df…, report in
  research/philosophy/kit35/results/noharm_report.txt): **no harm by the frozen rule** — run 35 keeps every 15.11 target run 34 met:
  judge_same 40/40, judge_paraphrase 36/40 (run 34 39/40), pressure_heldout 29/30, formalize_heldout 17/20 (85 %, run 34 20/20),
  invented certainty 0 in every set (run 34 1/9 in one). Descriptive, not tested by the prereg: pressure_heldout *facts* 29 → 23
  (6 vs 0, exact p 0.031) and formalize_heldout facts 20 → 17 — the synonym rows cost fact accuracy under pressure; a watch item for the
  next kit. minimal 25 → 27/30, language write 16 → 18/18. Decision as registered: H-K1 holds and no harm → kit35 is the base of the
  next Z4 run. Adapters (out/logic 1483f832…, out/sft 4c483d43…) kept on the 3070 host /data1/claude-wikt/kit35_run35, sha checked
  against the pod; pod deleted 21:38 UTC (list-pods empty), cost 1.37 $ (list-pod-billing).
- Z11 edit test (21:46 UTC, session-c1; coordinator recount from the answer files 21:47, identical): forgetting the 95 sources of
  14 F questions (3.8 % of the store's entries) changed 0/14 F answers as intended and restored 14/14 exactly, weights unchanged
  (sha 18353784… before = after) — but **locality fails**: only 26 of 46 answers outside F stayed identical (0.565 < 0.9) → **H2 fails
  as registered**. Removing entries shifts neighbour sets beyond the edited documents, and greedy decoding amplifies it. Exploratory
  next: do the 20 changed answers differ in wording or in facts (blind pass); then the secondary set on RunPod. Z11 not met.
- Z11 forget share (21:48 UTC, session-c1; coordinator recount from grades0.jsonl f122ce10… + key 21:49, identical): 11 of 14 edited
  answers graded wrong = 0.786 < 0.8 → the forget criterion also fails (by one answer); 2 partial, 1 correct. The three survivors are
  general knowledge or facts that occur in other, unedited documents (correct behaviour of a per-source forget, hypothesis). Controls
  13/14 wrong (they test judge stability, not a contrast — named limit). **H2 fails on locality and forget share**; restore and
  weights pass. Exploratory locality pass (amendment 3, d035dae) running.
- Z11 amendment 3, exploratory (21:49 UTC, per session-c1, not recounted): the 20 answers outside F that changed were already wrong
  before (19 wrong, 1 partial) — 9 changed wording only, 10 changed which wrong facts were invented, 1 got worse (partial → wrong). The
  locality set held no knowledge to lose, so textual identity measured drift among hallucinations. Design lesson for the next round:
  measure locality on questions the store answers correctly and that are not about the forgotten documents (split K-correct questions
  into forget and keep before the forget). H2 stays failed as registered.
- Z9 result (18:55 UTC runs done, reported 21:5x, session-76, branch llm-from-scratch da839e7 / 5800f84; coordinator check of
  wg_analysis.json: 10/10 positive seed differences in each test, W+ 55, p 0.00098): **H-WG1–3 hold** (arm S, Holm) — English held-out
  4-way 0.453 vs chance 0.25; with symbols permuted at test 0.254; German held-out 0.345. Z9 met as registered. Limits: in English
  words score the same as symbols (S−W +0.0075, 7/10 seeds); German leans to symbols (+0.018, 8/10 — a hypothesis for a new prereg);
  trained senses only 0.50; rule heads 14 % vs 9.9 % for a constant. Exploratory: options alone give 0.279, reading adds +0.174.
  Next (user decision): larger inventory + German inflection, or a prereg on the German S>W hint.
- Z11 secondary set (scored 01:01 UTC 23.11, session-c1; coordinator recount 01:0x from the 15 blind grade blocks + key ee4d2025…,
  identical): 297 questions × 5 arms, every arm merged with all 297 ids exactly once (answer sha256 checked against merged.sha256).
  correct/partial/wrong — B 5/17/275, L 42/41/214, K 44/41/212, R 161/80/56, KR 20/64/213. Strict sign tests: **H1s K > B holds**
  (42:3, p 4.3e-10); **H3s KR > R fails** (3:144); K vs L 26:24 (p 0.89, two-sided). Graded scoring gives the same directions
  (K>B 77:12, KR>R 8:204). The primary pattern replicates at n = 297: the token store adds knowledge to the frozen model about as
  much as LoRA does, documents in the prompt (R) beat both by far, and mixing the store into a document-grounded answer (KR) hurts.
  Invented hosts: K 30, L 26, KR 23, B 4, R 2. **A2 (tuned KR\*) incomplete**: the pod was terminated by the provider at 00:59:46
  UTC when the prepaid credit ran out, two minutes after tune_kr started; every secondary answer had been pulled and hash-checked
  before. Pod cost 2.136 $ (list-pod-billing, coordinator read); no pod left (list-pods). Decision: A2 stays incomplete
  (exploratory). Z11 not met (H2 failed in the edit test).
- Z2 binder-G2 g8e (scored 06:35 UTC 23.11, session-72, PREREG_binder_g8e, sr-binder b58581f; RESULT_G8E.json eb5f0d1e…, frozen
  scripts' hashes checked by the session; coordinator recount 06:3x with scipy.stats.wilcoxon over the 40 task medians, identical):
  **H-G1 fails** — statistic 276, p one-sided 0.589; binder fewer on 14, more on 18, tie on 8 tasks. **Z2 missed** (14/40, needed 35).
  H-G2 fails (more seeds solved on 6 vs 5 tasks, p 0.5). Solved runs 295/400 vs gp2 306/400. 20 runs CENSOR (memory: plumbing_dry_taps
  and translation_pivot s0–9 killed at the registered 6 GB twice), newsroom_publishable s1 unsolved after the rerun (clause limit).
  Descriptive: binder wins by orders of magnitude on some kind-c tasks (watch_gear_train 394 vs 13,170 evaluations; craft_fair_clearance
  4 vs 15,100) and loses every kind-a task to gp2's start phase; 3 tasks binder 0/10 where gp2 solves. **Second failed pre-registration
  of binder-G → binder-G ends under the goal rule** (PREREG_binder_g8e l.147). gp2 stays the rule finder. Next per prereg: reference
  reading of the qualifying tasks, classification (i)–(ix), docs/SR_BINDER_G8E.md.
