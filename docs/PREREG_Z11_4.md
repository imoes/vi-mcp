# PREREG Z11-4: can the store's provenance be read?

Date: 24.11.2026. This file is frozen with the sha256 in `PREREG_Z11_4.sha256` **before any Z11-4 readout of a test item
exists**. All times are UTC from `date -u`. Nothing here changes a Z11-1, Z11-2 or Z11-3 result.

## Why

The user's idea behind Z11 is weight-space programming: "Die Idee war ja weight-space programming einzusetzen und diese selbst
geschriebenen Gewichte von einer KI ablesen zu lassen." So far Z11 tested only the write half:
- the store carries document knowledge about as well as LoRA (Z11-1);
- a forget by document removes it, and the snapshot restores it exactly (Z11-2, Z11-3);
- the forget is not local at weight 0.8 (Z11-3: 17/33 kept).

An entry in the store is a 1024-dimensional key plus a next token. What an AI can read from it is its provenance: the document
whose training row wrote it. The user named that as the goal on 24.11.2026 (about 08:44 UTC), quoting the session's own
sentence: "das war das Ziel: Eine KI kann daran nur ablesen, aus welchem Dokument er stammt." The approval of this test, in the
same message, verbatim: "Ja mache den Ablese-Test". The coordinator session reviewed the design before the freeze. Its six points
are built in below.

**Two hypotheses, in this order:**
- **H7 (primary, the user's goal).** For an answer the store answered correctly, the per-token readout of the store names the
  document the answer's knowledge came from.
  - The mechanical rule decides first: is provenance readable at all?
  - The blind AI reader decides second: can an AI read it from the same readout?
- **H8 (secondary, the coordinator's first-divergent-token item).** An edit can be previewed from the store before it is made:
  masking a forget's sources in the neighbour search on the replayed before answer predicts whether the after answer stays
  text-identical, and where it first diverges.

## Literature read before freezing (24.11.2026, 08:46–08:50 UTC)

Arxiv HTML full texts were read by two web-fetch passes with targeted questions. Quotes were checked against the page text. Parts
the fetch tool only summarised are marked.
- **Khandelwal et al.** (arXiv 1911.00172, kNN-LM).
  - §6, "Qualitative Analysis", inspects retrieved contexts by hand. Figure 6 is the one worked example.
  - The kNN component "is particularly helpful in predicting rare patterns, such as factual knowledge" (abstract). §6 adds
    "factual knowledge, names, and near-duplicate sentences".
  - No measure of whether the retrieved contexts identify a source.
  - **What it predicts for us.** Credit should concentrate on fact tokens (names, hosts, numbers), not on function words.
- **SILO** (Min et al., arXiv 2308.04430).
  - The datastore "provides attributions for free to every model prediction" (§4.3), and removed data "is guaranteed not to
    contribute to any model predictions" (§4.2).
  - **Attribution is claimed, not measured.** The only evidence is qualitative (§5.3, Table 7). Removal is measured by perplexity
    only (Table 6: 12.9 with the held-out books, 16.5 without, 17.4 parametric only).
  - **What it predicts for us.** Nothing quantitative. To our reading, no measured attribution accuracy for a kNN-LM datastore
    exists in these sources. Z11-4 measures one.
- **Wang et al.** (arXiv 2305.14625, "kNN-LM Does Not Improve Open-ended Text Generation").
  - The kNN-LM improves perplexity for only 42 % of test tokens; 58 % are adversely affected (§5, §5.1).
  - "The retriever becomes less reliable with longer generated sequences" (§5.2). The retrieval distribution's entropy rises
    faster than the base LM's (figures only).
  - **What it predicts for us.** Credit is spread thin on many tokens. Our answers are short: median 99 tokens, at most 168.
- **Drozdov et al.** (arXiv 2210.15859).
  - The kNN-LM is "most beneficial in the buckets with high semantic similarity" (§3.1).
  - "Most of kNN-LM's improvements on Wikitext-103 come from retrieving contexts with overlapping n-grams" (§5.5).
  - **What it predicts for us.** For correct answers, whose text overlaps the training rows, the answer's own document should
    dominate the credit.
- **Xu et al.** (arXiv 2301.02828). The gain comes from the representation, approximate search and temperature (§1).
  - Which tokens benefit is offered as a hypothesis ("rare, or … frequent, but … multiple meanings", §4.2). The token-type
    analysis was only summarised by the fetch tool, not read.
- **TRAK** (Park et al., arXiv 2303.14186). An attribution method is judged by counterfactuals: "a data attribution method is
  useful insofar as it can make accurate counterfactual predictions" (§1). It uses the linear datamodeling score over retrained
  subsets (Def. 2.4).
  - **What it predicts for us.** The forget is our counterfactual. It costs no retraining: masking is exact. H8 is that
    counterfactual check per answer, and the F side of Z11-2/Z11-3 is one at the set level for H7.
- **Bohnet et al.** (arXiv 2212.08037, attributed QA).
  - An answer is attributable to a source if "all of the information provided by the system response" is supported by it (AIS,
    §3.2).
  - **What it predicts for us.** This motivates the lenient score below: a document other than the question's own that contains
    the answer also counts.

## Pilot (before the freeze, mechanics only)

Two Z11-1 probe questions outside both test sets were used. One changed under the Z11-1 edit and one did not, chosen by that
outcome so that both preview paths ran. The pilot was run under the Z11-1 edit (95 sources) against their real after answers
(`answers_K_edit.jsonl`).
- **Version 1** (08:52:35–08:53:07) replayed the answer teacher-forced from the re-encoded text. One answer failed to reproduce
  at token 39.
  - The cause was re-tokenization: the stored text "…ovsrv…" re-encodes as " o|vs|rv", which generation never produced (mixed
    probability 1e-05).
- **Version 2** (from 08:55:39) replays step by step as generation does. The script is the one frozen here.
  - Both answers reproduced exactly: 128 and 92 tokens.
  - The preview predicted "identical" for the unchanged answer.
  - For the changed answer it predicted divergence at token 33, character 110. The real texts share 111 characters, so the
    divergence falls inside that token.
- These two questions are not part of either hypothesis.

## Material (hashes at freeze)

- **Model and parameters:** the base model, float32 CPU path and `frozen_params.json` (k 32, temperature 476.737, weight 0.8;
  sha256 1242b7bc…), unchanged.
- **Store:** `store_qa`, revision 2558 (manifest sha256 a541c4c6…), read only.
- **Items, 117:** the 52 Z11-2 items (`z11_2_split.json`, 69b16d70…) and the 65 Z11-3 items (`z11_3_split.json`, 0a99b348…). Each
  is a question whose K before answer was graded correct in its pool.
- **Before answers:**
  - `z11_2_answers_before.jsonl` (0581065e…);
  - `z11_3_answers_before_b0/b1a/b1b/b2a.jsonl` (46078fb5…, 6e136b90…, dc0052c8…, 011a710a…).
  - The 117 answers have 11,576 tokens in all, median 99, maximum 168. None reached the budget.
- **Edits for H8, three:**
  - Z11-3 E1: 189 sources, from `z11_3_split.json`;
  - Z11-2 E1: 170 sources, from `z11_2_eligible.json` (b2f74acb…);
  - Z11-2 E2: 424 sources, from the same file.
  - The real after answers are `z11_3_answers_E1.jsonl`, `z11_2_answers_E1.jsonl` and `z11_2_answers_E2.jsonl`. They are read only
    by `score`.
- **Other documents that contain the answer** (the coordinator's point 3), counted before any readout:
  - Script: `z11_4_alt.py` (scratch); output `z11_4_alt_sources.json` (sha256 46a47593…), 08:49 UTC.
  - Rule: a document other than the question's own counts if it contains a word 6-gram of the reference answer.
  - Result: 9 of the 117 items have such a document (6 with 1, 2 with 2, 1 with 3). 102 own documents contain a 6-gram of their
    reference answer.
- **Code:** `scripts/z11/read4.py`, committed with this file.

## The readout (`read4.py readout z11_2|z11_3`)

Each before answer is replayed step by step through the frozen model, with a KV cache, as generation did.
- **Functions.** Every step uses the generation path's own functions: Memory's exact distance expression and top-k,
  `Memory.distribution` and `interpolate`.
- **Token choice.** At each step the mixed argmax is taken while it stays consistent with the stored text, which recovers the
  generated token ids.
- **Mismatch.** If the argmax leaves the text, the position is recorded as a mismatch and the rest of the text is forced.
  "Reproduced" means no mismatch and the generated token count.
- **Per token y_t the readout records:**
  - the base, kNN and mixed probabilities of y_t;
  - S: the store decided the token, i.e. the base argmax ≠ y_t;
  - the **credit** of each document d: `0.8 · Σ_{neighbours n of d with token(n) = y_t} w_n / p_mix(y_t)`. This is d's share of
    the token's final probability. The w_n are the normalised kernel weights of the 32 neighbours.
- **Candidates:** every document with a neighbour among the 32 at some step.
- **Outcomes stay out.** The readout file holds no grade, no after answer and no own document.

## H7: provenance (primary)

**Truth.** The question's own document: the question was written from it. For F items, Z11-2 and Z11-3 back this causally at the
set level, because forgetting the F documents turned 25 of 26 and 31 of 32 correct answers wrong.

**Readers**, all named before the run. The first two need no readout beyond the stored answers.
1. **M0, nearest-document rule.** The top document of the stored `nearest_documents`: the document of the single nearest
   neighbour, counted over the generated tokens.
2. **M1, credit rule.** The document with the largest credit summed over all tokens. Top-3 by the same sum.
3. **M1s** (decides nothing). M1 over S tokens only, or M1 if the answer has none.
4. **The AI reader** (blind). Fresh general-purpose subagents (Claude Opus), one per block of cards, each card bounded to about
   110,000 characters (`read4.py cards`).
   - **A card holds:** one row per generated token, with position, token string, S mark, and the documents with credit ≥ 0.01
     under card-local opaque labels (D01, …, ordered by `sha256("z11-4:label:" + id + doc)`) with their credit.
   - **A card does not hold:** the question, any document text, document ids, the question id, a grade or an after answer.
   - The reader therefore cannot match text against documents: it can only read the store's provenance (the coordinator's point
     1). The token strings are the answer itself. They let the reader weigh fact tokens above function words, which is the one
     thing an AI can add to M1.
   - Card ids are `sha256("z11-4:card:" + id)[:10]`. The key (card → item, label → document) is written to a separate file.
   - The instruction is `read4.INSTRUCTION`, verbatim. The reader writes `{"card", "top3"}` lines to the grades file named for
     its block, and uses no tool except reading its block and writing that file.
   - The grade files' sha256 are written to `judge_z11_4_grades.sha256` before `score` opens the key.

**Measures** (`read4.py score`), on all 117 items:
- strict top-1: the first document is the own document;
- lenient top-1: the first document is the own document or one counted in `z11_4_alt_sources.json`;
- strict top-3;
- per set;
- the chance level: the mean of 1 / (number of candidates) per answer. In the pilot that was 1/172 to 1/251, so about 0.5 %; the
  global level is 1/500.

**Pass criteria** (point criteria, as in Z11-2 and Z11-3; Clopper–Pearson 95 % intervals reported):
- **H7-rule:** M1 strict top-1 ≥ 80 %.
- **H7-reader:** the AI reader's strict top-1 ≥ 80 %.

**Decision table** (fixed now):

| M1 ≥ 80 % | reader ≥ 80 % | reading |
|---|---|---|
| yes | yes | provenance is readable, by rule and by an AI: the user's goal is met for correct answers |
| yes | no | provenance is readable by rule; an AI reading the same cards falls short, so use the rule |
| no | yes | the AI reads better than the sum, presumably by weighting fact tokens; readable by an AI |
| no | no | the store's provenance does not name the source at this threshold; the lenient score says whether shared content explains it |

Also reported, deciding nothing:
- M1 against M0 and the reader against M1: exact two-sided sign test on discordant items.
- Every figure strict and lenient.
- The items without a readout, if any.

## H8: edit preview (secondary)

For each item and each edit that applies to it (Z11-3: E1; Z11-2: E1 and E2), the readout repeats the mixing at every step with
the edit's sources masked to +inf before the top-k. The before token is kept as the path.
- The first step whose masked argmax differs from the before token is the predicted divergence. It is recorded with its character
  offset and width.
- If there is none, the preview says "identical".
- Masking is exactly what `Memory.topk(exclude=…)` and a forget do to the neighbour search, so the preview is exact up to floating
  point.

**Pairs:** 65 + 52 + 52 = 169. A pair is **evaluable** if the readout reproduced the generation up to the predicted divergence, or
everywhere for a predicted "identical".

**Pass criteria** (point):
- identity agreement (predicted identical ⇔ actually text-identical) on ≥ 95 % of evaluable pairs;
- divergence exact on ≥ 90 % of evaluable pairs that are predicted and actually changed. Exact means the real texts' common
  prefix ends inside the predicted token.

**Known before the run, stated so it is not mistaken for a finding:**
- Text identity:
  - Z11-3: F 0/32 identical, Kp 14/33 (`z11_3_compare.json`);
  - Z11-2 E1: Kp 16/26;
  - Z11-2 E2: Kp 10/24;
  - no Z11-2 F answer is identical.
- Kept per item is known only for Z11-3 (`Kp_not_kept`, 16).
- On Z11-3 Kp, predicting kept or not kept gives these baselines:
  - **majority** ("kept"): 17/33 = 51.5 %;
  - **nearest-document rule** (not kept iff an F document is in `nearest_documents`): 16/33 = 48.5 %. An F document appears there
    for 1 of 16 not-kept and 2 of 17 kept answers (recounted by the coordinator).
  - **preview rule** (kept iff predicted identical): 30/33 if the preview is exact on identity. All 14 identical answers are kept,
    and 16 of the 19 changed ones are lost.
  - That last number is arithmetic on known results. The new evidence in H8 is whether the preview is exact, which no earlier
    file tells.
- Descriptive, at the exact divergences: how many fall on S tokens, and the median credit of forgotten documents at that token.
  This is the coordinator's first-divergent-token analysis.

## Precision (computed before the run)

| observed | 95 % CI |
|---|---|
| 94/117 = 80.3 % | 72.0–87.1 |
| 105/117 = 89.7 % | 82.8–94.6 |
| 111/117 = 94.9 % | 89.2–98.1 |
| 158/169 = 93.5 % | 88.7–96.7 |
| 152/169 = 89.9 % | 84.4–94.0 |

A point estimate just at 80 % has a lower bound near 72 %. As in Z11-3, whether each lower bound clears its threshold is reported
too, as a stricter reading that decides nothing.

## Run

- **Host:** the CPU workstation of Z11-1 to Z11-3. One process at a time (the coordinator allows at most 2 heavy processes in all).
- **Limits:** MemoryMax 6G, MemorySwapMax 0, 4 threads, free-memory gate ≥ 8 GB.
- **Commands, in this order:**
  1. `readout z11_2`
  2. `readout z11_3`
  3. `rules`
  4. `cards`
  5. readers
  6. grade hashes
  7. `score`
- **Estimate (a guess from the pilot):** about 0.2 s per token at two edits, so about 40 minutes for 11,576 tokens.
- No data leave our hosts except the cards to the reader subagents. That is the same path as every earlier Z11 judging, and the
  cards carry no document text.
- Commits stay local until the user says otherwise.

## Named limits (stated now)

- **Correct answers only.** Provenance is tested where the store supplied the answer. It says nothing about wrong or invented
  answers, where "the source" is not defined. The Z11-1 pilot answer K got wrong is an example: M1 named another document.
- **One source per question.** Ground truth assumes one own document. The 6-gram count catches literal duplicates, not shared facts
  phrased differently.
- **Credit is one attribution among several.** It is checked counterfactually per answer only through H8's masking, and per set
  through the F forgets. No retraining-based measure like LDS is run.
- **One model family reads.** The readers are Claude subagents, the family of the session that built the cards. The cards are long,
  and the reader may summarise them rather than read every row.
- **One model, one store, one host.** Exactness of the preview relies on deterministic CPU numerics on that host.
- **Deviations** found during the run are written to the results with time and reason. They are never silently absorbed.
