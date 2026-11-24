# PREREG Z11-1, deviation 2: less memory for arm KR, same numbers

Date: 22.11.2026, 18:00–18:05 UTC (`date -u`). It changes no arm, parameter, question, rubric or hypothesis. It changes the
runner `scripts/z11/z11.py` after deviation 1 (commit eec2acb).

## What happened

- With deviation 1, arm R answered all 60 probe questions (17:09–17:37 UTC; 0 budget hits).
- Arm KR wrote 8 answers (1 budget hit) and was then killed by the 6 GB limit (exit 137, 18:00:04 UTC) on probe question 9. Its
  prompt with three documents is 5,521 tokens. The probe's RAG prompts are 1,234–6,390 tokens long (median 3,171).
- KR needs everything R needs plus the token store. The store's key matrix is 1.08 GB of float32 (263,273 × 1,024).

## The change

1. **Key state by hook.** The generator reads the key state from the output of the model's final norm through a forward hook
   and no longer asks for the hidden states of all 29 layers. Checked: the hook output is bitwise equal to
   `hidden_states[-1]` at the last position, after the prefill and after one decoding step (`torch.equal`).
2. **Memory-mapped keys.** `Memory` writes the key matrix once per store revision to a file next to the store
   (`z11_keys_rev2558_263273x1024.f32`) and maps it copy-on-write. The values are the same float32 numbers. The pages are file
   cache that the kernel can reclaim, not anonymous memory counted against the limit.

## Check (before KR resumed)

The fixed script answered 2 K and 3 KR probe questions again (the first ones with finish `stop` and a short answer). All 5 texts
and their nearest documents are identical to the stored answers (18:02–18:04 UTC; files `check_dev2/`). The 8 KR answers
already written are kept. KR resumes at question 9 (18:05 UTC).

## Consequence

The secondary set (A1) uses this script for all arms.
