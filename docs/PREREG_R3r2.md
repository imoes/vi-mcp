# PREREG R3r2 — the dedicated reader alone vs the reader union (frozen 22.11.2026 04:42 UTC by PREREG_R3r2.sha256, before any fresh3 read exists)

**How it came about.** PREREG_R3r (fresh2, 400 questions) confirmed union(R3r, base 2-shot) 70.75 % > union(R1-full, base) 66.0 %
(p 0.0022). Descriptively R3r ALONE gave 73.0 %, and the stated-fact diagnosis explains why: R3r recall 91.3 % with 9.8 % conflicting
values, the union 94.6 % with 22.0 % (the base reader adds conflicts). This registration tests that descriptive finding on new data.

**Test set fresh3:** `dev_fresh3_400.json` (sha256 2682689b…), 100 questions per type from the 2Wiki dev set, disjoint from the fresh
400, fresh2 and the development 400 (random.Random("q1-fresh3-2026-11-22")).
**Reads:** `q1_read_v2.py` unchanged (sha 5c6e9c6d…) on the RTX 3070 host: R3r (adapter sha f94be8b9…, 0-shot) and base Qwen3-0.6B
(2-shot), launcher `run_q1fresh3.sh` (sha d5d73dc8449316be…), after the sym-rag pool reads.
**Arms:** ALONE = R3r reads; UNION = R3r reads then base reads per question (score_r3r.py union order). Answers by the frozen
`official_score.py` (sha 7f9170e9…) with `--title-anchor --tiebreak shortest`, official alias EM.

**Hypothesis (unit = question, n = 400, α 0.05):**
- **H-R3r2:** EM(ALONE) > EM(UNION) — one-sided exact McNemar (`score_r3r.py test PER_UNION PER_ALONE`, sha db326200…: b = right only
  in ALONE).
- Descriptive: base alone; EM per type; stated_recall.py recall and conflicts per relation.

**Decision:** H-R3r2 holds → the deployed Q1 reader is R3r alone (one model call per paragraph instead of two). It fails → the union
stays (it was confirmed against the old union).

**Named limits:** one training seed of R3r, trained on a pod with an interrupted-and-resumed run (PREREG_R3r amendment 2); reads on
the 3070 host (R3r's fresh2 reads came from the pod).
