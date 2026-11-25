# Z1 literature review: repairing the reader in a small-LM + clingo pipeline on 2WikiMultiHopQA

Compiled 2026-11-25. Every paper below was downloaded from arXiv or the ACL Anthology as a PDF and read
as full text via `pdftotext`. Numbers are quoted from the paper's tables. Where I computed a number
myself, it says "(computed)". "Hypothesis" marks every transfer to our setting.
Our setting: Qwen3-0.6B (LoRA + 2-shot base, merged primary-first) emits `relation("S","O")` over the
34 fixed 2Wiki relations, and clingo answers. Alias EM is 75.5 % with the model's reads and 94.5 % with
gold triples (400 dev questions).

Error classes (from the task): 1 type violation · 2 subject binding · 3 role confusion within a type ·
4 granularity / gold noise · 5 downstream answer form or selection.

---

## A. Constrained / schema-aware decoding and type filtering

### A1. GenIE: Josifoski, De Cao, Peyrard, Petroni, West. NAACL 2022
https://arxiv.org/abs/2112.08340 (read: full text)
- **Setting:** BART seq2seq closed IE over Wikidata (5.9M entities, 857 relations). Constrained beam
  search with "(i) a high-level structural constraint … (ii) lower level validity constraints which use
  an entity trie and a relation trie" (§3.3).
- **Effect:** Table 2 (REBEL, micro): GenIE unconstrained P 65.30 / R 67.12 / F1 66.20, constrained
  68.02 / 69.87 / 68.93. The text: "the constrained generation strategy results in an increase of 2-3
  absolute points in terms of F1" (§5.1, measured on the randomly initialised model).
- **What it does not do:** it has no domain/range type check. It also leaves literals out entirely: "we
  only considered triplets for which both entities are element in the entity catalog. However, for many
  useful relations one of the objects is a literal … e.g., date of birth" (§6).
- **Error attribution:** §5.3 / Fig. 3 attributes errors to entity linking and relation classification
  and finds them strongly correlated in the end-to-end model.
- **Applies to class 1 only partly:** a trie can force our object to be a span that occurs in the
  paragraph, but GenIE says nothing about typed literals (dates and places), which is exactly where our
  class 1 errors sit.

### A2. Grammar-Constrained Decoding (GCD): Geng, Josifoski, Peyrard, West. EMNLP 2023
https://arxiv.org/abs/2305.13971 (read: full text)
- **Setting:** few-shot LLaMA/Vicuna (7B–33B) with a context-free grammar enforced by an incremental
  parser. Closed IE on SynthIE-text, entity disambiguation (ED), and constituency parsing.
- **Effect, closed IE:** Table 1, micro F1 unconstrained → constrained: LLaMA-7B 11.9 → 23.5,
  13B 12.9 → 30.6, 33B 17.5 → 36.0. The constraint only ensures "valid entities and relations" (§4.1).
  There is no type-signature check.
- **Effect, input-dependent grammar (IDG):** ED average for LLaMA-33B (Table 2) is 54.1 unconstrained,
  68.2 with an input-independent grammar (IIG), and 80.3 with IDG. "IDG performs better than IIG …
  leverage an input-specific candidate set" (§4.2).
- **Risk:** the most likely constrained output was the empty string. "the top generation is consistently
  an empty string" (§5). It was fixed only by length normalisation α ≥ 2.5 (Table 5). The smaller
  Vicuna-7B "still always outputs '$'".
- **Applies to classes 1 and 2:** an input-dependent grammar could restrict the subject to the paragraph
  title or entities in the paragraph (class 2) and objects to typed spans (class 1). Caveat: all numbers
  are for untuned 7–33B models, not for a LoRA-tuned 0.6B model.

### A3. SynthIE: Josifoski, Šakota, Peyrard, West. EMNLP 2023
https://arxiv.org/abs/2303.04132 (read: full text)
- **Setting:** generate text from sampled Wikidata triple sets with GPT-3.5, then fine-tune T5
  (220M/770M) for closed IE with GenIE-style constrained decoding.
- **Relevant measurement (gold noise):** a human evaluation of the distantly supervised REBEL set:
  "REBEL texts score low in precision (29.4%) … a micro-recall score of 56%, implies that REBEL's gold
  annotations are actually wrong 44% of the time" (§3.5, Table 2). "45% of the triplets are not
  expressed in the input text" (§4.3.1). REBEL's own gold scores F1 73.8 against hand annotation (§4.3.1).
- **Does not apply directly to class 1** (no type constraint study). **Applies to class 4:** gold
  triples aligned from a KB to text are noisy at scale. 2Wiki's evidence is built the same way (see D1).

### A4. RECENT, relation classification with entity type restriction: Lyu & Chen. ACL Findings 2021
https://arxiv.org/abs/2105.08393 (read: full text)
- **Setting:** TACRED (41 relations), with gold entity types given. Candidate relations are restricted
  to those whose domain/range fits the (subject type, object type) pair (Eq. 2–3). This is the cleanest
  measured domain/range restriction I found.
- **Effect:** Table 1:
  - GCN: P 69.8 → 88.3, R 59.0 → 59.3, F1 64.0 → 70.9.
  - SpanBERT: P 70.8 → 90.9, R 70.9 → 64.2, F1 70.8 → 75.2.
  - "the decline in recall limits the further improvement of F1" (§3.3).
- **Error-share measurement:** for GCN, "1,323 examples are false positives … 144 (about 11%) false
  positives among them break the entity type restriction" (§3.4, Table 2). So the model already
  respects types implicitly in about 89 % of its false positives.
- **Applies to class 1** because a type signature removes exactly the type-violating predictions, and
  the gain shows up as precision. Caveat: the types here are gold. Ours would come from a cheap literal
  classifier (date / number / place string), which can itself err.

### A5. Text2KGBench: Mihindukulasooriya, Tiwari, Enguix, Lata. ISWC 2023
https://arxiv.org/abs/2308.02357 (read: full text)
- **Setting:** ontology-driven triple extraction from Wikidata-TekGen and DBpedia-WebNLG, with
  Vicuna-13B and Alpaca-LoRA-13B.
- **Measured:** "a triple is considered to be conforming to the ontology if the relation is one of the
  canonical relations … This can be further extended to validate other restrictions such as domain,
  range" (§4). Domain/range is defined in the ontologies but **not measured**.
- **Error examples:** Table 4 lists an object type error, `award_received(Aparajito, Venice Film
  Festival)` ("mistook the film festival for an award"), plus subject and object hallucinations.
- **Applies to class 1** only as a taxonomy. It gives no effect size.

### A6. OAK+MEND, ontology-grounded post-extraction correction: Loconte, Cornelio, Hospedales. arXiv 2605.29168 v2, 2026 (Findings of EMNLP 2026 per search result, not verified)
https://arxiv.org/abs/2605.29168 (read: full text)
- **Setting:** open-domain LLM KG extraction on HotpotQA/MuSiQue fragments, canonicalised to a
  Wikidata ontology fragment. Symbolic rules detect domain-range violations. An LLM then picks repairs
  (`swap`, `replace_predicate`, `add_subject_type`, `add_object_type`), with the source fragment shown
  and a "no action" option. Each repair is re-validated, for at most 2 iterations (§4.1–4.3).
- **Effect on validity:** Table 1, HotpotQA, share of valid triples 63.4 → 96.8 % (Qwen3-30B-A3B) and
  67.9 → 98.4 % (GPT-OSS-120B).
- **Effect on QA:** Table 2, HotpotQA EM, OAK → OAK+MEND: 47.0 → 45.6 (Qwen) and 46.4 → 46.1 (GPT-OSS).
  The paper reads this as "little or no loss". For QA they "retain triples and qualifiers violating the
  ontology" (§5), so filtering itself was not tested.
- **Repair actions:** Table 3. The most frequent are predicate replacement and swap (for Qwen,
  `swap` 9,671 vs `replace_predicate` 45,539).
- **Constraint at extraction time:** putting constraints into the extraction prompt "drastically
  reduces the number of extracted triples … which in turn reduces QA performances" (§3.1).
- **Applies to classes 1 and 3 (`swap` = subject/object direction)**, but with a warning: much higher
  type validity gave **no QA gain** there. Type repair is cosmetic unless the violating triple was on an
  answer path.

### A7. The Constraint Tax: Ray. arXiv 2605.26128, 2026 (single-author preprint)
https://arxiv.org/abs/2605.26128 (read: full text of the main sections)
- **Setting:** sub-3B models (Qwen2.5-0.5B/1.5B, SmolLM2; 3B as a boundary check) on deterministic
  synthetic tasks, hard JSON-schema decoding vs prompt-only output.
- **Effect:** "hard answer-only schema decoding raises schema validity from 61.5% to 100.0%, but lowers
  answer accuracy from 19.7% to 11.0% and increases wrong-valid-schema outputs from 49.5% to 88.9%"
  (Abstract). In a calendar tool-call task: "prompt-only JSON achieves 91.5% executable accuracy; the
  same hard tool-call schema reaches only 48.0%". Its recommendation: "reason free, constrain late".
- **Applies as a risk to classes 1 and 2:** hard decoding constraints on a 0.6B model can turn invalid
  reads into valid-but-wrong reads. Our model is LoRA-tuned on the output format. **Hypothesis:** the
  tax is smaller for a format-tuned model, but no paper measures that.

---

## B. Verifier / solver feedback for repairing logical forms

### B1. Logic-LM: Pan, Albalak, Wang, Wang. EMNLP Findings 2023
https://arxiv.org/abs/2305.12295 (read: full text)
- **Setting:** GPT-3.5/GPT-4 translate problems into FOL, LP, or CSP and a solver answers. Self-refiner
  prompts with "the erroneous logic form, the solver's error message, and a set of demonstrations"
  (§3.3).
- **Effect:** Table 3, executable rate / accuracy on executable forms, before → after self-refinement:
  - FOLIO, GPT-3.5: executable 66.7 → 84.3 %, accuracy 61.8 → 64.3.
  - FOLIO, GPT-4: executable 79.9 → 85.8 %, accuracy 80.4 → **79.9**.
  - AR-LSAT, GPT-4: accuracy 60.0 → **58.8**.
  - Average executable-rate gain: +5.01 (§4.4).
- **Why it fixes little:** "a valid symbolic representation does not necessarily equate to a 'correct'
  problem formulation … feedback aids in converting 'invalid' symbolic representations into valid ones"
  (§4.4).
- **Does not apply to classes 2–4:** solver error messages repair syntax, not meaning, and our wrong
  reads are syntactically valid atoms. **Applies to class 1 only** if a type violation is turned into an
  explicit error message (cf. A6).

### B2. LINC: Olausson, Gu, Lipkin, Zhang, Solar-Lezama, Tenenbaum, Levy. EMNLP 2023
https://arxiv.org/abs/2310.15164 (read: full text)
- **Setting:** an LLM translates NL premises into FOL and Prover9 proves the result, with K = 10
  majority voting over formalisations (§3).
- **Failure modes (§5.1):**
  - L1, implicit information missing.
  - L2, lossy representation choice (`NaziGermanPolitician(x)`).
  - L3, syntax errors "38% for StarCoderPlus, 24% for GPT-3.5, and 13% for GPT-4", most commonly a
    symbol used with several arities.
- **Precision vs recall:** "LINC's precision when predicting True or False is very high (93%) compared
  to that of CoT (81%), but this comes at the cost of lower recall … (60% for LINC vs. 75% for CoT)"
  (§5.2). LINC predicts Uncertain 57 % of the time vs 41 % for CoT.
- **Voting:** "LINC makes good use of increased values of K … especially … the weaker models; these are
  more prone to generating syntactically invalid FOL … Taking the majority vote … lessens the risk of
  predicting Error" (App. H, Fig. 7; no table values in the text).
- **Gold noise:** of 21 errors shared by LINC and CoT, "16 are ambiguous or incorrect in their
  specification" (§5.2).
- **Applies to classes 3 and 4:** voting helps mostly when samples fail differently. Translation loses
  information but rarely invents it, which matches our "missing fact → no answer" behaviour. Shared
  errors are often gold problems (class 4).

### B3. SatLM: Ye, Chen, Dillig, Durrett. NeurIPS 2023
https://arxiv.org/abs/2305.09656 (read: full text)
- **Setting:** the LLM writes a declarative spec and an SMT solver answers. The solver returns ERROR,
  UNSAT, or AMBIG, and SatLM abstains on those (§3, §4.4).
- **Effect on CLUTRR (kinship):** Table 5, ProgLM → SatLM:
  - correct 58.9 → 68.3, incorrect 21.0 → 7.7;
  - answered 79.9 → 76.0 %, selective accuracy 73.7 → 89.9;
  - SatLM: UNSAT 15.5 %, AMBIG 5.0 %, ERROR 3.5 %.
- **Effect on GSM-Sys:** selective accuracy 45.2 → 77.1.
- **Limitation:** one round only. Re-prompting on UNSAT/AMBIG is left as future work (§6).
- **Applies to class 3 (kin roles)** because contradictions such as `father(A,B)` together with
  `father(B,A)`, or a mother equal to a spouse, make the clingo program UNSAT or produce several answer
  sets. That signal can trigger abstention or a fallback to the second reader. **Hypothesis:** it fires
  only when the role error creates a contradiction, not when it is merely wrong.

---

## C. Self-consistency / agreement across samples or readers

### C1. Self-Consistency: Wang, Wei, Schuurmans, Le, Chi, Narang, Chowdhery, Zhou. ICLR 2023
https://arxiv.org/abs/2203.11171 (read: full text)
- **Finding:** "the consistency (in terms of % of decodes agreeing with the final aggregated answer) is
  highly correlated with accuracy (Figure 5, over GSM8K) … one can use low consistency as an indicator
  that the model has low confidence" (§3.5).
- **Scope:** "applicable only to problems where the final answer is from a fixed answer set" (§2).
- **Applies to class 3:** a vote over per-paragraph reads keyed by (relation, subject) has a fixed
  answer set per slot. Evidence is for arithmetic CoT, not for IE.

### C2. MBR-EXEC: Shi, Fried, Ghazvininejad, Zettlemoyer, Wang. EMNLP 2022
https://arxiv.org/abs/2204.11454 (read: full text)
- **Setting:** Codex samples programs, and the program whose execution result agrees with most others
  is selected.
- **Effect:** Table 2, Spider (SQL semantic parsing): greedy 50.8, sample 48.5, MBR-EXEC 63.6. MBPP:
  47.3 / 47.7 / 58.2.
- **Executability alone is strong:** "simply involving executability checking significantly helps …
  on Spider, applying ML over executable commands even outperforms MBR-EXEC" (§4.4.3).
- **Applies to classes 1 and 3:** vote on the solver's derived answer, not on the raw triples. Filtering
  out non-valid candidates first (= type check) already gives much of the gain.

### C3. Self-Verification for clinical IE: Gero, Singh, Cheng, Naumann, Galley, Gao, Poon. 2023
https://arxiv.org/abs/2306.00024 (read: full text)
- **Setting:** GPT-3.5/GPT-4. The pipeline extracts, then runs Omission (add missed items), Evidence
  (cite a source span), and Prune (drop items the evidence does not support).
- **Effect:**
  - "average F1 improvement across models and tasks is 0.056" (§3.1).
  - Omission raises recall and Prune raises precision (Table 3 caption).
  - Evidence spans overlap human spans "93% for GPT-4" (§3.2).
- **Applies to class 2:** the read must cite a span that names its subject (or the paragraph title is
  the subject). Caveat: the verifier there is a large model. **Hypothesis:** a 0.6B verifier will be
  much weaker. A deterministic span check is the transferable part.

---

## D. 2WikiMultiHopQA: how the gold evidence is made, and known error analyses

### D1. 2WikiMultiHopQA dataset paper: Ho, Duong Nguyen, Sugawara, Aizawa. COLING 2020
https://arxiv.org/abs/2011.01060 (read: full text)
- **Evidence comes from Wikidata, not from the text:** "Evidence information … is a set of triples …
  obtained from the Wikidata" (§1). Paragraphs are Wikipedia summaries (§3.1).
- **Alignment is string presence only:** "the value o1 must appear in the Wikipedia article for the
  entity e1" (§3.2). "because we only checked whether the object entity o appears in the sentence or
  not, there could be a semantic mismatch" (§5.4).
- **Mismatch rate:** "eight out of 100 samples that have a mismatch between Wikipedia article and
  Wikidata triple" (§5.4).
- **Country names and demonyms:** "For the property related to the country name, we handled many
  different similar names by using the aliases of the entity and the set of demonyms" (App. A.1).
  This explains America/American and Yugoslav/Serbian. Dates are "quite consistent", occupation is
  "inconsistent" (App. A.1).
- **Human ceiling:** human upper bound is answer EM 91.0, and evidence F1 78.81 (Table 7). The low
  evidence score is blamed on "ambiguity in the names of Wikidata" (§5.3).
- **Applies to class 4:** granularity mismatches are partly baked into gold through Wikidata values and
  demonym matching. Part of the 94.5 % → 75.5 % gap may not be recoverable by better reading.
  Our 94.5 % with gold triples is above the human UB of 91.0, which was measured on a different
  sample of 100.

### D2. Spurious correct answers: Ishii, Inoue, Suzuki, Sekine. KaLLM workshop 2024
https://aclanthology.org/2024.kallm-1.3.pdf (read: full text)
- **Measured:** GPT-4, closed-book, 100 random 2Wiki dev items. "spurious correct answers (Answer is T
  and Derivation is F) comprise 18% of all cases (which is 31% of the correctly answered cases) in
  2Wiki" (§3.2). Fig. 1 shows a numerical error (1934 for 1943) that still yields the right comparison.
- **Applies to classes 4 and 5:** comparison questions tolerate wrong reads. Scoring our reads against
  gold triples is needed in addition to answer EM.

### D3. T²RAG OpenIE audit: Gong, Tang, He, Yang, Jin. arXiv 2508.02435, 2025 (preprint)
https://arxiv.org/abs/2508.02435 (read: appendix B.8 in full)
- **Measured:** an LLM OpenIE extractor on 50 random 2Wiki documents. Table 8: P 95.9 %, R 98.2 %.
  Table 9, share of documents with ≥1 error:
  - Missing 52 %;
  - Over-merge 40 %;
  - Inaccurate 10 %;
  - Over-split 10 %;
  - **Placeholder 4 %**;
  - Hallucination 2 %.
- **Caveats:** the paper's counts say 16 perfect and 33 erroneous documents, which adds up to 49, not
  50. It is open IE with no fixed schema.
- **Applies to class 1:** the placeholder class ("unknown") also shows up with a much larger extractor.

**Searched and not found:** no paper I found analyses subject-binding or entity-linking errors of a
triple reader on 2Wiki specifically (WebSearch 2026-11-25, two queries). Ho et al. 2023
(https://arxiv.org/abs/2302.05963, abstract and §1 read) report only that "correct reconstruction of the
entity-level reasoning task contributes to finding the correct answer in only 37.5% of cases".

---

## Summary table

| Class | Best-supported intervention | Expected size (source) | Risk |
|---|---|---|---|
| 1 Type violation | Deterministic post-hoc type check per relation range: date regex for date relations, non-numeric place for place relations, placeholder blacklist. On violation, take the secondary reader's read for that slot instead of dropping it ("constrain late"). | Precision gain: +18.5 / +20.1 P at −6.7 R for SpanBERT (A4 Tab. 1). Only about 11 % of false positives were type-breaking (A4 §3.4). Executability filter alone carried most of MBR's gain on Spider (C2 §4.4.3). QA gain may be ≈0 when the violating triples are off the answer path (A6 Tab. 2). | A dropped slot with no replacement turns a wrong answer into no answer. Hard decoding on a 0.6B model can make valid-but-wrong reads: accuracy 19.7 → 11.0 (A7), empty-string mode (A2 §5). |
| 2 Subject binding | Input-dependent constraint or check: the subject must be the paragraph title (or an entity named in the evidence sentence). Optionally cite the source span and prune unsupported reads. | IDG vs IIG ED: 68.2 → 80.3 avg acc, LLaMA-33B (A2 Tab. 2). SV: +0.056 F1 on average, large models (C3 §3.1). No 0.6B evidence. | Legitimate facts about other entities in a paragraph (a parent's birthplace inside the child's article) get lost. Needs an exception for kin objects. |
| 3 Role confusion (incl. kin) | (a) Consistency constraints in clingo (inverse kin, gender, mother ≠ spouse). UNSAT or several answers → abstain or fall back to the other reader. (b) Vote over several reads or readers on the derived answer. | CLUTRR selective accuracy 73.7 → 89.9, incorrect 21.0 → 7.7 % of items (B3 Tab. 5). Spider 50.8 → 63.6 by execution agreement (C2 Tab. 2). Agreement correlates with accuracy (C1 §3.5). | Fires only when a contradiction or disagreement exists. Two readers trained on the same data may agree on the same wrong role. Abstention lowers coverage. |
| 4 Granularity / gold noise | Do not fight it in the reader. Normalise at evaluation (aliases, demonyms as 2Wiki itself did), and report a gold-noise ceiling from a manual audit of lost items. | 2Wiki: 8/100 Wikipedia–Wikidata mismatches, human UB EM 91.0 (D1 §5.4, Tab. 7). KB-aligned gold wrong up to 44 % (REBEL, A3 §3.5). Shared errors 16/21 ill-specified (B2 §5.2). | Over-normalising hides real reader errors. Training on noisy gold teaches the noise. |
| 5 Answer form / selection | Deterministic answer-form rule from the question template (year vs full date), outside the reader. Check reads, not only answers. | No direct literature number. Solver self-refinement does not fix semantics: Exe_Acc −0.5 / −1.2 for GPT-4 (B1 Tab. 3). 31 % of GPT-4's correct 2Wiki answers rest on wrong derivations (D2 §3.2). | Rules tuned on dev overfit. Keep them per question template and test on fresh items. |

**Bottom line (inference from the sources above, not a measured result for our pipeline):**
- Type and range checks buy precision cheaply and reliably, but their QA effect is bounded by how often
  the type-violating triple was on the answer path. A6 measured no QA gain from near-100 % type validity.
- For a 0.6B model, check after generation and fall back to the other reader. Do not hard-constrain
  decoding (A7, A2).
- Solver feedback (Logic-LM) repairs syntax, not meaning. Solver *abstention* on UNSAT/AMBIG (SatLM) is
  the variant with a measured precision gain on kinship.
- Part of class 4 is a property of how 2Wiki gold was built: Wikidata values string-matched to text,
  with demonym aliases.
