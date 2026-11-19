# G9b — the G9 question with the selection fixed (pre-registration, 19.11.2026, before any G9b run)

## Why
G9 failed for one agent instance (A): the program chosen on ONE validation day (by F1) was a predictor that drifted (prev_fail_conv:
validation F1 0.159, test 0 of 75). The synthesis of G8b-0/G8b-1/G9/A2 says every failure so far was in the selection, not the search.
G9b tests that claim on G9's data: only the selection changes; the search (gp2, budget 4,000, seeds 0–2) is unchanged.

## Data (g9b_data.py, production copy of 16.11.2026, one agent instance (A), values coded, decode table local)
train < 2026-11-11 (2,875 experiences, 54 failed); validation windows 2026-11-11 (1,238 / 15) and 2026-11-12 (1,990 / 44), pooled
3,228 / 59; test >= 2026-11-13 (6,423 / 77, base rate 0.012) — identical to G9's test period.

## Selection (the same for every method)
MDL on the pooled validation = size + FN + FP (MaxSynth, Hocquette et al. AAAI 2024); "no rule" (size 0) is always a candidate
(MDL = 59); ties: smaller. GP candidates = its archive (best training fit per size). Single literal rules: size 2. Trees depth 1–6:
size = sum over positive leaves of (1 + path length). The chosen candidate of each method is read once on the test period.

## Predictions (written before the run)
- P1: with failures this rare, MDL will choose "no rule" for most methods and seeds (abstain) — the selection refuses to claim a law
  it cannot pay for.
- P2: no method that does NOT abstain fails the test gate (Wilson lower bound of precision > test base rate). A non-abstaining choice
  that fails the gate refutes "the selection was the problem" for this data.
- Success is NOT "a law found": abstaining is the expected honest answer on 54 training failures.

## Limits (named in advance)
- The test period is the same as G9's and was read once there; G9b's design was motivated by that result. A pass is weaker evidence than
  on unseen data; a clean test needs experiences after 16.11.2026 (a new production copy — the user's decision).
- One instance, 8 days of data.
