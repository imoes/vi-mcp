# G8b-1 amendment 2 (2026-11-19 ~13:00 UTC, before any aggregate outcome) — named limit of the robustness check

vi-mcp-44 showed (insight:7fdb7a6a) that big random worlds catch depth-bounded fake closures only when they contain long acyclic
chains. Measured on the 11 recursive (kind c) blind tasks, 200 big worlds each with the robustness seed: longest chain median 4,
maximum 7–9 (kitchen_vegetarian: 2). So amendment 1's check catches programs that enumerate paths up to depth ~3–6, not deeper ones.
Stated as a limit; no change to the frozen check. A positive G8b-1 result on kind-c tasks is reported together with this limit;
task-specific structured stress sets (chains of 10+, rings, tails) would be needed to remove it.
Also from vi-mcp-44: G8b-0 stored only the 10 smallest solutions per run (gp.py, sorted(...)[:10]); G8b-1 records the FIRST solution
of every run (first.json and first_solution), which is the one the robustness check re-verifies.
