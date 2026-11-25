# A2 amendment 1 (19.11.2026 ~15:40 CET, after the workstation incident; no GP result was looked at before writing it)
The GP arm with 8 parallel processes drove the workstation into swap (one popper_bench.py at 10.7–17.7 GB RSS on a task with ~86,000
background facts; load 342); all runs were paused and then killed. 40 GP runs had finished; killed runs left no result and are rerun.
Changes for the remaining GP runs (run_a2_gp_capped.sh):
- tasks with <= 20,000 background facts: 3 parallel, each capped at 6 GB; the 7 large tasks (trains1-4, noisy-wn18rr1/3,
  iggp-hextforthree-next-control): one at a time, capped at 16 GB;
- a run killed at its cap counts as "not solved, resource limit" (recorded in run_a2_gp.exits), never silently dropped;
- the Popper arm (complete, 8 parallel, uncapped) is not rerun.
Consequence named in advance: the GP arm runs under less CPU contention than the Popper arm did, which favours GP slightly under the
600 s wall clock; the report states it next to every time and solved count.
