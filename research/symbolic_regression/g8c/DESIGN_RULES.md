# Binding design rules for any learned proposer (G8c v2, G8d) — 19.11.2026

## R1 Anonymous identifiers (user question 19.11.2026: "hast du an die anonymisierung der identifier der datenblöcke gedacht?")
gp2 itself is name-blind (operators and fitness treat predicates as symbols; the canonical form renames variables; provenance matching
is renaming-invariant). A proposer that READS worlds or programs as text is not: with speaking names (parent_of, beat, outranks,
blocked_by) it can learn the meaning of a word instead of the structure, and the library block becomes guessable from the vocabulary
(review 1, finding 4).
- Every dream and every test task is shown to the proposer with predicates and constants renamed to random identifiers (p1, p2, …,
  c1, c2, …), a fresh random bijection per dream / per task and seed; arities and types are kept. The same applies to library block ids
  and to anything else that names an origin.
- Training and test use the same renaming procedure; the bijection is never an input.
- Control (reported, no claim): the same evaluation with the speaking names, to measure how much the names alone carry.
- Gate addition: R must beat an arity/vocabulary-size-only model on the anonymised dreams (review 1, finding 4 ii).

## R2 Privacy of real data (G9-type data)
Values of real experiences are coded before any search or model sees them (t/x/h/i codes); decode tables stay local (0600) and never
enter the repository; published results name codes only, never a code next to a plain instance, host or tool name that would decode it;
VI entries about such results are internal.
