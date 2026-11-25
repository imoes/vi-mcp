# PREREG G8d-1 — does a proposer conditioned on computed vectors make the rule search cheaper on new blind tasks? (frozen 21.11.2026 ~11:05 UTC by docs/PREREG_G8d1.sha256, before any run on the test tasks)

**How it came about (stated, not hidden):** plan G8d (vectors computed from the search itself, not a text embedding).
G8d-0 (development, 33 tasks): a candidate's free behaviour + exact structure (SF) predicts which single edit improves THAT parent —
within-parent AUC 0.770 vs 0.704 for the best structure-blind baseline, margin 0.066, task-bootstrap CI [0.017, 0.115]. G8d-0b: an
oracle that knows the improving edit makes the search 2.76× cheaper (median over the 12 hard development tasks; gate 1.5). The VSA
projection was not built (it would compress S, whose own gain was small). Open: does a REAL, learned SF proposer pay on tasks nobody
tuned on?

**Tasks (test, never seen by any part of the pipeline):** `blind_tasks_g8d1/blind_tasks.py`, 40 tasks, kinds a/b/c = 10/15/15,
written by a subagent that saw neither gp2, the library, the encoders, the development tasks nor any result (its AUTHOR_REPORT.md
names every file it opened); domains disjoint from the development areas. Hashes below.

**Search:** gp2 (frozen, G8b-1 hash 9789e1ee…), arm Z (no library; start set drawn with `Random("start:<task>:Z:<seed>")`, identical
for every policy), budget 15,000 evaluations after the start phase, seeds 0–9 (10 seeds as in G8b-1 and G8d-0b; the plan said 20 — reduced before the freeze for compute: measured smoke cost puts 20 seeds at ~180 CPU-h; the unit of every test is the task, seeds only smooth the task medians).

**Policies** (`gp2_arms_d1.py`; each chooses (operator, rule index) of every mutate() call, inner choices stay gp2's random draws;
every policy draws a uniform (operator, rule) with probability ε = 0.2):
- **U** uniform (gp2 itself).
- **P** static operator prior: weight = share of improving edits per operator on the development edits (Laplace), rule uniform.
- **C** conditioned: every (operator, rule) candidate of the program being mutated is scored by the frozen SF model
  (HistGradientBoosting, fitted on all development edits, `train_c.py`); drawn with weight = predicted probability.
- **Cs** control: C's scores permuted within each decision — same score values, no link to the candidate.
- **O1** oracle ceiling (descriptive only): hard-stratum tasks, seeds 0–4, run after the four main policies.
The parent's behaviour features (per-world TP/FP/FN on the current training worlds) come from an uncounted solver call — the same
numbers the search's own evaluation already produces (plan: F0 is free); counted cost is unchanged.

**Outcome:** O2 = evaluations after the start phase to the first exact solution (exact = equivalent to the reference on every
verification world; gp2's own check); a run that never solves gets 15,000 (censored); a run solved in the start phase has no O2 —
because the start set is the same for every policy, such a seed drops out for all policies alike.

**Units and strata:** a task is *eligible* if at least 5 of its 10 seeds are not solved in the start phase; its value per policy = the
median O2 over those seeds. *Hard stratum* = eligible tasks with median U O2 ≥ 300 (the G8d-0b rule).

**Hypotheses (one-sided, α 0.05):**
- **H1 (primary):** C < Cs on O2 — Wilcoxon signed-rank over the eligible tasks' medians (`scipy.stats.wilcoxon(C, Cs,
  alternative="less", zero_method="wilcox")`; tasks where both are censored drop out as zero differences).
- **H2:** C < P, same test. **H3:** C < U, same test.
- Secondary (descriptive): the three tests in the hard stratum; solved share per policy; per-task ratios Cs/C, U/C; by kind a/b/c;
  O1/U in the hard stratum; run time per policy (the model's cost in seconds).

**Convincing pattern (fixed now, from the plan):** H1 and H2 hold, C < Cs and C < P also in the hard stratum, no harm on easy tasks
(median ratio U/C ≥ 0.9 outside the hard stratum).

**Decision:** If H1 holds, the computed-vector proposer is real progress for the rule search and goes into the search (and is the
basis to compare a learned encoder against, G8d-2). If H1 fails while O1 still beats U by ≥ 1.5, the information is there but the
model does not deliver it — next is a better model/representation, not more data. If O1 also fails on these tasks, one-step guidance
does not pay at this scale and the line ends.

**Checks of the task set (before any search on it):** the author's check.py passes (every REFERENCE has exactly one answer set on
all 29,907 verification worlds and 60 random worlds per task; answer share 0.30–0.88 per task; kinds 10/15/15). Against the 33
development tasks: no shared task name, no identical reference after renaming predicates, no duplicate shape inside the new set.
Within gp2's limits (6 rules, 4 body literals, 3 helpers) except **split_ticket** (one rule with 5 body literals: reachable only through
an invented helper) — kept, because removing a task after looking at the search program would tailor the set; it is the same for every
policy. frost_alert uses an arity-3 input (gp2 handles arity 3; the development set had one).
**Plumbing check:** `gp2_arms_d1.py --policy U` on a development task (bank_fraud, seed 0) reproduces the stored G8b-1 run exactly
(search cost 174, 266 evaluations). Smoke test of P, C, Cs on development tasks bank_fraud and games_levels, seed 0 (workstation, 21.11.2026):
the first C/Cs runs crashed (the behaviour cache stored None for an unscorable program and was then indexed); fixed by caching
(number of training worlds, score). After the fix all four policies solve both tasks — search cost bank_fraud U 174, P 649, C 828,
Cs 830; games_levels U 1,824 (stored), P 4,978, C 2,297, Cs 4,718; C costs about 1.7× U per evaluation (49 vs 29 ms). Single
development seeds, no evidence for any hypothesis. No run on a test task before the freeze.

**Compute:** jobs = 40 tasks × seeds 0–9 × {U, P, C, Cs}, shuffled with `random.Random("g8d1-jobs")`, split between two CPU hosts
(about 6 and 4 parallel runs, 4 GB memory each, `nice`), then O1 on the hard stratum. A run that fails (exit ≠ 0, not a budget
end) is rerun once with the same arguments and counted; a second failure is reported per task and policy.

**Hashes (sha256):** blind_tasks_g8d1/blind_tasks.py 0aba13746edbf11af5d9681bc101f7bb1e20290eccef7f85e7150870d830382b ·
check.py 97635578d11eb781d75ff7cf22ebe5b1f44bfb93fb3a9810041aa112ec5c1c25 · AUTHOR_REPORT.md
a37ddbd4cb242db2a67eb94da083ad8384708d151d7eea02b2b88d74c2928741 · gp2_arms_d1.py 76ac5a72a7ba13004a7071f62e3d7bdf303fffcbef060105c787f8c285379c14 (after the smoke-test fix below)
· train_c.py 95f4ef20246b179eff8ddec2e6864cd8902435de742df125ef8ed4d0731e9ffa · gp2_arms.py
32e33a053035dd29793d0c301d6263adbabe52250249ec38855c24a8e7d1730b · g8d0.py 5dcf25dbd3fa5fdae90acc429bde18bdd40e6e26d48408c9701879f580752e30 ·
score_d1.py 95e2dd0799531c9291849a48641a634eeb3db9e7d541bda7d8c7e0013431adfb (the analysis above as code; dry-run on development smoke runs only) ·
gp2.py 9789e1eee001280ccc7e6569e36ca30cbcec044f399abf8110ea32627fc52699 · model_C.pkl 19b7397fd453cbafa58ccfb2d5e9fd8ceb22eeb263b2e4706856d68f62eef4c0 (83,733 rows, 5,260 improving, 31 tasks, 542 features — the G8d-0 rows exactly; 0 rows skipped by the gold-timeout guard) · environment: Python 3.12.3,
scikit-learn 1.9.1, numpy 2.5.5, clingo 5.8.3 (the G8d-0 versions), scipy 1.18.1 for the tests.

**Named limits:** one search (gp2), one task author, synthetic everyday domains; the SF model was chosen and fitted on development
tasks only; ε = 0.2 keeps every policy partly uniform; censoring at 15,000 understates differences where one policy never solves.
The solver call has a time limit (g8_eval.TIMEOUT): under heavy host load an evaluation can time out and count as unfit, so runs are
not strictly load-independent (seen 21.11.2026: a reference answer timed out while the SF model was being fitted; a rerun on the
same data had 0 such cases). Runs therefore go at moderate parallelism, and every run records its wall time; a policy-dependent
timeout rate would be reported.

## Amendment 1 (21.11.2026 ~15:05 UTC, compute only — no result read)
The second CPU host runs about 2.5× slower per run than planned (0.75 runs/min; ~17 h for its 960 jobs). A third CPU host takes the
last 400 jobs of that host's list in reverse order (8 parallel, same 4 GB limit and nice); the second host keeps working from the front
of its list; a job finished on both hosts keeps the first result by finish time, the other is counted and reported. Before starting,
the third host passed the same 9-file hash check and reproduced the development smoke runs exactly (bank_fraud seed 0: U search cost
174, C 828, as on the first host). Analysis, hypotheses and outcome definitions are unchanged.

## Amendment 2 (21.11.2026 21:02 UTC, compute only — no result read)
The first CPU host finishes its own 640 jobs; the second host has slowed to ~26 runs/h (the GPU job beside it uses CPU). Of the second
host's list, 276 jobs were neither finished on the second host (from the front) nor on the third (from the back) at 21:00 UTC. The
first host takes the middle half of these, 138 jobs in list order (`d1_jobs_hal2.txt`, sha256 254ed230…), with 4 parallel runs (its
process limit), the same runner, hash check, 4 GB limit and nice; the other two hosts keep working from their ends. The duplicate rule
of amendment 1 applies (first result by finish time kept, duplicates counted and reported). Analysis, hypotheses and outcome
definitions are unchanged.

## Amendment 3 (22.11.2026 02:01 UTC, compute only — O1 results not read)
The O1 ceiling runs (hard stratum, seeds 0–4, 80 runs, `d1_jobs_O1hard5.txt` sha256 e5d60e3c…) run slowly on the first host alone
(2 of 80 after 40 min). The second host runs the same list in reverse order (`d1_jobs_O1_rev.txt`, 6a4649a2…), the third host from its
middle (`d1_jobs_O1_mid.txt`, 25de575e…), 4 parallel runs each, same runner, hash check, limits and nice; the first host keeps its
order. Duplicate rule of amendment 1 (first finish kept, duplicates counted). Analysis and decision rule unchanged.
