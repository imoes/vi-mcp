# G8c-0 — oracle ceiling for a static per-task operator prior (protocol, 19.11.2026, written before any measured run)

Motivation: independent review 1 of the G8c draft (REVIEW_1_summary.md), finding 4 (iii) and 12. Before any proposer is built: can a
STATIC per-task operator prior speed gp2 up at all? An oracle knows the true effective operators of each task.

Tasks: 30 dreams (dreams.json, seeded, 10 each with k = 1, 2, 3 effective edits of a mapped library block, on a blind task's vocabulary
and world generator; kept only if not equivalent to the unmodified block on verify + stress worlds; drop reasons counted).
Arms U (uniform, gp2 unchanged), O (oracle 0.8/0.2), P (another dream's operators, derangement per seed), M (mean of all oracle priors).
Identical start set per (dream, seed) in every arm. Seeds 0, 1, 2. Budget 15,000 evaluations after the start phase. 360 runs.
Outcome O2 (censored 15,001); pairs with a start-phase solution are undefined in every arm alike (identical starts) and counted.

Decision rule (fixed now):
- The ceiling PASSES iff (a) the median over dreams of the per-dream ratio median O2(U) / median O2(O) is >= 1.5, and (b) O beats P and
  O beats M on O2 (statistic of G8b-1: dream = unit, mean rank differences, 10,000 sign flips, each two-sided p < 0.05 — a conjunction,
  no Holm). Dreams with all arms censored are excluded and counted.
- PASS -> a static proposer is worth building (G8c v2 with the review's fixes). FAIL -> a static per-task prior is abandoned; the
  proposer must be conditioned on the candidate program (next design, G8d), which is also closer to the user's MTP idea.
- Reported regardless: per k, per operator in the oracle set, the clone rate (no-op children) is not measured here.
Limits: dreams come from the same library and gp2's own operators — this is a ceiling for THIS search, not for proposers in general.
