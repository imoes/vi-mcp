# G8b-1 amendment 1 (2026-11-19 ~12:35 UTC) — written BEFORE any aggregate G8b-1 outcome was computed (score1.py not yet run;
# ~1,050 of 1,320 runs exist; only per-run progress counts were looked at)

Reason: the Popper baseline (vi-mcp-44, VI insight:343a724e) showed that the G8b-0 verifier of dependency_cycle (113 domain worlds
+ 200 stress worlds) accepts non-general programs: three Popper programs passed it and still flag nodes on acyclic chains of 6–10
packages. The blind tasks use the same kind of verifier (exhaustive small domain + 200 big stress worlds), so a "solved" in G8b-1 may
be too lenient as well.

Added (secondary, does not replace the primary analysis of prereg_G8b1.md):
- ROBUSTNESS CHECK: every first verified solution of every G8b-1 run is re-checked against the task's REFERENCE on 1,000 NEW big
  worlds per task (blind_tasks.world_text(name, random.Random(f"{name}:robust:1"), big=True)), the same 1,000 for every arm and seed.
  A solution failing any of them is "solved but not robust".
- Reported per arm: robust solved share, non-robust share; and H1–H3 recomputed with non-robust solutions counted as unsolved
  (censored at the budget) — a sensitivity analysis, labelled as such, no claim beyond "the primary result does / does not survive".
