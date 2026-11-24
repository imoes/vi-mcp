# PREREG Z11-2: the edit test on knowledge the store actually holds

Date: 23.11.2026, frozen with the sha256 in `PREREG_Z11_2.sha256` before any Z11-2 answer exists. Times are UTC from `date -u`.

## Why

The Z11-1 edit test (PREREG_Z11, "Edit test") failed:
- forget: 11/14 graded wrong;
- locality: 26/46 textually identical.

The exploratory pass A3 showed what was wrong with the measurement. Outside F, the store had no correct knowledge to lose, so
textual identity measured drift among invented answers. Z11-2 asks the question the edit test meant to ask:

> When the store answers a question correctly, can a forget remove that knowledge without training, and without harming other
> questions the store also answers correctly?

Nothing in Z11-2 changes a Z11-1 result.

## Fixed setup (identical to Z11-1)

The following are unchanged from Z11-1:
- the base model, revision and float32 CPU path;
- `scripts/z11/z11.py answer --arm K` (the deviation-2 generator), with greedy decoding and a decoding budget of 2,048;
- `frozen_params.json`: k 32, temperature 476.7373046875, weight 0.8;
- the store `store_qa` at revision 2558 (263,273 entries).

The store's manifest sha256 is recorded before the first step, and it must be the same after the last one.

## Question pool and split (before any Z11-2 answer)

1. **Pool.** The pool holds every question on which arm K was graded **correct** (strict) by the blind judges of Z11-1:
   - the primary probe (`judge_probe`, 8 questions);
   - the secondary set (`secondary/judge_secondary`, 44 questions).

   That makes 52 questions. Partial grades are not in the pool. The sha256 of the grade and key files is recorded.
2. **Split by document.** Questions are grouped by their source document, so that all questions on one document fall into the
   same group.
   - The documents are sorted by id and shuffled with `random.Random("z11-2:split")`.
   - The first ⌈n/2⌉ documents form the forget side F, and the rest form the keep side Kp.
   - The split is written to `z11_2_split.json` with its sha256 before the first answer.
3. **Eligibility (host check).** On the run host, K answers every pool question from the unedited store. This is the *before*
   answer.
   - A question is eligible only if its before answer is textually identical to the answer the Z11-1 judges graded correct.
   - Every excluded question is named with the reason "host difference". The secondary answers came from the rented host
     (deviation 3).

## Two forget variants (each applied to its own hardlink copy of the unedited store)

- **E1, forget by document.** Every store source of F's documents is forgotten, as in Z11-1.
- **E2, forget by provenance.** The forget set is F's documents plus every document in the `nearest_documents` list of an
  eligible F question's before answer. This list holds the top 3 documents of the top-1 neighbour, counted over the generated
  tokens. Every store source of these documents is forgotten.
  - A keep question whose document lies in the E2 forget set is excluded from E2's locality. It is counted and named.
  - E1 is not affected by this exclusion.

Each variant is applied to a hardlink copy of `store_qa` (`store_e1`, `store_e2`), with the `Datastore.forget` reason "Z11-2 E1"
or "Z11-2 E2". `store_qa` itself is never edited, and it serves as the restore snapshot. After an edit, K answers every eligible F
and Kp question from that variant's store.

## Measures and thresholds (fixed now)

These checks apply to each variant separately:

| Part | Criterion | Pass |
|---|---|---|
| Forget | share of eligible F questions whose after answer is graded **wrong** | ≥ 80 % |
| Locality | share of eligible Kp questions whose answer is **kept**: the after text is identical to before, or the changed text is graded **correct** | ≥ 90 % |
| Restore | the eligible F questions answered again from `store_qa` after both edits are textually identical to their before answers | 100 % |
| Weights | `weights_sha256` of the core is identical before and after | identical |

- **H4:** E1 passes all four parts.
- **H5:** E2 passes all four parts.
- Each verdict is reported with the counts and a Clopper–Pearson 95 % interval for forget and locality.
- If fewer than 15 F or 15 Kp questions are eligible for a variant, the verdict is also labelled "underpowered", and it still
  stands as measured.

Reported, not decisive:
- the forget share counted as "not correct" (wrong or partial);
- locality as textual identity only;
- for every F answer that was not graded wrong, the `nearest_documents` list after the edit;
- the grades of the before answers in the new blind pass (judge stability);
- the store size per variant (entries, sources, revision).

## Blind judging

- **Per question:** the before answer, the E1 after answer and the E2 after answer are graded pointwise (correct, partial or
  wrong), each against the reference and the source document. For a Kp question excluded from E2, the E2 answer is graded too
  but not counted.
- **Blinding:**
  - The letter order is seeded per question with `random.Random("z11-2:judge:" + id)`.
  - The key is kept in a separate file.
  - Block text is wrapped at 180 characters.
- **Judges and rubric:**
  - The judges are fresh general-purpose subagents that read only their block file.
  - They use the rubric and judge prompt of Z11-1, unchanged.
  - The key is opened only after every block is graded.

## Run host and resources

- **Host:** the Z11-1 primary workstation (AMD Ryzen 9 7950X3D, 16 CPUs). It uses the same venv and versions as the Z11-1
  primary: Python 3.12.3, torch 2.15.0+cpu, transformers 5.24.0, peft 0.22.0, numpy 2.5.5. No rented host.
- **Resource limits:**
  - One process at a time.
  - Each process runs in `systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=0 nice env OMP_NUM_THREADS=4`.
  - `free -g` must show at least 8 GB available before each step; otherwise the run waits.
- **Order:** Z11-2 starts after amendment 2 of Z11-1 (`tune_kr`, then KR\*) has finished on the same host.
- **Disk:**
  - The store copies are hardlinks; the key cache is rebuilt per copy, about 1.1 GB each.
  - A guard refuses each step below 3 GiB free.
  - The copies and their caches are deleted after the restore check.
- **Estimate:** about 52 before + 52 E1 + 52 E2 + 26 restore ≈ 180 K answers. On that workstation, Z11-1 K took 3,226 s for 60 answers, so
  this is about 2.7 h. This is a projection, not a measurement.
- **Script:** `scripts/z11/edit2.py` (pool, split, before, forget, compare, judgepack, score). It is committed before the first
  run, and its sha256 goes into `run_times_z11_2.log`.

## Named limits

- The pool is small: about 26 questions per side before the eligibility check.
- The forget threshold of 80 % and the locality threshold of 90 % are point criteria, not tests against a null.
- E2's forget set depends on the before answers. It is fixed before any after answer exists.
- The same model family judges as in Z11-1.
- The secondary questions carry the A1 leakage note: the kNN parameters were tuned on rows of the same documents.

**Published copy (23.11.2026).** One internal host name is replaced by a neutral description in 2 places (public-repository rule). The frozen original (sha256 076b8420737abfc1900f5560f7d8900160a23f96a8d6f3c71a16396eb0144115, the value in PREREG_Z11_2.sha256) is kept privately; this published file therefore does not match that hash.
