# Z11-1 results: kNN-LM token store vs. LoRA vs. RAG on the run-3 knowledge probe

Status: final, 23.11.2026. The primary result, the edit test and the secondary set (amendment 1) are complete. Amendment 2 is
incomplete: the rented host was terminated before its tuning finished.

Pre-registration: [PREREG_Z11.md](PREREG_Z11.md) (frozen 15:41 UTC), amendments [A1](PREREG_Z11_A1.md),
[A2](PREREG_Z11_A2.md) and [A3](PREREG_Z11_A3.md), deviations [D1](PREREG_Z11_D1.md), [D2](PREREG_Z11_D2.md) and
[D3](PREREG_Z11_D3.md). Each has a sha256 file next to it. All times are UTC from `date -u`.

## Question

Can the knowledge that LoRA run 3 put into the weights instead live in an editable token store next to frozen weights (kNN-LM,
Khandelwal et al. 2019, arXiv:1911.00172), so that it can be forgotten and restored without training?

## Setup

- **Base model:** Qwen/Qwen3-0.6B at a pinned revision, float32, greedy decoding, decoding budget 2,048 tokens (as in run 3). The
  same system instruction is used for every arm.
- **Store:** `vi_mcp.knn_lm.Datastore` built from the 2,558 training rows of run 3: 263,273 entries, 1.08 GB of float32 keys, at
  revision 2558.
- **Arms:**
  - B: the base model.
  - L: LoRA run 3, rank 64, 4 epochs.
  - K: kNN-LM.
  - R: BM25 top-3 documents in the prompt.
  - KR: K and R together.
- **Frozen parameters**, chosen on 374 validation rows from documents outside the probe (`frozen_params.json`, sha256 1242b7bc…):
  - k = 32;
  - temperature 476.74 (a factor of 0.1 on the median nearest squared L2 distance);
  - weight 0.8;
  - RAG top-3.
- **Questions:** the 60 never-trained knowledge-probe questions about trained documents (run 3).
- **Judging:** a blind pointwise grade against the reference and the source document: correct, partial or wrong.
  - The letter order is seeded per question, and the key is kept in a separate file.
  - The judges are fresh subagents that read only the block file.
  - Exact sign tests.
- **Judge check:** the base and LoRA answers are identical to run 3's, 60/60 each. The judges agree with the run-3 grades on
  98.3 % (κ 0.88 for B, κ 0.96 for L).

## Primary result (scored 22.11.2026 20:12:55)

| Arm | correct | partial | wrong | graded score (1 / 0.5) |
|---|---|---|---|---|
| B | 0 | 4 | 56 | 2.0 |
| L | 7 | 8 | 45 | 11.0 |
| K | 8 | 6 | 46 | 11.0 |
| R | 41 | 11 | 8 | 46.5 |
| KR | 1 | 17 | 42 | 9.5 |

| Hypothesis | Test (wins:losses, exact sign test) | Verdict |
|---|---|---|
| H1 K > B | 8:0, p = 0.0039 one-sided | **holds** |
| H2 K ≥ L (point estimate) **and** edit test passes | 8 ≥ 7 (5:4, p = 1.0 two-sided); edit test below | **fails** (edit test) |
| H3 KR > R | 0:40 | **fails** |

Descriptive comparisons:
- R > L: 35:1;
- R > K: 35:2;
- L > B: 7:0;
- KR vs. L: 0:6.

### Secondary measures on the probe

| Arm | NLL of the reference answers (2,464 tokens) | perplexity | median s per answer (CPU, 4 threads) | budget hits |
|---|---|---|---|---|
| B | 3.019 | 20.5 | 6.2 | 1 |
| L | 3.172 | 23.9 | 16.8 | 0 |
| K | 2.370 | 10.7 | 19.9 | 4 |
| R | 0.982 | 2.67 | 24.2 | 0 |
| KR | 1.355 | 3.88 | 43.1 | 9 |

- L has a higher NLL than B even though L answers more questions correctly. The references were written by run 3's generator
  model. Hypothesis: the adapter learned its own answer style and is penalised on text worded by another model.
- KR is close to R in NLL but far below R in generated answers (1 vs. 41 correct). NLL measures how likely the model finds a given
  answer, not what it generates.

## Edit test (pre-registered; run 20:45–21:46, blind pass 2 scored 21:48:40)

F is the set of 14 probe questions on which K was graded correct or partial. All 95 store sources of their 14 documents were
forgotten in one batch, which moved the store from revision 2558 to 2653 and left 253,207 entries.

| Part | Criterion | Result | Verdict |
|---|---|---|---|
| Forget | ≥ 80 % of F's edited answers graded wrong | 11/14 = 78.6 % (11 wrong, 2 partial, 1 correct) | **fail** (by one answer) |
| Locality | ≥ 90 % of the answers outside F textually identical | 26/46 = 56.5 % | **fail** |
| Restore | every F answer from the snapshot identical | 14/14 | pass |
| Weights | weights hash identical before and after | identical | pass |

- **Forget.** Two of the three edited answers that were not graded wrong are about facts the base model or general knowledge also
  supplies; in the primary, the base model was partial on one of them. The fact asked by the third occurs in 8 of the 500 training
  documents, and only F's documents were forgotten.
  - Hypothesis: the fact survives through the other documents' entries. A per-source forget is then working as designed, and the
    test should forget by fact, not by document.
- **Controls.** The 14 unedited control answers came back 13 wrong and 1 partial. By construction they are questions K did not get
  right, so they check that the judge is stable. They are not a contrast.
- **Locality, exploratory (amendment 3; scored 21:49:31).** The 20 changed answers outside F were judged blind as before/after
  pairs.
  - Before: 19 wrong, 1 partial. After: 20 wrong.
  - Pair verdicts: 9 same facts, 10 different (but equally wrong) facts, 1 after worse.
  - Outside F the store had no knowledge to lose, so the textual-identity criterion measured drift among invented answers.
    Removing 3.8 % of the entries changes the neighbour sets, and greedy decoding amplifies small shifts in probability.
  - This cannot rescue H2.

## Reading

- **The store carries document knowledge to new questions (H1).** At this scale, it does so about as well as LoRA run 3: 8 vs. 7
  correct, with an equal graded score of 11.0.
- **Retrieval in the prompt is far ahead of both.** R gets 41/60 correct.
  - This contradicts the closest prior work. In SILO (arXiv 2308.04430, Table 4), the kNN-LM closes 91 % of the perplexity gap
    and in-context retrieval only 27 %. Here R leads K in NLL (0.98 vs. 2.37) and in correct answers (41 vs. 8; 161 vs. 44).
  - Likely differences, all **hypotheses**, none tested here:
    1. **Measure.** SILO measures language-modelling perplexity on running text. We measure answers to questions, where one
       retrieved document can hold the whole answer.
    2. **Scale.** SILO's datastores hold up to 1 billion tokens per domain, and its in-context blocks are 1,024 tokens. Ours holds
       263,273 entries from the 2,558 training rows of 500 documents, and R puts the three best-matching whole documents into the prompt.
    3. **Model.** SILO uses a 1.3B base language model under domain shift, where in-context use is limited by the parametric
       model (SILO §5.2). We use a 0.6B instruction-tuned model that reads a prompt and answers.
- **Mixing the store into a prompt that already has documents hurts.** KR got 1 correct. Its weight of 0.8 was tuned without
  documents. Amendment 2 tests whether this weight is the cause.
- **The forget is not yet clean, and not local in text.** Restore and frozen weights work exactly as designed.
- **What the next design needs:**
  1. Forget by fact, not only by source.
  2. Measure locality on questions the store answers correctly outside the forgotten documents.
  3. Mix in the store only when the retrieval is confident.

## Secondary set (amendment 1; scored 23.11.2026 01:01:26)

The set has 297 new questions about the trained documents, written and checked as described in A1. All five arms ran on one
rented CPU host (deviation 3: AMD EPYC 9655P, the same software versions, the identical answer path). Before the run, a cross-host
check found 9 of 9 texts identical to the workstation's. The questions were split into shards that were stopped and resharded by
memory headroom (D3 addenda). The merged answer file of each arm holds each of the 297 ids exactly once, with 0 duplicates.

| Arm | correct | partial | wrong | graded score | budget hits | abstain | invented host |
|---|---|---|---|---|---|---|---|
| B | 5 | 17 | 275 | 13.5 | 3 | 25 | 4 |
| L | 42 | 41 | 214 | 62.5 | 2 | 0 | 26 |
| K | 44 | 41 | 212 | 64.5 | 26 | 0 | 30 |
| R | 161 | 80 | 56 | 201.0 | 0 | 2 | 2 |
| KR | 20 | 64 | 213 | 52.0 | 39 | 1 | 23 |

| Test (A1) | wins:losses | p | Verdict |
|---|---|---|---|
| H1s K > B | 42:3 | 4.3e-10 one-sided | **holds** |
| H3s KR > R | 3:144 | 1.0 one-sided | **fails** |
| K vs. L (two-sided) | 26:24 | 0.89 | no difference shown |

Descriptive comparisons:
- R > L: 133:14;
- R > K: 132:15;
- L > B: 40:3;
- KR vs. L: 14:36 (p 0.0026, two-sided).

The primary pattern replicates at five times the size. The store and the LoRA adapter carry about the same amount of document
knowledge. The base model knows almost none of it, and retrieval in the prompt is about four times better than either. The store
and the adapter invent hosts at about the same rate (30 vs. 26 answers), and neither abstains. Leakage named in A1: the kNN
parameters were tuned on validation rows from the same 440 documents; these were rows, not these questions. As A1 requires, this set
is supporting evidence only and is not pooled into the primary test.

## Amendment 2 (KR with a weight tuned with documents in the prompt): incomplete

`tune_kr` started on the rented host at 00:57:45 UTC. The provider terminated the host at 00:59:46 UTC because the prepaid account
balance was used up (audit log: status TERMINATED; balance −0.06 USD). No weight was frozen and no KR\* answer exists. The
hypothesis therefore stays open. Two observations point the same way without testing it:
- KR's NLL on the probe references (1.355) lies between R's (0.982) and K's (2.370);
- KR loses 0:40 and 3:144 against R in generated answers.

The rented host cost 2.14 USD in total (provider billing per pod).

## Related work, and whether it predicts these results

The four papers below were read on 23.11.2026, from the arXiv HTML versions; venues are from the arXiv pages or the ACL Anthology.
Figures are quoted with their table or section. "Not in the paper" means not found in the parts read.

**SILO** (Min et al., arXiv 2308.04430, ICLR 2024 spotlight)
- **Setup.** A 1.3B model trained only on permissively licensed text, with a datastore of up to 1 billion tokens per domain.
  - Two ways to use the datastore: as a kNN-LM, or BM25 blocks of 1,024 tokens put in the context (RIC-LM).
  - The measure is language-modelling perplexity. The only downstream tasks are zero-shot classification; there is no generation
    or question answering.
- **Results.**
  - The kNN-LM closes 91 % of the perplexity gap to Pythia averaged over 8 out-of-domain sets: 19.0 → 12.0 against 11.3, while
    RIC-LM closes 27 % (Table 4). The paper concludes that "kNN-LM is more effective than RIC-LM" (§5.2).
  - Opt-out (§5.3, Table 6) compares a Books3 datastore with and without the Harry Potter books; it does not delete from an
    existing store. Average perplexity on a held-out book is 12.9 with them, 16.5 without, and 17.4 for the model alone.
- **Prediction for Z11.**
  - SILO predicts K ahead of R. The opposite happened here: R was ahead of K in NLL (0.98 vs. 2.37) and in correct answers (41 vs.
    8, and 161 vs. 44). Hypothesis: our R puts the three most relevant whole documents of a small corpus into the prompt of an
    instruction-tuned model that answers a question. SILO's RIC-LM serves perplexity under domain shift, where it is limited by
    the parametric model (§5.2).
  - On removal, SILO and our edit test agree on two points:
    - The store's own contribution goes away by construction: "data removed from the datastore is guaranteed not to contribute"
      (§4.2). Our restore (14/14) and the identical weights fit this.
    - What other data holds stays: in SILO, 16.5 rather than 17.4 after removal. In Z11-1, the one fact found in 8 other training
      documents survived the forget. SILO did not measure answers to questions.

**Wang et al., "kNN-LM Does Not Improve Open-ended Text Generation"** (arXiv 2305.14625, EMNLP 2023)
- **Setup.** GPT-2 small and TRIME, with WikiText-103 datastores, on open-ended continuation. There is no question answering in
  the paper.
- **Results.**
  - Perplexity improves (14.8 → 12.6, §3.4), but generation quality does not: MAUVE 0.773 vs. 0.793, with "no convincing
    winner" (§4). Human raters preferred the baseline in 51 % of pairs, against 49 % for kNN-LM (§4.1).
  - The retrieval distribution's entropy grows faster than the base model's as the generated text gets longer (§5.2, Fig. 3).
    Their hypothesis is that retrieval is "less reliable when using model-generated text as queries".
- **Prediction for Z11.** Only partly. K's NLL gain did carry over to answers (K > B: 8:0 and 42:3). It is not the null result
  they found for continuation. Their warning fits two observations, though neither was tested as such:
  - KR is close to R in NLL (1.36 vs. 0.98), but far behind it in answers (1 vs. 41).
  - The budget hits of the store arms (K 26, KR 39 of 297, against R 0) point to degenerating long generations.

**Geng, Zhao, Rush, "Great Memory, Shallow Reasoning: Limits of kNN-LMs"** (arXiv 2408.11815, NAACL 2025 short)
- **Setup.** Llama-2-7B, Llama-3-8B and Mistral-7B, each with token-level datastores built from Wiki-style text or from math text.
- **Results.**
  - The datastores help a little on memory-type classification and hurt slightly on knowledge and reasoning tasks. For example,
    NQ with Llama-2 goes from 23.18 to 22.53 (Table 4).
  - Oracle retrieval does not always help either. With test items in the store, NQ rises to 46.40 from 23.64, yet "the model does
    not always derive the correct answer, even when the correct answer is explicitly given as one of the k nearest neighbors"
    (§7, Table 6).
  - Tuning the mixture weight on OBQA and HotpotQA gives the lowest loss "when λ is close to 0" (§7).
  - The paper has no comparison with retrieval in the prompt.
- **Prediction for Z11.**
  - Their oracle result matches the ceiling we saw. Our store holds rows of exactly the documents asked about, and K still
    answered only 44 of 297 correctly.
  - Their λ ≈ 0 finding on QA predicts that the weight 0.8, tuned without documents, is too high once documents are in the prompt.
    That is exactly the amendment-2 hypothesis for KR ≪ R; amendment 2 tests it.
  - Their slight loss against the base model does not match our K > B. Hypothesis: our base model knew almost nothing about these
    internal documents (B 5/297), unlike NQ for a 7B model.

**TOFU** (Maini et al., arXiv 2401.06121; listed at an ICLR 2024 workshop; no main-conference record found)
- **Setup.**
  - 200 fictitious authors, learned by fine-tuning, with forget sets of 1, 5 and 10 % and a retain set. The authors are fictitious
    to ensure "that no remnants of it exist in the model's pretraining phase" (§2.1).
  - Forget quality is a KS test on truth ratios against a reference model trained only on the retain set (§2.2.3).
- **Result.** "none of the baselines we consider show effective unlearning" (abstract).
- **Prediction for Z11.**
  - TOFU measures forgetting on facts the model knows, against a retain-only reference. Z11-1 measured locality on questions the
    store did not answer correctly, which is the flaw A3 found. Z11-2 follows TOFU's design: forget and keep questions that K
    answered correctly before the edit.
  - Z11-2 addendum 1 adds TOFU's pretraining argument as the descriptive class "base knows".
  - TOFU's reference model corresponds to the base model with a store that never held F's documents. A store forget produces
    exactly this, without gradient steps, which TOFU's methods cannot do. What can stay is knowledge from the weights and from
    other documents.

## Named limits

- n = 60. H2 is a point estimate, not an equivalence test.
- One model family judges: Claude subagents, the same family as the session that ran the experiment. Each judge saw only the
  blinded block.
- Duplicate question pairs occur in each primary block.
- The decoding budget was reached in 4 K answers and 9 KR answers. Those answers count as at most partial.
