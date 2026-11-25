# PREREG Q1 pipeline levers — span tie-break and title anchoring on fresh 2Wiki questions (fixed 21.11.2026 ~10:15 UTC, before any read of the test questions exists)

**How it came about (stated, not hidden):** both levers were found and tuned by reading the errors of the gold-free pipeline on the
400 development questions (2Wiki dev, 100 per type) that every Q1 step so far used (research log, 21.11.2026 "Where the pipeline loses
chains"). On those questions (union of the R1-full and base 2-shot reads, template goal, clingo with the train-selected kin rules),
official answer EM with aliases: 68.25 % without levers, 68.75 % with title anchoring, 72.0 % with the tie-break, 72.5 % with both.
Numbers measured on the questions they were tuned on are not evidence; this registration tests them on questions nobody has read.

**Test questions:** 400 further 2Wiki dev questions, 100 per type (bridge_comparison, comparison, compositional, inference), drawn with
`random.Random("q1-fresh-test-2026-11-21")` from the dev questions not among the 400 development ids, each type's ids sorted before
sampling; file `fresh_test_ids.jsonl`, sha256 38f398a53bf45597647e4aa3a16cc9699bbe28a1bf8a637abdb9f268e307bc84; overlap with the
development ids 0.

**Reads:** the same two readers as the development union, with unchanged prompts and decoding: R1-full (0-shot, its adapter) and the
untrained base Qwen3-0.6B (2-shot); union of their triples. Reader script `q1_read_v2.py` sha 5c6e9c6d… — the development reads were
made with its predecessor 17aad757…, which differs only by the in-line loop guard (a generation that ends in 3 identical blocks
stops earlier). Both pipeline arms of every hypothesis use the same reads, so the reader version cannot favour an arm. Input
`dev_fresh400.json` (sha256 49123438d02479f94a346510b74fe001bf79e9b154ceec75e12df761fad433af) holds exactly the 400 test questions,
so the reader's `--per-type 100 --seed 11` reads all of them. Queued on the GPU host behind the kit R2 jobs (`run_q1fresh.sh`, hash
check before start). No reader is changed after this registration.

**Frozen code (sha256):** `official_score.py` 7f9170e9bf5e0047a9609142ea337e0ec6089ae03bb20a938ff2f3645655368c (levers, metric; the `--per` output for the
test was added before any test read existed and reproduces the development numbers exactly — previous hash d6b4e32e…),
`goal_templates.py` 7f457a63f5866fb39f526499a76eb82dee84987285f58c0266433547fbf178e6, `q1_oracle.py`
4cf9cd5865412d949b6e49fcf030f4703640a6fab3565decb334bf2f3578a52d. The McNemar test runs on per-question results of these.

**Pipeline (fixed):** question → goal by the train-induced templates (`goal_templates.py`, attribute union on, slot guard off, span
resolve on), clingo with the kin rules selected on train (`kin_selected.jsonl`), typed word senses (`denote2.jsonl`), gender
(`kin_inference_g2.json`) — exactly as for the development 67.5 %.

**Levers (code frozen in `official_score.py`, sha256 recorded with the result):**
- *tie-break:* when the pipeline derives several values and the shortest (by normalised length) is contained in every other
  (normalised), the answer is the shortest; otherwise unchanged.
- *title anchoring:* a fact read from the paragraph titled T whose subject s differs from T becomes a fact about T when s and T share a
  name token outside any "of …" phrase (≥ 3 letters, not in the fixed list of titles/particles) and their number/roman-numeral tokens
  agree.

**Metric:** official 2Wiki answer EM with aliases — `2wikimultihop_evaluate_v1.1.py` semantics: maximum over the gold string and the
aliases and demonyms of `answer_id` from `id_aliases.json`, SQuAD normalisation. A question without a single derived value scores as
the empty prediction. Reported next to it: our own EM (gold string only) and official F1.

**Hypotheses (unit = question, n = 400, one-sided exact McNemar on the discordant pairs, α 0.05):**
- **H-L1 (primary):** pipeline with both levers > pipeline without levers.
- **H-L2:** tie-break alone > no levers.
- Descriptive: title anchoring alone vs no levers, per type; questions lost by each lever (listed).

**Decision:** If H-L1 holds, both levers become part of the Q1 pipeline and every later Q1 number is reported with them (and once
without, for continuity). If it fails, the levers stay out and the development gain is reported as overfitted to the development
errors.
**Named limits:** one dataset, one reader union; the alias file is noisy (e.g. Q16 lists a film title); the levers are heuristics of
string form, not of meaning; the development analysis also showed that the remaining chain errors are mostly entity linking
(containment merges "Tiberius" with "Tiberius Claudius Nero"; Jaccard separates "ab"/"ap" spellings) and unread mother/spouse facts —
neither lever addresses those.
