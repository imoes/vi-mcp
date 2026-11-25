# A2 amendment 2 (19.11.2026 ~16:40 CET)
popper_bench.py kept every solved answer set in an unbounded dict; on tasks with ~10^5 listed examples (iggp-gt-chicken-goal) each
process passed the 6 GB cap and was killed (5 of 5 seeds, exit 137). Change: the solver cache is a 16-entry LRU (gp2 keeps its own score
cache; the solver cache only spares re-solving one program for each of its 20 cases); the final statistics re-solve the best program.
Equivalence check before relying on it: three finished runs (andersen s0, iggp-attrition-next-score s3, iggp-coins-next-cell s0) rerun
with the new file — solved, evals, first and smallest solution, best training program and statistics identical; only the wall-clock
'seconds' inside first_solution differs. Runs started after ~16:35 CET use the new file. The 5 killed gt-chicken runs are rerun.
popper_bench_v1.py is the previous version (kept).
