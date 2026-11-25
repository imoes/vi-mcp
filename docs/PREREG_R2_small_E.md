# PREREG R2-small Part E — do mirror worlds teach a small model to choose predicates from the data? (fixed 21.11.2026 ~09:00 UTC, before any Part E data were trained on)

**How it came about (stated, not hidden):** kit R2 run 1 (Qwen3-0.6B, one SFT epoch on teacher rules) writes the right rule shape but
chooses the predicates essentially at random: held-in way-A tasks 17/300 exact; with clingo re-binding the predicates of the model's
shape 145/300 (exploratory). SLR (Helff et al., arXiv 2506.15787) trains its easiest curriculum levels on **mirror** examples: "For each
positive example, a corresponding 'mirror' negative is created by randomly altering the rule-specific atoms" — the data differ only where
the rule looks. Rule "small model first": the lever is tested on the from-scratch tiny model before any Qwen kit uses it.

**Data** (generated on the CPU host before training, hashes in `expected_e.sha256`):
- *indep* tasks = `gen_rules.py` as in kit R2 (two independent random worlds), the six trained families chain2, inverse, disj, filter,
  neg, recursion.
- *mirror* tasks = `gen_rules_mirror.py`: world 2 is a copy of world 1 in which only atoms of the target program's own predicates are
  altered (each removed with p 0.35, absent ones added with p 0.35·density); all other predicates are identical in both worlds; the
  positives must differ between the worlds; the same triviality and minimality checks as gen_rules.py.
- Prompt format, target format (`t(X, Y) <= …`, one rule per line) and checker (clingo: the rules derive exactly the positives of both
  worlds, closed world) are identical for both kinds.

**Arms (the only difference is the training set; 12,000 tasks each, 2,000 per family):**
- **indep:** 12,000 indep tasks.
- **mix:** 6,000 indep + 6,000 mirror tasks (the same 6,000 indep tasks as half of the indep arm), shuffled.

**Model and training:** H13 `gpt.py` (pre-LN, RoPE, d 128, 4 layers, 4 heads), AdamW 2e-3, cosine, batch 32, 20,000 steps, greedy,
10 seeds per arm (0–9), tokenizer as R2-small Part C (`\d+` included). Trainer `r2train_e.py` = `r2train_d.py` with arms indep/mix and a
third evaluation set.

**Test sets (never trained):** testI = 300 indep tasks of the six families (`rules_test_heldin.jsonl`, the kit R2 set); testM = 300
mirror tasks of the six families (new seed); testD = 200 indep tasks of the never-trained families chain3 and join
(`rules_test_heldout.jsonl`).

**Hypotheses (unit = seed, one-sided exact Mann-Whitney U over 10 + 10 seeds, α 0.05):**
- **H-E1 (primary):** testI exact (realistic independent worlds) mix > indep — training on contrastive mirror worlds transfers to
  choosing predicates from independent data.
- **H-E2:** testM exact mix > indep.
- Descriptive: per-family exact rates; shape-exact (`shape_bind.py`: the answer's shape with clingo re-binding the predicates) on testI —
  if shape-exact is high and exact low in both arms, the arms differ only in predicate choice; testD exact (expected ≈ 0 in both).

**Decision:** If H-E1 holds, the next Qwen kit (R3) adds mirror tasks to way A (half of the way-A rows), with the same test sets. If
only H-E2 holds, mirror training does not transfer and the predicate choice stays with clingo (shape proposal + binding). If neither
holds, the tiny model cannot use the contrast either; R3 is designed without it.
**Named limits:** one tiny model size; synthetic worlds of 7 entities and 4 binary + 2 unary predicates; testD is expected at 0 and is
not tested; runs on the AMD host after H13 g3 (ROCm), not the GPU type of Parts B–D.
