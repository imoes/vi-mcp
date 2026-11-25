# PREREG R3m — primary-first merge of the two readers (frozen 22.11.2026 09:18 UTC by PREREG_R3m.sha256, before any fresh4 read exists)

**How it came about (stated, not hidden).** PREREG_R3r2 (fresh3) failed: R3r alone 70.25 % vs union(R3r, base) 71.0 %. The stated-fact
diagnosis on fresh3 showed the union recalls more (94.3 vs 89.2 %) but contradicts more (18.9 vs 11.3 %); by type the union won
compositional (+5) and lost inference (−5). The idea below came from those fresh3 numbers, so fresh3 is NOT a test set for it.
It was then developed on fresh2 (spent for PREREG_R3r, used here as development data), in one session on 22.11.2026:
- `pref` (keep a base triple only when R3r gives no triple with the same relation for a subject sharing a token): union 70.75 % →
  75.25 % official alias EM (21 vs 3 questions, exact one-sided McNemar p 0.00014); inference 53 → 67; conflicts 22.0 → 12.35 % at
  recall 94.6 → 93.1 %. The union's 70.75 % reproduces the earlier AMD-host score exactly (same frozen scorer, now on the workstation).
- `snap` (copy errors snapped to the closest paragraph span, name relations only; two guards added after seeing harmful snaps of dates
  and demonyms): 0 questions changed — dropped, not part of this registration.
No other variant was tried.

**Test set fresh4:** `dev_fresh4_400.json` (sha256 448abff0…), 100 per type, disjoint by id from the development 400, fresh 400,
fresh2 and fresh3 (`make_fresh4.py`, random.Random("q1-fresh4-2026-11-22")).
**Reads:** `q1_read_v2.py` unchanged (sha 5c6e9c6d…) on the RTX 3070 host: R3r (adapter sha f94be8b9…, 0-shot) and base Qwen3-0.6B
(2-shot), after the RAG-1c pool reads, the same launcher pattern as fresh3 (llama-server stopped, restarted in the EXIT trap).
**Arms:** UNION = `score_r3r.py union` (R3r then base, as in PREREG_R3r2); PREF = `reader_merge.py pref R3R BASE`; ALONE = R3r reads.
Answers: frozen `official_score.py` (7f9170e9…) `--title-anchor --tiebreak shortest`, official alias EM, clingo 5.8.3.

**Hypotheses (unit = question, n = 400, exact one-sided McNemar via `score_r3r.py test`, Holm over the two at α 0.05):**
- **H-M1 (primary):** EM(PREF) > EM(UNION).
- **H-M2:** EM(PREF) > EM(ALONE) — the base reader's second call pays only through the merge.
- Descriptive: EM per type; stated_recall.py recall and conflicts for the three arms; PREF on fresh3 (marked: the set that suggested
  the idea, so not evidence).

**Decision:** H-M1 holds → the deployed Q1 reader is R3r + base merged primary-first (a pipeline step, no training). H-M1 fails →
the union stays. H-M2 decides whether the base call is kept at all (fails → R3r alone is as good, one call per paragraph).
Either way kit R3 gets no new reader rows from this line: the remaining reader misses on fresh3 are largely gold facts the text
does not state (sample of 12: Poland/Queensland/Wessex/Childwickbury not stated as birth or death place; 'Somerset' vs the read
'Stoke St Gregory'), a few genuine misses (Thornby's 'born in New York', 'Queen consort of') and one copy error ('Brautat').

**Named limits:** one R3r seed; one development set (fresh2) for the rule; the token-overlap subject test is crude (a namesake
sharing a token suppresses a base triple too); 2Wiki evidence noise bounds the ceiling (gold facts 94.0 % on fresh 400).

**Hashes (sha256):** dev_fresh4_400.json 448abff0d714b8318822858ef63026e1479aa8249f393bef66d445e5a17225e9 · make_fresh4.py
6ae7f5e4a4aed91b64d5decfaef39a7f205828a9414cfcddd3fcb5d89b66f739 · reader_merge.py
b4964509c23136e37dc06e430b76c3604b3bea8f41f80f7d1629aaab692ce9d5 · score_r3r.py db326200f19b597be4d871f6b65e74f99a6fb1e71b3e8bed691f3b0cd15af4b6 ·
official_score.py 7f9170e9bf5e0047a9609142ea337e0ec6089ae03bb20a938ff2f3645655368c · stated_recall.py
4467fb8ecb2632e4419ecf1cf96010c19386e90bfac467b2182f4b6a123b34ba · q1_read_v2.py 5c6e9c6dd3e945307a723ce4206f7c3803fcb90d94784b265ef1e75478d6350b.

## Amendment 1 (22.11.2026 09:32 UTC, compute only — no fresh4 read exists)
The 3070 host is busy with the RAG-1c pool reads, so the fresh4 reads move to a RunPod pod with the SAME GPU type (RTX 3070,
community cloud), image runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404 with transformers 5.23.0 and peft 0.21.3 (the 3070 host's
container has the same two versions, torch 2.7.1 vs the pod's 2.8.0). The same files (q1_read_v2.py sha 5c6e9c6d…, adapter
f94be8b9…, dev_fresh4_400.json 448abff0…) are copied by scp and hash-checked on the pod; R3r and base read in sequence as in
run_q1fresh4.sh. The queued launcher on the 3070 host was stopped before it started (its run.log never existed). Analysis,
hypotheses and decision rule unchanged. (R3r's fresh2 reads also came from a pod — PREREG_R3r named limit.)

## Amendment 2 (22.11.2026 09:38 UTC, compute only — still no fresh4 read exists)
The user preferred their RTX 3060 (12 GB, Ampere, Windows 11, native venv torch 2.7.1+cu128 — the same torch as the 3070 host's
container, transformers 5.23.0, peft 0.21.3) over a RunPod pod. The pod of amendment 1 (4l8x981kmolqfj) was deleted before any read
(list-pods empty at 09:35 UTC). Task TASK-R3M4 in the private exchange repo (commit c53f2cb): the same q1_read_v2.py (5c6e9c6d…),
d0_docs.py (b70ed764…), dev_fresh4_400.json (448abff0…) and adapter (f94be8b97527433d…, sent in two parts and reassembled), all four
checked by exact sha256 before reading; R3r then base, as before. Analysis, hypotheses and decision rule unchanged. Named limit added:
GPU type differs from the 3070 that read fresh2/fresh3 (greedy fp32 decoding; small numeric differences between GPUs can change a
token).
