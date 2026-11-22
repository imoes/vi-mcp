# PREREG Z11-1, deviation 3: the secondary set and amendment 2 run on a rented CPU host

Date: 22.11.2026, committed at 22:08:47 UTC (`date -u`). The runs started at 22:07:43 UTC. No answer of the secondary set and
no amendment-2 number was known when this was written. It changes no arm, parameter, question, rubric or hypothesis.

## What differs from the primary

| | Primary (60 probe questions) | Secondary set (297) and amendment 2 |
|---|---|---|
| Host | CPU workstation, AMD Ryzen 9 7950X3D | rented CPU pod, AMD EPYC 9655P, 32 vCPU, 64 GB |
| Threads per process | 4 | 2 (answers); 4 (tune_kr, KR\*) |
| Python | 3.12.3 | 3.12.16 |
| torch / transformers / peft / numpy | 2.15.0+cpu / 5.24.0 / 0.22.0 / 2.5.5 | identical |
| Script | `scripts/z11/z11.py` (deviation-2 version) | the same file, plus `tune_kr` and arm `KRs` from amendment 2 (commit 4ee806a); the answer path is unchanged |
| Device, precision, decoding | CPU, float32, greedy, budget 2,048 | identical |

The A1 hardware clause allows a rented host under the same rules. It is named here as a deviation because the CPU and the thread
count differ. Floating-point reductions can then differ in the last bits.

## Layout

Each arm's 297 questions are split round-robin into shards: B, L and R one shard each, K three, KR eight. Each shard is answered by its
own process. Every answer depends only on its own question, and each process loads the same weights and store. The shards are merged
in question order afterwards. All five arms of the secondary set run on this one host. The amendment-2 steps (`tune_kr`, then KR\*
on the 60 probe questions) also run on this host.

## Check (before the runs)

- Inputs: the sha256 of the store manifest, adapter, training split, probe catalogue, documents, frozen parameters, validation rows
  and secondary questions on the rented host equal those on the workstation. The weights hash and the store (revision 2558, 263,273
  entries) are equal too.
- Answers: the rented host (8 threads) answered the first 3 probe questions with K, R and KR (22:06 UTC). All 9 texts are identical to
  the primary answers from the workstation (4 threads), including the 3 that reached the budget. The nearest document is also the same.
- `tune_kr` ran on 2 validation rows in a separate directory as a smoke test. Its output was discarded.

## Addendum (22:09–22:15 UTC, before any amendment-2 number)

`tune_kr` first started alongside the answer shards with 4 threads. It was stopped at 22:09 UTC after 1 of 374 rows, and nothing was
frozen. The reasons were the measured 37 s per row (about 3.8 h) and the memory peak of 54.7 of 59.6 GB. It reruns only after every
answer shard has finished, with the thread count recorded in `frozen_params_A2.json` (`source.threads`). A different thread count can
change floating-point sums. The weight is frozen before any KR\* answer exists, so it is a documented setting, not a change of a frozen
value. KR\* answers the 60 probe questions in shards, like the answer runs. If the 04:00 UTC cost cap comes first, A2 is reported as
incomplete.

## Limit

Identity is shown on 9 answers, not on all of them. If any secondary answer is later compared across hosts, a difference is reported
as a host effect, not hidden.
