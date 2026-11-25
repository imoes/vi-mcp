# Z1 — proposal for the next registration (25.11.2026, draft; nothing starts without the user's go)

## Where Z1 stands
- Deployed reader: R3r + base, primary-first merge (PREF). Score: 75.5 % official alias EM on fresh4 (PREREG_R3m). Target ≥ 80 %,
  that is +18 questions of 400. Gold-fact ceiling on fresh4: 94.5 %.
- Diagnosis (DIAGNOSIS_Z1.md; exploratory, on the spent sets fresh3 and fresh4) found three things.
  1. **The remaining loss is facts that neither reader writes.** 31 of the 44 missed gold facts on fresh4 are in neither read. Then
     come answer form (about 13 questions) and evidence that is not in the text (19).
  2. **No pipeline step over the current reads helps.**
     - The relation type guard changed 0 answers.
     - A perfect gold arbiter between the two readers gives at most +0.25 points on fresh4 and +2.0 on fresh3.
     - A title snap fixes ≤ 4 wrong answers and puts about 22 right ones at risk.
  3. **The lead from Z5 (type binding, "latest") does not carry over.** R3r breaks a type in 4 of 4,544 triples.
- So the lever must produce **new candidate facts** and **choose among them without gold**.

## What the literature says (LITERATURE_Z1.md; 15 papers read in full)
- **Voting on executed results works, and agreement predicts correctness.**
  - Self-Consistency (Wang et al., ICLR 2023, §3.5).
  - MBR-EXEC (Shi et al., EMNLP 2022, Table 2): on Spider, greedy 50.8 → MBR-EXEC 63.6. Checked in the PDF by me, 25.11.
  - Filtering to executable candidates already carries much of that gain (§4.4.3).
  - Our analogue: sample several reads, derive an answer with clingo from each, and vote on the derived answer.
- **Hard constrained decoding hurts small models.** Below 3B, schema validity went 61.5 → 100 % while accuracy fell 19.7 → 11.0
  (preprint 2605.26128). Grammar-constrained decoding has the empty string as its mode unless length is normalised (Geng et al. 2023
  §5). So: no constrained decoding; check after generation.
- **Solver error feedback fixes syntax, not meaning.** Logic-LM's executable rate rose, but GPT-4's accuracy fell on FOLIO and
  AR-LSAT (Pan et al. 2023, Table 3). Our reads are valid but wrong, so a repair loop on clingo errors is not the lever.
- **Abstention on UNSAT/ambiguity** raises selective accuracy (SatLM on CLUTRR, Table 5). It does not raise EM on all questions, so
  it is not a Z1 lever.
- **Part of class 4 is built into the gold.** 2Wiki evidence comes from Wikidata. Values are checked only by string presence, and
  demonyms are matched by aliases (Ho et al. 2020 §3.2, App. A.1). Human upper bound: EM 91.0 (Table 7). Some of our "missed" facts
  are gold choices, not reading errors.

## Proposed path: a cheap development probe first, then one registration

### Step 0 — development probe (fresh4 only, spent; about 1–1.5 GPU hours; needs a 3070 slot or the peer's 3060)
- **Reader:** a sampling variant of q1_read_v2.py, `q1_read_sample.py`.
  - Same prompt, same adapter, R3r 0-shot.
  - `do_sample=True`, temperature 0.7, K = 8 samples per paragraph.
  - Seeds fixed, no token cap, the same loop guard.
- **Questions:** 198 of fresh4: the 98 that PREF gets wrong and 100 drawn at random from the 302 it gets right. The second group
  measures harm.
- **Measures:**
  - (a) **Coverage:** how many of the 44 missed gold facts appear in at least one sample.
  - (b) **MBR-READ:** each sample k forms a read set with the base reads, merged by pref; clingo derives answer_k; the majority
    answer over k = 0 (greedy PREF) … 8 wins; ties go to greedy.
  - (c) EM on the 98 and on the 100; extrapolated net gain per 400 (an estimate).
- **Go/no-go rule, fixed before the probe:**
  - Register step 1 only if the extrapolated net gain is ≥ +12 questions per 400 and the harm on the 100 right ones is ≤ 3.
  - If coverage (a) is < 30 % of the 31 facts that neither reader writes, sampling cannot be the lever. Then propose the teacher path
    (below) instead.

### Step 1 — PREREG_Z1s (only if step 0 passes; written and frozen before any fresh5 read)
- **Test set fresh5:** 400 new 2Wiki dev questions, 100 per type, disjoint from all earlier sets. `make_fresh5.py`, seed string
  fixed in the prereg.
- **Arms:**
  - PREF (greedy, as deployed).
  - MBR-READ (K and T as in step 0, unchanged).
  - Both are scored by the frozen official_score.py (7f9170e9, `--title-anchor --tiebreak shortest`).
- **H1:** EM(MBR-READ) > EM(PREF), one-sided exact McNemar, α 0.05.
- **Goal check (descriptive):** EM(MBR-READ) ≥ 80 %.
- **Diagnostics:**
  - stated_recall per arm;
  - DIAGNOSIS classes per arm;
  - agreement rate against correctness (does the vote margin predict EM?).
- **Decision:** H1 holds → the deployed Q1 pipeline reads with MBR-READ. H1 fails → PREF stays.

### The teacher path (only if step 0 shows that sampling does not produce the missing facts)
- A ≤ 9B teacher (BabyLM allows teachers ≤ 9B; research log line 95), such as Qwen3-8B, reads the 2Wiki TRAIN paragraphs.
- Its triples are kept only if the value occurs in the paragraph. They are added to the R3r rows, and the 0.6B reader is retrained.
- That is about 16k paragraphs × ~10 s on one 3070, about 45 h. Too large to propose before step 0 has shown where the facts are.

## What I do not propose, and why
- **Type guard:** 0 effect, measured.
- **Arbiter between the two current readers:** the gold ceiling is +0.25–2.0.
- **Constrained decoding:** the small-model tax (literature above).
- **Solver-error repair loop:** fixes syntax, which is not our error.
- **Abstention:** it does not move EM.

## Named limits
- fresh3 and fresh4 are spent, so all of step 0 is development evidence.
- Sampling makes reads non-deterministic; seeds are fixed and logged.
- MBR-READ costs K + 1 reads per paragraph at inference, about 9× today's read time.
- The judges are the official evaluator: no LLM judge, no human check.
