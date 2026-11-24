# Z11 summary: a virtualised LLM (kNN-LM token store next to frozen weights)

Status: **closed 24.11.2026** on the user's decision ("Wir können auch heute schließen"). This file only summarises; every number
comes from the results files linked in each section, and each result was pre-registered there with a sha256 before its data
existed. Nothing here is new evidence.

## The question

Can document knowledge be **written** into an editable store next to frozen weights, instead of into the weights by fine-tuning?
And can the result then be **read back**: which document an answer came from, and what an edit will change, before it is made?
This is weight-space programming applied to a store, with an AI as the reader.

Setup in all parts:
- the base model is Qwen/Qwen3-0.6B, frozen, float32, with greedy decoding;
- the store is `vi_mcp.knn_lm.Datastore`, built from LoRA run 3's 2,558 training rows of 500 documents, with 263,273 entries;
- the frozen parameters are k 32, temperature 476.74 and weight 0.8;
- the judges are blind, pointwise subagents, and the key is opened only after the grade files are hashed.

## Results

| Part | Question | Pre-registered result | Source |
|---|---|---|---|
| Z11-1 primary (60 probe questions) | Does the store carry knowledge to new questions? | **H1 holds:** K 8 correct vs. B 0 (8:0, p 0.0039). K ≈ LoRA (8 vs. 7). RAG 41. | [RESULTS_Z11.md](RESULTS_Z11.md) |
| Z11-1 secondary (297 questions) | Replication at 5× size | **H1s holds:** 42:3, p 4.3e-10. K vs. L 26:24 (p 0.89). RAG 161 correct, K 44, L 42. | [RESULTS_Z11.md](RESULTS_Z11.md) |
| Z11-1 store + RAG | Does the store add to retrieval? | **H3 fails** at weight 0.8 (KR 1 correct). Tuned with documents in the prompt (weight 0.1): KR\* 160 vs. R 165, no gain. | [RESULTS_Z11.md](RESULTS_Z11.md), A2, A4 |
| Z11-2 (52 questions K got right) | Forget by document, locally | **H4 holds (E1):** forget 25/26, locality 24/26, restore 26/26, weights equal. **H5 fails (E2, wider forget):** locality 20/24. | [RESULTS_Z11_2.md](RESULTS_Z11_2.md) |
| Z11-3 (65 new questions) | Repeat at larger size | **H6 failed as scored** (locality 17/33). Z11-4 then showed that half of the after answers came from a process with a corrupted neighbour search. The verdict stays on record. | [RESULTS_Z11_3.md](RESULTS_Z11_3.md) |
| Z11-3 R1 (clean re-measurement) | The same, in one process with the fixed code | **H6-R1 holds:** forget 30/32 (CI 79.2–99.2), locality 33/33 (CI 89.4–100), restore 32/32, weights equal. | [RESULTS_Z11_3.md](RESULTS_Z11_3.md) "Re-measurement R1" |
| Z11-4 H7 (117 correct answers) | Can the source document be read from the store? | **Holds.** Rule 110/117 = 94.0 % (CI 88.1–97.6); blind AI reader 110/117, top-3 116/117; chance 0.5 %. | [RESULTS_Z11_4.md](RESULTS_Z11_4.md) |
| Z11-4 H8 (169 edit pairs) | Can an edit's effect be previewed exactly? | **Fails as scored** (identity 155/169). Every miss is in Z11-3's defective half. Against the clean R1 answers (exploratory): identity 169/169, divergence point 114/115. | [RESULTS_Z11_4.md](RESULTS_Z11_4.md) |

## What Z11 shows

1. **Writing works, about as well as fine-tuning.** The store carries as much document knowledge to unseen questions as LoRA
   run 3 (44 vs. 42 of 297). It needs no gradient step, and the model weights stay bit-identical.
2. **As a way to answer questions, retrieval in the prompt is far better.** RAG gets about four times as many correct answers
   (161 vs. 44). Mixing the store into a prompt that already has documents adds nothing measurable. The store's value is
   therefore not accuracy. It lies in points 3 and 4.
3. **Editing works and is local.** Forgetting a document's entries removes its answers (30/32, 25/26) and leaves answers from
   other documents in place (33/33, 24/26). Restore is exact. A wider forget (E2) costs locality.
4. **Reading works.** From the entries behind an answer, a fixed rule and a blind AI both name the source document in 94 % of
   cases, against 0.5 % chance. Before an edit is made, the store says exactly which answers will change and at which character
   (169/169 and 114/115 against clean answers). For weights, the same counterfactual has to be estimated with retrained models.
5. **Reading caught a defect in our own measurement.** The preview disagreed with Z11-3, and that disagreement exposed a race on
   the key cache (fixed in edfee3a with a temp file and `os.replace`). Only Z11-3's after answers were affected (audit d745b7a).
   The earlier conclusion that the forget is "not local" was withdrawn explicitly.

## What stays open

- **Forget by fact, not by document.** A fact that occurs in several documents survives a per-document forget (Z11-1, Z11-2).
- **Robustness of the forget** under paraphrased questions and sampled decoding. Only greedy decoding was measured.
- **Provenance below the document level.** "Source" means the document whose training rows wrote the entries. Provenance was
  read only for correct answers.
- **Scale and generality.** One model (0.6B), one store, one writer, CPU only. The judges and readers are one model family
  (Claude), the same family as the session that ran the experiments.
- **Store and RAG together** gave no gain. A design that mixes the store in only when retrieval is unsure was proposed and never
  tested.

## Evidence

- Commits on branch `z11-virtual-llm`, from Z11-1 to f2764e7.
- Every prereg has a `.sha256` file next to it.
- The data files and score hashes are named in each results file.
- CHANGELOG entries are under "Unreleased — experiment Z11-1".
