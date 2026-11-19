# A2 — our rule search (gp2) on Popper's own example tasks (protocol, fixed before any full run, 19.11.2026)

## Question
Does the symbolic-regression search that recovered 5 of 6 mechanisms on our own tasks (G8b-0) hold up on tasks someone else wrote
for an established ILP system? Popper's example tasks are Popper's home turf (bias files written for Popper); a result there is
external evidence in both directions.

## Tasks
Popper v5.0.1 (commit 578a4e26) `examples/`: 51 directories. Usable for gp2: the 32 that `popper_bench.py --list` marks OK
(flat facts in bk.pl; the IGGP idiom `body_pred(P,1) :- constant(P,_)` expanded over constant/2). Skipped, 19, each with its reason in
`list.txt`: synthesis-* (lists), 1d_* and robots-* (lists), noisy-alzheimer-* (quoted atoms), noisy-dropk-20 (lists). The skipped
tasks are reported as "not expressible as flat facts", never as failures or wins.

## Arms
- **GP:** `popper_bench.py` — gp2 unchanged (operators, lexicase, archive, 25 generations after the first solution); cases = 20
  stratified chunks of the listed examples; scored on listed examples only (Popper's semantics). No Popper bias limits given.
  Seeds 0–4, 600 s wall clock each.
- **Popper:** the shipped bias unchanged, `--timeout 600`, `--noisy` for the noisy-* tasks (Popper's intended mode), container
  popper-g8b:5.0.1. 3 repetitions (Popper is not deterministic). NuWLS not used (not installed).
- Not run at the same time; each arm 8 processes in parallel on the same 16-core workstation.

## Measures (per task)
1. **solved:** a program complete and consistent on ALL listed examples (P = R = 1) within 600 s — Popper prints this as
   "Precision:1.00 Recall:1.00". Share of runs per task, then tasks with ≥ 1 / majority of runs solved.
2. **size** of the returned program (literals incl. head) vs Popper's; Popper's is optimal within its bias.
3. **balanced accuracy** of the best program on all listed examples (the only measure on noisy tasks).
4. time to first solution.

## Limits (named in advance)
- No held-out test: "solved" measures fitting the listed examples, not the law. Tasks with few negatives accept nonsense programs
  (kinship-ancestor has 0 negatives — smoke test: gp2 returned `ancestor(V0,V1) <= inv1(V0) & mother(V2,V1)`). Such tasks are
  flagged (neg < 5) and reported separately.
- The original IGGP benchmark (Cropper, Evans, Law 2020) has test sets; these 16 iggp-* directories are Popper's training slices only.
  This is NOT a reproduction of the IGGP numbers (best system 40 % perfect, ILASP 86 % balanced accuracy).
- Our scoring code (popper_bench.py) is new; its smoke test (kinship-pi, kinship-ancestor, iggp-minimal-decay-next-value) passed.

## No primary hypothesis
Descriptive comparison; no p-value is claimed. Whatever the result, it is reported per task.
