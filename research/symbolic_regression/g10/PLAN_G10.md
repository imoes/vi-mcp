# G10 — vector-symbolic binding as the representation of the rule search (plan draft, 19.11.2026, for independent review)

## Why
User, 19.11.2026: "Sprachmodelle binden Attribute über Vektoren an Entitäten ist genau der Ansatz, um unsere symbolische Regression zu
verwirklichen." Language models bind attributes to entities with close 'binding ID' vectors (Feng & Steinhardt, arXiv 2310.17191);
vector symbolic architectures (VSA) do the same explicitly: role⊗filler binding and superposition (Kleyko et al. arXiv 2111.06077).
Our results so far: the library helps only when a block fits unchanged (G8b-1 H2), not as a seed for modification (H1, ratio 1.10,
CI [0.93, 1.24]); searched solutions reach the same structures from the true or the rewired block (provenance 48 % vs 46 %). The library
is drawn UNIFORMLY at random in gp2's start phase. VSA offers structural similarity, so the library could be consulted where the search
already has a partial program. Research (VI insight:d7401431): nobody has encoded ASP/Datalog clauses in VSA, decoded vectors to rules with a
solver in the loop, or retrieved rule libraries by VSA similarity; plain HRR similarity is blind to structure unless fillers are
contextualized (Plate 1993: 100/100 vs 94/100); FHRR needs ~340 dimensions for 15 bound pairs at 99 % (Schlegel et al., Table 2).

## The encoding (two levels, research recommendation 1)
- Exact level: the rule itself (gp2's canonical tuple form) — edits and decoding stay symbolic and exact; no vector is ever decoded into a
  rule in G10-0/1 (decoding is G10-2).
- Key level: one FHRR hypervector per rule (torchhd 5.8.4, MIT), dimension d ∈ {1024, 2048, 4096}:
  rule = bundle( HEAD ⊗ head_atom, BODY ⊗ bundle(literal_i) ), literal = SIGN ⊗ (PRED ⊗ p + Σ_j ARG_j ⊗ filler_j);
  filler of a variable = canonical variable symbol (numbered by first occurrence, so alpha-equivalent rules get identical keys)
  CONTEXTUALIZED with the roles it fills elsewhere in the rule (Plate 1993); constants and predicates: random symbol vectors per
  NAME-FREE identity (predicates replaced by role-in-rule and arity — R1 of DESIGN_RULES.md: no name leaks meaning) — variant B keeps
  names for a speaking-names control. A program = the set of its rule keys; similarity of programs = mean of best-match rule similarities.

## G10-0 — does the key capture structure? (no search; minutes)
Data: the 113 library rules (24 blocks), the 33 blind-task references, and their renamed / rewired variants from arms2.
- T1 invariance: a rule and its alpha-renamed, predicate-renamed copy → cosine ≥ 0.99 (exactness check of the encoder).
- T2 structure sensitivity: rule vs its XR-rewired copy (same predicates, variable occurrences permuted) → must be clearly LESS similar
  than T1; report the distributions; plain (non-contextualized) HRR as the ablation that Plate predicts to fail.
- T3 agreement with the exact structural key: rank correlation between VSA similarity and near.matches / a graded structural distance on
  all pairs of library rules.
- T4 retrieval: for each blind task, rank library blocks by similarity to the task's REFERENCE (an oracle query) — is the block
  near.matches finds in the top 3? This bounds what G10-1 can reach.
Gate to G10-1: T1 ≥ 0.99 for ≥ 99 % of rules, T2 separation (AUC ≥ 0.9 between renamed and rewired copies), T4 top-3 recall ≥ 0.8 on the
tasks whose reference has a near.matches block.

## G10-1 — retrieval during the search (the MAC/FAC idea; pre-registered separately after G10-0)
Every R generations gp2 takes the best archive programs (by fit), encodes them, retrieves the K most similar library blocks by VSA key,
maps them onto the task (arms2.mapped_chunk) and injects them as immigrants (replacing the same number of random immigrants).
Arms, identical start sets (start RNG without arm name — review finding 2 of G8c), same budget:
- U  gp2 unchanged (random immigrants only)
- V  VSA retrieval immigrants
- Vs retrieval with a shuffled key-to-block map (same number of library immigrants, no structural information)
- Vn retrieval with speaking names (names leak?)
Outcome O2 as G8b-1. Primary: V vs Vs on O2 (information, not "more library"), then V vs U. Tasks: a NEW blind task set as confirmatory
(the 33 are development now — review finding 5 of G8c); fresh seeds. Fable review before the run.

## G10-2 — edits in vector space and a proposer (only if G10-1 is positive)
Local edits S' = S − r⊗a + r⊗b with cleanup and clingo check (research recommendation 5); a proposer that predicts WHICH structural
operation to apply (DTM, arXiv 2306.00751: 100 % vs < 30 % OOD) — the user's MTP idea in this space; dreams from the library with
anonymised identifiers (DESIGN_RULES.md R1).

## Resources
CPU only (torchhd on CPU; d ≤ 4096; a few thousand rules) — hal within its limits (≤ 4 processes, memory-capped) or the RTX 3070 host CPU.
