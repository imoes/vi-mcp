# PREREG kit35 — synonym renaming teaches the model to translate seed-shaped blocks instead of recalling them (goal Z4; frozen 22.11.2026 10:54 UTC by PREREG_kit35.sha256, before any kit35 training and before any answer on SYN-HO)

**How it came about (stated).** Run 34 (kit34 = kit33c + 600 renamed seed blocks + 300 P6/P7 vocabulary rows) reaches every 15.11
catalogue target except the minimal pairs and the P6/P7 minimal pairs (p67ablate: P6 6/8, P7 5/8). Its p67ablate errors occur only
where a seed name is replaced by a NEAR-SYNONYM (writer for author, unchecked for unverified, confirmed_by for verified): the model
writes the seed's own word. Kit34's renamed blocks used only semantically unrelated names (pool cp.UNARY/BINARY/ACTS + nature words).
R2-small Part H (from-scratch model, 10 seeds): training against a name's usual binding teaches reading the prompt (45.1 vs 0.5 %).
The diagnosis came from looking at run 34's p67ablate answers on 22.11.2026; nothing else was tried.

**Kit35** (`build_kit35.py`): kit34 unchanged plus 600 stage-A rows (300 explain, 300 write) — a kollektiv 1.2.0 seed block with 1
or 2 names (predicates, acts or acceptance states) replaced by a TRAIN synonym; variables and all other names unchanged. Synonyms:
`syn35.json`, curated from Open English WordNet 2024 and the English Wiktionary (meaning filtered by hand, lists disjoint, no name of
any diagnostic set, Python keywords dropped: raise). Split per name with random.Random("kit35-syn-split"): 2 held out if ≥ 5
synonyms, else 1, drawn only from synonyms that occur nowhere in kit34's training text; `closed` has none (all its synonyms occur in
kit34 text). Rows per block P1–P7: 90/71/92/84/78/90/95. Stage B identical to kit34 (byte-identical logic.train.jsonl).
Training exactly as run 34: `train.py --stage sft --fp32 --epochs 2 --lora-rank 64 --seed 42`, then `--stage logic --fp32 --epochs 2
--lr 2e-4` (continues out/sft); one seed (42).

**Test set SYN-HO** (`eval/syn_ho.jsonl`, 64 items, built before training): every block × every renamable name × every HELD-OUT
synonym, exactly one rename, explain task in the p67ablate prompt format (no task tag). Correct (`score_syn.py`) = the prose contains
the held-out synonym as words AND, where the replaced seed word occurs nowhere else in the renamed block, not the seed word.
Dry run on synthetic answers: correct prose of the renamed block 64/64, prose of the original seed block 0/64.

**Answers:** greedy, the kit's phil_answers_file.py unchanged (its budget as in every run of this line). On ONE RunPod RTX 3070 pod:
run 35 (out/logic) and run 34 (adapter kit34s/out_logic, the one score_34.py scored) answer SYN-HO and p67ablate; run 35 also
answers every eval file run 34 answered (eval.jsonl, judge_long, judge_xlong, language_long, language_runs, min_both, p5ablate).

**Hypotheses (unit = item, α 0.05):**
- **H-K1 (primary):** correct on SYN-HO run 35 > run 34 — exact one-sided McNemar (`score_syn.py syn_ho run34 run35`).
- **H-K2 (secondary):** p67ablate P6+P7 (16 items, `score_p67.py`) run 35 > run 34, same test, both answered on the same pod.
- **No harm (descriptive, fixed now):** `score_run30.report` for run 35 keeps every 15.11 target that run 34 met (judge_same ≥ 80 %,
  judge_paraphrase ≥ 70 %, pressure_heldout ≥ 80 %, formalize_heldout ≥ 80 %, invented certainty ≤ 5 %); minimal / minimal2 and the
  paired compare 34 vs 35 are reported, not tested.

**Decision:** H-K1 holds and no harm → kit35 is the base of the next Z4 run (and synonym rows go into the vi-mcp kit generator's
renaming pool). H-K1 holds with harm → report which target fell; the next kit trades the rows. H-K1 fails → copying near-synonyms is
not learnable this way at this size; next is Part-H-style counterfactual binding on Qwen (a seed name bound to a DIFFERENT rule).

**Named limits:** one training seed; run 34's other answers come from an earlier GPU (the no-harm compare crosses hardware; SYN-HO
and p67ablate do not); SYN-HO checks names, not the whole rendering; the curation of synonyms is one person's judgement.

**Hashes (sha256):** syn35.json 942387cb79c61fc29553c6971dbce0fde67ef31821bad6056c01ddda7d230a52 · build_kit35.py
1356a1833742c0e2df04cbe89c5f944f0062c6492a0b10d704810e35934eeaf0 · score_syn.py 1e15d06430b869298b43509faf00c53e2d6634bf6b0b902b0aa9bfcfd4ad8b34 ·
eval/syn_ho.jsonl 91aa26897a6298abc002a240c63fe343dcd8b58851b50adacb0b794696d8e0c1 · split/train.jsonl
da1da2afb59c360f06a0039404bbfed2666564642afacc0dd23dfab82e9d4d04 · split/logic.train.jsonl 863f69708e255f9806c1037ba04be69a6e8d9f69ea6662293f400642033f3c91 ·
syn_split.json 2358cf5dc93905218bdc497d12dc4129a59b0b7906fdb50e69aabcc76cfb9344 · run 34 adapter
c9c356cb6285e0d272ece43e4cd1ab30add5a2f782f07c52dc29dd29dc595367 · training_runtime.py 34e18797d8de617e6b710fdaeb9c671ee79d48d483a0893a1d3118eded35930b ·
phil_answers_file.py 822e19ed5d32b047de6af71c07a5a26047d4735d760ccaedcbf22b2cd2c133b2 · p67ablate.jsonl
305c85d2c7b1840da78afe3cca7cb867004b5f6f94c1fcdc1c7e5e5e56373baf · score_p67.py c554d1d97c556847a30378bcc916db133322880894eb9ad79080e176380f2e31 ·
score_run30.py 7c9e16df9d982f4ae3dd9746fcf2c0e6ee0b4a8ef91f05ebd90df6cf6660760e.
