# Z1 diagnosis: where the deployed reader still loses (25.11.2026, exploratory)

Goal Z1: official alias EM ≥ 80 % on a fresh 2Wiki Q1 set; deployed reader R3r + base, primary-first merge (PREF), 75.5 % on fresh4
(PREREG_R3m). fresh3 and fresh4 are spent test sets; everything here is development analysis on them, and a confirmation needs a new
set (fresh5).

## Reproduction (needed because the reads were made on the peer's RTX 3060)
- Reads fetched from the exchange repository (results/r3m4-3060): read_fresh4_r3r.jsonl sha256 6323e31b…d82f,
  read_fresh4_base2shot.jsonl c1d032ee…6705; dev_fresh4_400.json 448abff0… as frozen.
- PREF rebuilt with reader_merge.py (b4964509) and scored with the frozen official_score.py (7f9170e9; q1_oracle.py 4cf9cd58) on the workstation,
  25.11.2026 08:37 UTC, Python 3.12 venv with clingo 5.8.3 (the system Python moved to 3.14 in the apt upgrade; the old venvs lost
  clingo): **75.5 %, per-question identical to r3m/fresh4/per_PREF.jsonl.** fresh3 PREF reproduces 74.75 % (research log).

## Gold-fact ceiling on fresh4
Gold evidence triples as the only read (z1_diag.py gold): **94.5 %** (bridge 97, comparison 99, compositional 90, inference 92).
Cells: reads right / gold right 295; reads wrong / gold right **83**; both wrong 15; reads right / gold wrong 7.

## The 83 questions lost to reading, by their weakest gold fact (z1_diag.py diag, stated_recall.py logic)
| class | n | compositional | inference | comparison | bridge |
|---|---|---|---|---|---|
| missed (stated, no matching read) | 38 | 22 | 10 | 5 | 1 |
| not stated in the paragraph (Wikidata-only evidence) | 19 | 6 | 13 | 0 | 0 |
| read correctly, answered wrong (downstream) | 19 | 7 | 8 | 1 | 3 |
| conflict (right value read, a wrong one too) | 7 | 4 | 3 | 0 | 0 |

Missed relations: place of birth 10, father 9, country of citizenship 7, place of death 6, mother 3, sibling 3, …; conflicts: father 7,
country of citizenship 4, spouse 3, mother 2.

## What the misses are (all 20 first "missed" cases read by hand)
- **Wrong value of the right type, often a granularity or gold choice:** Stoke St Gregory vs Somerset; Karnataka vs Bangalore; Sokuluk
  District vs Kyrgyzstan; Vicente López vs Buenos Aires; Yugoslav vs Serbian; American vs America. Several are gold noise or a
  different correct granularity.
- **Subject binding:** a fact of one entity attached to a token-sharing other (Jill Biden's birthplace as Joe Biden's).
- **Role confusion:** the lyricist/composer read as performer (Sammy Cahn, Irving Berlin); a band member read as director.
- **Type violations** (place of death = "August 6, 1973", = "65"; publication date = a description): present, but see below.

## Three levers measured on fresh3 + fresh4 (development; no lever reaches the goal)
1. **Relation type guard before the merge** (typeguard.py: date relations need a digit; places and agents must not be dates or numbers;
   placeholders dropped). R3r has almost no type violations (10 of 4,506 triples on fresh3, 4 of 4,544 on fresh4); the base reader has
   2,344 / 2,434 (mostly placeholders). **Effect: 0 answers changed on both sets** (fresh3 74.75 → 74.75, fresh4 75.5 → 75.5). Where a
   type-violating value occurs, the right value is missing too, so dropping it turns a wrong answer into an empty one.
   *This contradicts the lead taken from Z5 (type binding as a loss class): on 2Wiki with R3r as primary the class costs no answers.*
2. **Perfect arbiter between the two readers** (arbiter_bound.py, uses GOLD, a ceiling, never a method): for every single-valued
   relation group, keep only the gold-matching candidates from R3r ∪ base when one exists. fresh3 74.75 → **76.75 %**, fresh4 75.5 →
   **75.75 %**. Any arbitration (vote, verifier question, third reader as judge) between the existing two readers is bounded by +0.25
   to +2.0 points. Of the 44 missed gold facts on fresh4, 13 are read by base only (pref drops them under an R3r value), 31 by neither.
3. **Answer snapped to a context title** (counted, not run): wrong answers with gold = a context title and a token-subset candidate
   title: 3 (fresh3), 4 (fresh4), against 23 / 21 right answers that the same snap could touch. Small and risky.

## Consequence for the next registration (hypotheses)
- The remaining loss is **facts neither reader writes** (31 of 44 missed facts on fresh4) plus **answer form** (about 13 of the 19
  "read ok" losses are a correct entity in another surface form: "Prince Richard I of Capua" vs "Richard I of Capua", "Zhao of Wei" vs
  "King Zhao of Wei", "Petworth House, Sussex" vs "Petworth House") plus 19 questions whose evidence is not in the text at all.
- +18 questions are needed for 80 % on 400. Arbitration gives at most ~1–8; the type guard 0; a title snap ≤ 4 with risk. A
  reader that writes the missing facts is the only lever of the needed size: new candidates (a stronger teacher's reads distilled into
  the 0.6B reader, or sampled reads), not a better choice among the current two.
