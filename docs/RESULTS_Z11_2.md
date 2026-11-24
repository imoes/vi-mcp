# Z11-2 results: forgetting and keeping knowledge the store actually holds

Status: final, scored 23.11.2026 11:18:45 UTC. Pre-registration: [PREREG_Z11_2.md](PREREG_Z11_2.md) (sha256 076b8420…) and
[addendum 1](PREREG_Z11_2_A1.md) (sha256 d68633b1…). Both were frozen before any Z11-2 answer existed. All times are UTC from
`date -u`. Nothing here changes a Z11-1 result ([RESULTS_Z11.md](RESULTS_Z11.md)).

> **Correction, 24.11.2026.** This document says E1 is "clean and local". The larger pre-registered repeat, Z11-3
> ([RESULTS_Z11_3.md](RESULTS_Z11_3.md)), did not replicate the locality: 17 of 33 kept, 51.5 % (95 % CI 33.5–69.2), against
> 24 of 26 here. The numbers below stand as measured, but "local" holds only for these 26 questions. The forget result
> replicated: 31 of 32.

## Question

Z11-1's edit test measured locality on questions the store did not answer correctly, so it measured drift among invented answers.
Z11-2 repeats the test where the store has knowledge to lose. The pool is the 52 questions that arm K answered **correctly** in
Z11-1 (8 primary, 44 secondary). They are split by document into a forget side F and a keep side Kp. The test asks whether the
store can forget F without losing Kp.

## Run

All steps ran on one CPU workstation, the one used for the Z11-1 primary, with 4 threads in a 6 GB memory scope.

| Step | UTC | Result |
|---|---|---|
| Split (`z11_2_split.json`, sha256 69b16d70…) | 08:15:57 | 26 F, 26 Kp |
| Weights hash before | 10:13:03–10:13:09 | 18353784… |
| K before answers, 52 questions | 10:13:09–10:30:02 | 52/52 |
| Eligibility | 10:30:03 | 52 eligible, 0 excluded for host difference |
| E1 forget, then K answers from the copy | 10:32:28–10:49:33 | revision 2558 → 2728, 170 sources, 247,275 live entries |
| E2 forget, then K answers from the copy | 10:49:33–11:06:44 | revision 2558 → 2982, 424 sources, 221,277 live entries |
| Restore: K answers F from the unedited store | 11:06:44–11:14:56 | 26/26 |
| Weights hash after | 11:14:56–11:15:02 | 18353784… |

- **Host check.** Every before answer on the run host is text-identical to the answer Z11-1's judges graded correct. That includes
  the 44 secondary answers, which were produced on a rented host.
- **The two variants.**
  - E1 forgets F's 26 documents.
  - E2 forgets them plus the documents that supplied F's before answers (nearest neighbours), 64 documents in all. Two Kp
    questions collide with those documents. They are graded but not counted for E2, so E2 has 24 Kp.
- **Edits on copies.** Each edit ran on a hardlink copy of the store. Each copy was deleted as soon as its 52 answers existed
  (addendum 1), at 10:49:33 and 11:06:44, with a disk reading before and after. The unedited store's manifest is unchanged.

## Judging

The 52 questions were packed into 3 blocks of text wrapped at 180 characters.
- **Blinding.** Each question shows its before, E1 and E2 answers in an order seeded with `"z11-2:judge:" + id`. The key was
  kept in `judge_z11_2_KEY.jsonl` (sha256 1951e357…).
- **Judges.** Three fresh subagents each graded one block, with Z11-1's judge prompt and rubric unchanged. The only addition was
  one line describing the text layout.
- **Opening the key.** The key was opened after all 52 questions were graded. The grade files' sha256 are 95714b1a…, 762b6fcf…
  and 1c223edf….

## Result

| Variant | Forget: F graded wrong (≥ 80 %) | Locality: Kp kept (≥ 90 %) | Restore | Weights | Passes |
|---|---|---|---|---|---|
| E1 | 25/26 = **96.2 %** (95 % CI 80.4–99.9) | 24/26 = **92.3 %** (95 % CI 74.9–99.1) | 26/26 | identical | **yes, H4 holds** |
| E2 | 26/26 = **100 %** (95 % CI 86.8–100) | 20/24 = **83.3 %** (95 % CI 62.6–95.3) | 26/26 | identical | **no, H5 fails** (locality) |

The intervals are Clopper–Pearson. As pre-registered, the thresholds are point criteria, not tests against a null. With 26 and
24 questions per side, every interval reaches below its threshold.

### Details

- **Kp text identity.** E1: 16 of 26 Kp answers are text-identical. Of the 10 that changed, 8 are graded correct. E2: 10 of 24
  are identical, and 10 of the 14 changed ones are graded correct.
- **Forget with no text left.** No F answer is text-identical to its before answer, in either variant.
- **The E1 answer that survived.** The one F answer still correct after E1 now draws its answer mainly from another document.
  That document was not forgotten in E1. Before the edit it was the second-nearest source of the same answer, by neighbour
  counts over the generated tokens (`nearest_documents`).
  - E2 also forgets that document, and the answer turns wrong there.
  - This observes directly what Z11-1 could only state as a hypothesis: a fact survives through another document's entries.
    A forget by source works as designed, and forgetting a fact means forgetting every source that carries it.
- **What E2's wider forget costs.** Locality drops from 92.3 % to 83.3 %.
  - Two Kp answers turn from correct to wrong.
  - One turns from correct to partial. It does so in E1 too.
  - One was graded partial before and stays partial (see "Judge check").
  - E2 removes 64 of 500 documents (12.8 %), against 26 (5.2 %) for E1.
- **Class "base knows"** (addendum 1, descriptive). One F question belongs to it: the base model was graded correct on it in
  Z11-1. Its after answer is graded wrong in both variants. The forget share without the class is therefore 24/25 = 96 % for E1
  and 25/25 = 100 % for E2, the same as with it.

### Judge check

This pass graded 50 of the 52 before answers correct and 2 partial. Both partial ones are Kp questions, and Z11-1's judges had
graded both correct. That is a judge disagreement on 2 of 52 (3.8 %).
- One of the two kept its text in both edits, so it counts as kept.
- The other changed its text. It is partial before and after, so under the pre-registered rule (identical text, or changed and
  graded correct) it counts as not kept, in E1 and in E2.
- Counting it as kept, because its grade did not drop, gives E1 25/26 = 96.2 % and E2 21/24 = 87.5 %. Neither verdict changes.

## Reading

- **On questions the store answers correctly, a forget by document is clean and local (H4).**
  - 25 of 26 forgotten answers are wrong afterwards, and 24 of 26 kept answers are kept.
  - The frozen weights are unchanged, and the snapshot restores every answer exactly.
  - Z11-1's edit test failed on locality (56.5 %). The cause was the measure: it counted drift among wrong answers, not lost
    knowledge.
- **A broader forget is cleaner but not local enough (H5).** Removing the neighbour documents too makes the forget complete (26
  of 26). It also takes knowledge that Kp questions need. The store is shared between documents, and its neighbours are not
  fact boundaries.
- **What the next design needs.** Forget by fact: find every source whose entries carry the fact, for example by the
  neighbours of a correct answer. Then measure the locality cost of each extra source, instead of removing every neighbour
  document wholesale.
- **Compared with TOFU** (arXiv 2401.06121, "none of the baselines we consider show effective unlearning"):
  - The store forget needs no gradient step, and the snapshot undoes it exactly.
  - This is **not** a like-for-like comparison. TOFU's models hold the knowledge in their weights. In E1 it sits in removable
    store entries.

## Named limits

- n = 26 per side. The 95 % intervals are wide, and every lower bound is below its threshold.
- One model family judges: Claude subagents, the same family as the session that ran the experiment. Judge disagreement with
  Z11-1 on the before answers was 2 of 52.
- The judges flagged invented hosts inconsistently. Some counted host names in cited source lines and others did not. That flag
  is not a Z11-2 measure.
- The pool holds only questions K answered correctly in Z11-1. The results say nothing about facts the store answers partially.
- One model (Qwen3-0.6B), one store (263,273 entries from 500 documents) and one run host.
