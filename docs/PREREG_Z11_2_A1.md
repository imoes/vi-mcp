# PREREG Z11-2, addendum 1: the descriptive class "base knows", and store copies deleted early

Date: 23.11.2026, frozen with the sha256 in `PREREG_Z11_2_A1.sha256` before any edit is applied. Times are UTC (`date -u`).

**State when this was written:**
- The split exists (`z11_2_split.json`, sha256 69b16d70…, 08:15:57 UTC).
- No Z11-2 before answer and no after answer existed.
- Amendment 2 of Z11-1 (`tune_kr`) was running.

This addendum changes no question, split, variant, threshold or hypothesis of [PREREG_Z11_2.md](PREREG_Z11_2.md). H4 and H5 are
decided exactly as preregistered, on all eligible F questions.

## 1. Descriptive class "base knows"

**Definition.** An F question belongs to the class "base knows" if arm B (the base model without the store) was graded **correct**
(strict) on it in Z11-1. The grades come from the same blind grade files as the pool: `judge_probe` for the primary and
`secondary/judge_secondary` for the secondary set.

**Why.** A forget in the store removes only the store's contribution. Knowledge the base model has in its weights cannot be
forgotten this way, so an F answer can stay correct after a perfect store edit.
- TOFU (Maini et al., arXiv 2401.06121) uses fictitious authors for exactly this reason: the knowledge to be unlearned exists only
  in the fine-tuning data, not in pretraining.
- TOFU compares an unlearned model with a reference model trained only on the retain set. In Z11-2 the reference corresponds to
  the base model with a store that never held F's documents. For E1, the edited store *is* that reference, because a store forget
  is exact by construction. What remains in an E1 answer comes from the weights or from other documents. E2 also removes the
  documents that supplied F's answers.

**Counted before any edit** (Z11-1 grades of arm B on the 52 pool questions, computed at 08:22 UTC):

| Side | questions | B correct | B partial | B wrong |
|---|---|---|---|---|
| F | 26 | 1 | 0 | 25 |
| Kp | 26 | 1 | 4 | 21 |

**Reported per variant**, in addition to the preregistered measures:
- the forget share (graded wrong) on all eligible F, which is the preregistered criterion;
- the forget share on the eligible F **without** the class "base knows";
- the grades of each class member, named.

These two numbers are descriptive. Neither of them decides H4 or H5.

## 2. Store copies deleted as soon as their answers exist (disk)

The workstation's `/home` stood at 89 % on 23.11.2026 08:22 UTC (`df -B1 /home`: 16,687,669,248 bytes available). The copies are handled as
follows:
- `store_e1` is deleted as soon as `z11_2_answers_E1.jsonl` holds every eligible F and Kp question.
- `store_e2` is deleted as soon as `z11_2_answers_E2.jsonl` does the same.
- Both copies are gone by 23:00 UTC on 23.11.2026 in any case, even if judging or scoring has not finished.

Only the answers, the forget reports (`z11_2_forget_E1.json`, `z11_2_forget_E2.json`) and the hashes are kept.

Neither judging nor scoring reads the copies, and the restore check reads `store_qa`, so no preregistered measure changes. Each
deletion is logged with a `df -B1 /home` reading.

**Published copy (23.11.2026).** One internal host name is replaced by a neutral description in 1 place (public-repository rule). The frozen original (sha256 d68633b1eab005a581e4dd73d1d789c64890a3a66d461e485464639d83392890, the value in PREREG_Z11_2_A1.sha256) is kept privately; this published file therefore does not match that hash.
