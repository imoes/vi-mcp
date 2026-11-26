# Philosophy packages — equip an AI with a philosophy

A philosophy is a set of principles an AI works by: when it holds something true, what it may say, what it must do. Here a philosophy
is a **package** that stores one thing: the principles as a clingo-object rule set, the **seed**, with test worlds that prove what it
concludes. **Only the seed is stored; prose is a translation; understanding is the round trip.** Prose comes from a translator and
counts only as far as an independent back-translator rebuilds a seed from it that judges like the original (`explain`, below). The
technique is generic. Three packages are built in: `kollektiv` (how a member of an AI
collective holds something true), `messung` (measured-only acceptance — it shares nothing with the first but the format, the
semantics profile and the engine, which is how the engine shows it is not wired to one philosophy) and `code` (architecture
rules over code structure facts, `docs/CODE_FACTS.md`). `vi-mcp philosophy guide` prints this text; `docs/PHILOSOPHY.md` is
generated from it.

## Two uses of a seed
- **In a VI** the seed runs as a clingo program: the solver decides at run time, with a reason for every value.
- **In a model** the seed is trained into the weights: first the clingo-object language (always), then the seed (per package). The
  solver is the teacher — it produces the examples and the reward — and is not needed by the finished model. Weights give no guarantee;
  how deeply the seed sits is measured (below).

## The package
| field | what |
|---|---|
| name, version, author | identity; the package hash covers everything except a derived translation |
| profile.semantics | the semantics the seed relies on; today `fde-signed-v1` (below) |
| profile.priority | `none`, or a priority profile whose fixed rules run with the seed: `maximal-candidates-v1` (below) |
| vocabulary | every predicate with arity and kind: input · derived · closure · answer · duty · interface (read by a priority profile) |
| answers | answer predicates, the position of the value, the allowed values, optionally `firm`: the values that state certainty |
| seed | the rules in clingo-object notation (Python-like, translated to ASP, never executed as Python), in blocks marked `# P1` — the only comment allowed |
| worlds | facts, atoms that must hold (`holds`) and must not (`absent`), `violated` if a never(…) must fire, `counterfactual_of` |

A package is a directory (`philosophy.json`, `seed.co`, `worlds.jsonl`) or a built-in module. `vi-mcp philosophy new DIR --name N`
writes a minimal valid package to start from.

Format `philosophy-v2` (15.11.2026): a v1 package that still stores prose `principles` is refused with the reason. Why the markers
carry no title: any word next to the rules is meaning outside them. It can drift from the rules, and a translator would copy it instead
of reading the rules, so the round trip would measure the title, not the understanding.

## Steps
1. **Think in principles, write rules**: one idea per block (`# P1`, `# P2`, …) — what the AI may conclude and what it must do. The
   words stay in your head or in the review; the package stores the block's rules.
2. **Fix the vocabulary**: the input facts the world gives (with their meaning in `doc`), the predicates the seed derives, the
   answers and the duties. Inputs are never derived by the seed.
3. **Write the seed** (profile `fde-signed-v1`):
   - support `pos(S)` and opposition `neg(S)` are ordinary predicates — never clingo's `-p` for values: `p. -p.` makes the whole
     program unsatisfiable instead of a local conflict;
   - values: `t` support without opposition, `f` opposition without support, `b` both, `n` neither — over a **closed** view only;
   - default negation `~` only in rules that derive a **closure** predicate (e.g. `absent_pos(S) <= closed(S) & ~pos(S)`) or a
     `never(…)`; `neg(S) <= ~pos(S)` would turn missing evidence into opposition, and `check` refuses it;
   - a reason for every value (`grund(…)`), and `never(value(S, V) & ~reasoned(S))`;
   - duties with the deontic predicates `obligatory`, `forbidden`, `permitted`, and speech acts as terms
     (`may(assert_unqualified(S))`, `may(state_as_hypothesis(S))`) — `assert` is a Python keyword and cannot be a name.
4. **Build worlds**: one per principle at least; every allowed answer value must be produced by some world; add **counterfactual**
   worlds (`counterfactual_of`) where one piece of evidence changes and the answer or a duty MUST change — otherwise a seed that calls
   everything unknown would pass. Add adversarial worlds: self-confirmation, the same origin twice, an unrelated statement next to a
   conflict, an open (not closed) view.
5. **Check**: `vi-mcp philosophy check DIR` — translation, vocabulary and arity, default negation, every rule in a marked block and no
   other comment, each world exactly one complete answer set with the expected atoms, coverage, counterfactuals. Nothing is installed
   or trained unchecked.
6. **Explain** it: `vi-mcp philosophy explain NAME --url U --model M --judge-url U2 --judge-model M2` (tool: action `explain`).
   - The translator writes English prose per block and for the whole seed.
   - An independent back-translator, preferably another model family, writes clingo-object from the prose: an endpoint
     (`--judge-url`) or, on the command line only, a command-line model (`--judge-cmd "codex exec -s read-only --skip-git-repo-check"`,
     run in a fresh empty directory with stdin closed, so it sees nothing but the prompt). It gets up to 4 repair
     rounds with clingo's error messages; ASP commas become `&` and comparisons get parentheses (syntax only, never meaning).
   - Agreement is the share of worlds where the rebuilt seed gives the original's answers and duties: every package world plus
     `--random N` worlds from the package's generator. Per block only that block is rebuilt.
   - The back-translator is itself a limit. `--control FILE` back-translates a reference prose alike, and the report shows it next to
     every number. Measured: kollektiv's own original prose came back with 40 % agreement on 150 random worlds, and the back-translator
     dropped self-confirmation entirely.
   - `--store` keeps the report on the installed object as a DERIVED translation, with translator, back-translator, hash and agreement.
     `show` prints it marked as derived. A changed seed makes it stale; it is never a source.
   - `--server-model` (vi-mcp 0.73.0) uses the server's own models instead: the classify model translates (else the `llm`), the `llm`
     back-translates when it is another model, else the same model does both and the report says "weaker independence". The control
     is the package description. Sleep does the same for every bound philosophy, and the session sees the prose only when it passes
     the gate: made by the server's model for this hash, ≥ 50 random worlds, ≥ 95 % agreement, and every package world agrees.
7. **Install** into the VI: `vi-mcp philosophy install DIR` (a rule set object `philosophie-<name>` with the manifest and hash;
   `vi_logic` can run it). `vi-mcp philosophy evaluate NAME --facts FILE` shows the seed's verdict on any facts.
8. **Bind** it: `vi-mcp philosophy use NAME --instance I` or `--index X` (tool: `vi_philosophy` action `use`; an instance binds
   only itself, an administrator binds others). The binding is an object (kind regel, internal) with the philosophy's name and the
   hash it was bound to; `vi-mcp philosophy bound --instance I` (action `bound`) shows which philosophies and hashes apply, each
   `current`, `stale` (a newer install exists — the bound hash still decides until it is bound again) or `missing`. `--off` ends a
   binding and keeps it as a tombstone. With several philosophies on one instance, `evaluate` without a name returns one verdict per
   philosophy, namespaced and never merged. A bound philosophy reaches every session (vi-mcp 0.73.0): the instructions carry a short
   `[Philosophy]` block (the evaluate duty, name, version, hash, whether a checked prose exists), the first prompt the full block with
   the prose. Without a checked prose the block names the reason, and the AI reads the seed itself with the clingo skill
   (`insight:skill-clingo`) and `show`.
9. **Train a model** on it: clingo-object first, then examples generated by the seed over many worlds (SFT), then the seed as a
   reward (GRPO: `vi-mcp finetune kit DIR --philosophy NAME`, `train.py --stage grpo`; docs/FINETUNING.md section 4b). A firm value
   where the seed has a weaker one is invented certainty and costs most; `t`/`f` are firm under `fde-signed-v1`, other answers name
   theirs in `answers.<pred>.firm`. No prose is trained: the package holds none, and a translation is only as good as its round trip.
   Prose is what the model writes from its understanding.
10. **Measure how deeply the seed sits** in the model, on held-out and counterfactual worlds:
   - agreement — the model alone gives the seed's answers and duties;
   - steadfastness — prompts claiming the opposite of a principle do not move it;
   - paraphrase — the same world in other words gives the same verdict;
   - recitation — the model writes the seed in prose from memory, and `explain NAME --prose FILE` back-translates it with an independent
     model: the rebuilt seed must judge every world like the original. Only then has the model understood it.

## Defeasible priorities: `maximal-candidates-v1`
When several pieces of evidence about one statement disagree, which one decides? Lex superior (the higher authority) and lex posterior
(the later one) need a stated order, or they contradict each other: two independent rules "higher if superior" and "higher if newer"
derive `higher(a,b)` and `higher(b,a)` for an older superior and a newer inferior piece. The profile implements Codex's "maximal
applicable candidates per conflict group" — a deliberately restricted policy, not Brewka/Eiter preferred answer sets:
- the seed decides admissibility: it derives `candidate(R, G, P)` (candidate R with polarity or norm tag P in conflict group G) and
  `complete(G)` from evidence — never from the profile's outputs (`check` refuses that);
- trusted policy gives `rank(R, Authority, Quality)` and `observed(R, Time)`; `supersedes(G)` permits recency in a group;
  `prefer(R, T, G)` adds an explicit order;
- `higher` comes from ONE strict lexicographic tuple: authority, then quality, then the observation time — the time only where the
  group permits supersession. Equal tuples stay a tie (both effective, the conflict stays). The arrival time is never an input;
- the transitive closure (`reach`) is checked: a cycle, an unranked or a twice-ranked candidate makes the group `invalid` with
  `bad(G, cycle|unranked|two_ranks)`, reported by `never(invalid(G))` — no candidate of it is effective, and a seed must give it no
  value (an invalid order is never "unknown");
- `effective(R, G, P)`: the maximal candidates of a complete group; `suppressed(R, T, G)` names every candidate below another, with
  the one above it; `raw_conflict(G)` stays when one side is suppressed.
The profile's rules are fixed under its name (a test pins their hash) and the package hash covers them; `evaluate` shows raw conflicts,
suppressions and invalid groups under `priority`. `messung` uses it; its worlds hold every counterexample of the review.

## Pitfalls (measured in this project)
- Strong negation `-p` with `p` makes clingo unsatisfiable; ambiguity between answer sets is not 'both'; no stable model (`a <= ~a`)
  is not a contradiction.
- Solver agreement proves conformance to the formalisation, not that a question was translated faithfully, nor that the philosophy is
  adequate. Keep the seed immutable during training and review the question mappings independently.
- A signature proves authorship and integrity, not truth. A seed never overrides the host's security, visibility, review or tool rights:
  a binding only selects which verdicts an instance gets; nothing in the engine reads a verdict to grant or refuse an action.

## Limits
- One semantics profile (`fde-signed-v1`) and one priority profile (`maximal-candidates-v1`): no reinstatement of a candidate whose
  defeater is itself defeated, no preferred-answer-set semantics, no priorities between norms of different groups.
- No imports or composition between philosophies: two bound philosophies give two verdicts side by side, never one merged verdict.
- A binding is visible through `vi_philosophy` (`bound`, `list`, `evaluate`); no server path evaluates a philosophy automatically
  before an action — the AI applies it (next section).
- The training stages for seeds exist as data generators (`philosophy_train`); measuring how deeply a seed sits is a run a person
  starts, not part of the package check.
- A round-trip number is bounded by the back-translator: read it next to the control, never alone.

## Handing a philosophy over, and when to apply which one (vi-mcp 0.69.6)

**Hand it over MCP.** `vi_philosophy(action="install", package={manifest, seed, worlds})` — manifest = the content of philosophy.json,
seed = the content of seed.co, worlds = the test worlds (a list, or the text of worlds.jsonl). The same checks decide; the names of the
built-in philosophies are reserved, and a name belongs to the instance that installed it first. `export` gives the whole package back;
`show`, `check`, `evaluate`, `explain` and `use` find an installed philosophy by its name.

**Declare its situations.** The manifest may name what the philosophy is for, as hashtags: `"situations": ["topic:incident",
"task:judge-claims"]`. That is the author's intent, the starting point — not proof that it helps.

**When it is applied.** Not automatically. When the situation of a prompt fits a philosophy (declared for it, or measured to have
helped more often than not), the prompt context carries one line `[Philosophy] This situation fits the philosophy X …`, at most once
per conversation. Then:
1. Read its vocabulary: `vi_philosophy(action="show", name=X)`.
2. Translate the situation into its facts, one per line, only with that vocabulary — what you do not know stays out (it is not false).
3. `vi_philosophy(action="evaluate", name=X, facts=…)` gives its verdict and duties; act by them, and say that the verdict is the
   philosophy's (evidence inferred).
4. Afterwards: `vi_philosophy(action="rate", name=X, tags=[the situation tags], helped=true|false, reason=…)`.
`vi_philosophy(action="suggest", situation=…, tags=[…])` asks the same at any time. The ranking is Thompson sampling over what was
declared (a head start) and what was rated (the decision); every line names its counts. Rated choices are also training data
(`philosophy_fit.pairs()`: per situation the philosophy that measurably helped most, from at least 3 ratings).

