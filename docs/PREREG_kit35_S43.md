# PREREG kit35-S43 (step 0 of kit36): a second training seed of run 35

Date: 25.11.2026. Frozen with the sha256 in `PREREG_kit35_S43.sha256` **before any step-0 training starts**. All times are UTC from
`date -u`. Decision: the user, relayed by the coordinator at 08:48:36 UTC ("Step 0 + kit36"); GPU slot on the RTX 3070 host today
13:30 UTC, hard end 21:00 UTC.

## Why

FINETUNING_PAPER §5.34 (built-for 9681fc5) diagnosed run 35's pressure-facts drop as one held-out phrasing. "Speaking for claim sN:
member X, source O." is written as `author(sN, X)` when X is also sN's author. Run 34 has 110/110 such sentences right, run 35 101/110
(only-34 9, only-35 0); counting the non-self cases too, 12:1. Open point 13 requires a second training seed of run 35 before kit35
becomes a base. The question is whether this error belongs to kit35, which would make kit36's contrast rows the right lever, or to
training seed 42.

## What runs

- **Kit:** kit35 rebuilt on 25.11.2026 (vi-mcp-sr bfe3ce0, `research/philosophy/kit35/RECOVERY.md`). Stage A `split/train.jsonl` sha256
  da1da2af…5d4 is exactly the `dataset_sha256` in run 35's train.log. Stage B `split/logic.train.jsonl` is kit34's file (863f6970…).
- **Training:** as run 35, read from run 35's `training_args.bin` and `adapter_config.json`: LoRA rank 64 (alpha 128, dropout 0.05,
  all linear), fp32, batch 1, 2 epochs, linear schedule, adamw_torch_fused, learning rate 2e-4 in both stages.
  - The **only** change is `--seed 43` in both stages.
  - Commands: `train.py --stage sft --fp32 --lora-rank 64 --epochs 2 --lr 2e-4 --seed 43`, then
    `train.py --stage logic --fp32 --lora-rank 64 --epochs 2 --lr 2e-4 --seed 43`. The logic stage continues out/sft, as the kit
    defaults.
- **Answers:** `phil_answers_file.py out/logic eval/eval_step0.jsonl eval/step0_answers.jsonl`, greedy with thinking off and the kit's
  frozen 4,096-token budget.
  - `eval_step0.jsonl` (sha256 6dbb1ebb…) is the 90 items of judge_paraphrase (40), pressure_heldout (30) and formalize_heldout (20)
    from the kit's `eval/eval.jsonl`, unchanged. Only these sets contain the phrasing.
  - The full 427-item answer pass (5,075 s on this GPU for kit34) does not fit the slot and is not part of step 0.
- **Host:** the RTX 3070 host, own container `claude-ft-bench:cuda-gcc`, `HF_HUB_OFFLINE=1`. The vision llama-server is stopped for the
  run and restarted in the EXIT trap, then probed with a real request. Start and probe lines go to the coordinator.

## Measure and decision (fixed now)

The scorer is `research/philosophy/kit35/step0_score.py` (sha256 in the .sha256 file). Before this registration it reproduced the
diagnosis exactly on runs 34/35 (for/self 110 vs 101; for/other 178 vs 176; against 92/92 both).

- **Primary count:** "Speaking for" sentences where X is sN's author, n = 110. Run 35 seed 43's correct lines, against run 35's 101
  and run 34's 110.
  - **≤ 105/110** (at least 5 errors): the error replicates with a second seed, so it belongs to kit35. kit36 group A (member-cue
    contrast pairs) targets a real kit effect.
  - **≥ 109/110** (at most 1 error): the error does not replicate. Run 35's 9 are within seed variation, and kit36's H-36a would test
    a seed artefact; the kit36 prereg must then say so and adjust.
  - **106–108:** undecided; reported as such.
- **Reported, deciding nothing:**
  - the for/other and against cells and the author-error counts;
  - exact fact lists of the three sets for runs 34, 35 and 35-s43: the answer's "[i] fact" lines, without unknown lines, equal the
    item's gold facts as a sorted list (the §5.34 method). The frozen no-harm scorer `score_run30.py` (sha 7c9e16df…) was in the
    same deleted scratchpad as `rule_prose.py`, has not been recovered, and is not used. World verdicts are therefore not reported
    in step 0;
  - training time and loss.

## Limits

- One more seed, not three.
- The answer set is the 90 items that contain the phrasing, not the whole no-harm catalogue.
- Run 35 trained on a rented RTX 3070, run 35-s43 trains on our own RTX 3070. Same GPU type; a hardware effect cannot be told apart
  from the seed effect. Run 23 measured +4/−2 for the same kit and seed on two GPUs (FINETUNING_PAPER §7).
