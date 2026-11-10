# Architecture

## Target picture

A **VI** is an AI that loops — with two layers:

| Layer | What it does | In the code |
|---|---|---|
| **Intuition** (subconscious) | sees every reported action, judges without a model, automatically *before* the action: remembered answers, reflexes, learned searches | `intuition.before`, `reflexes.before` |
| **Consciousness** | what a human or LLM deliberately looks up: insights, rules, drilling down | `memory.recall`, `memory.drilldown`, tools `vi_recall`/`vi_drilldown` |

Three principles from the project owner:

1. *"You give the AI an intuition that analyses automatically; consciousness only analyses what has been pre-filtered."*
2. *"In the first place you remember the **search** (the hashtag combination, the mnemonic), not the fact."*
   → learned searches run automatically before matching actions; `vi_drilldown` goes further down the funnel.
3. *"Before an action you automatically access memory, consciousness and subconscious — and that has to live
   in the database."* → every experience carries in `daten.vorher` the triggers and everything that was found
   beforehand, and is linked to those objects.

And the picture for operation: **one AI process, many conversation contexts — like time slices.** From this follows
the most important decision of the project:

## One process

There is **exactly one** server process. All clients talk to it over HTTP.

*Why (measured on 08.11.2026):* As a stdio server, every AI session started its own process; on one host
4 processes ran at the same time on the same database file (`/proc/<pid>/fd`, same inode), each with its own
loop. Consequences: N-fold maintenance work, locks only within one process (`threading.Lock`), lost
updates through read-modify-write across process boundaries, races for conversation numbers. Eight independent reviews
(peer sessions, 08.11.) reached the same conclusion: *the problem is the N processes, not the database.*

With one process: one writer, one loop, one connection, one lock (`memory.lock`, RLock).

*How you would notice that the assumption is wrong:* when a second process opens the same `vi.db`. Observation point:
`fuser ~/.local/share/vi-mcp/vi.db` must show exactly one process.

## Database: SQLite, as long as it is one host

SQLite in WAL mode: many readers, one writer (https://www.sqlite.org/wal.html). With one process that is enough.
**Not** over NFS/SMB — WAL needs shared memory on one host (ibid., "Disadvantages").

Only when several hosts are to write is a database server needed; then **PostgreSQL** (JSONB, tsvector,
sequences, row locks). MongoDB was considered and rejected: the model is relational (objects, tags, edges
with joins), full-text search would be weaker, and replacing a document loses updates just the same. Because all
access goes through one process, a later switch is a change in `memory.py`, not in the protocol.

## Data model

> **Stored formats keep their German names** — table and column names (`objekt`, `art`, `zeit`, `daten`, `sicht`, …), JSON keys in
> object data (`quelle`, `inhalt`, …), hashtag kinds and values (`thema:`, `modus:aktiv`, `ok:ja`, `herkunft:offen`, …), stored enum
> values (`geteilt`, `intern`, `privat`, …), object kinds (`erkenntnis`, `erfahrung`, `regel`, …), the P2P wire format and the config
> file keys — so existing databases and peers keep working. The MCP interface (tool names, parameters, enum values) is English since
> 0.22.0; the German names are accepted as aliases and English enum values are translated to the stored German values (`api_en.py`).

**Everything is an object** (`memory.MemoryObject`, table `objekt`; mapping without an ORM): fixed fields `id`, `art` (kind),
`zeit` (time); changeable only through methods — `tag`, `confirm`, `refute`, `link`, `access` —, each with an
entry in `aenderungen` (who, when, **reason — mandatory**, checked before the change). The history keeps 50
entries; older ones are truncated **with a count** (`daten.aenderungen_gekuerzt`, shown in `vi_object`).

| Kind | What for | Created by |
|---|---|---|
| `erfahrung` (experience) | every reported action: tool, arguments, duration, `ok:ja`/`ok:nein`/`ok:unbekannt`; `daten.vorher` = memory access before it; **importance from surprise** (`ueberraschung:neu` 3 · `wiederholt`/`erholt` 2 · `chronisch` 1 · `keine` 0 — prediction error as a learning signal, docs/FORSCHUNG.md A7) | `vi_after`; `vi_before` with a remembered answer; before without after (session end/1 h) |
| `antwort` (answer) | remembered result of a **read-only** call (`frage:<hash>`), valid for 120 s (configurable per tool, max 1 h) | `vi_after` |
| `erkenntnis` (insight) | something learned, with source and importance 0–3; with `key` (0.23.0) **one object per recurring finding**: the same key from the same instance updates it (`daten.key`, `daten.repeats`, earlier states in `daten.history`) instead of adding a new one; with an image (0.35.0) `daten.bild` and `daten.regionen`, bytes in table `bild` (see Images) | `vi_learn` |
| `regel` (rule) | condensed: same error ≥ 3× in 24 h, mode `test` | loop |
| `reflex` | Python code: kind `werkzeug`, `vorher`, `nachher` (MCP: `tool`, `before`, `after`) | `vi_reflex_learn` |
| `suche` (search) | mnemonic: name, filter, **triggers**, story | `vi_learn_search` |
| `gespraech` (conversation) | one session, serial number `YYYYMMDDNNN`, summary + hashtags; history zlib-compressed in `gespraech_roh` | `initialize` |
| `frage` (question) | question from one instance to another or to all; states `offen`/`zugestellt`/`beantwortet`/`abgelaufen` (open/delivered/answered/expired) | `vi_ask` |
| `skill` | solution path: problem (triggers), steps, instructions, versions, evidence; modes `test`/`aktiv`/`strittig`/`aufgegangen` (merged) | `vi_solved`; sleep (success after errors) |
| `selbst` (self) | `selbst:kern` = the self (target/actual/narrative, versioned); otherwise proposals for the target (mode `test`) | start / `vi_self_propose` |
| `schlaf` (sleep) | report of a consolidation run: counters per step, duration, errors, new/changed IDs | loop (from an importance sum; at night only after 24 h without sleep) |

**Hashtags** `art:wert` (kind:value, table `tag`); `art:<kind>` is always set. Administrative hashtags (`art:`, `frage:`, `ok:`,
`serial:`, `tag:`) do not count as content. **Edges** (table `kante`, both directions, with reason): automatic with ≥ 2
shared content hashtags (Zettelkasten idea, A-Mem) and from every experience to the objects found beforehand.

**Modes** (exhaustive): `aktiv`, `test`, `aus`, `defekt`, `strittig`, `widerlegt`, `archiviert` (active, test, off, broken, disputed,
refuted, archived). Refuted objects appear in no search; disputed ones appear with a note; archived ones only if the filter contains
`modus:archiviert` (stub: shortened text, hashtags, time; the content lives in the long-term archive).

**Owner and visibility** (columns `instanz`, `sicht`): Every object belongs to the instance whose token the request carried
(objects of the loop: instance `vi`); the hashtag `instanz:<name>` is set from it and cannot be chosen freely.
`sicht` follows the kind: **private** (`privat`) are `erfahrung` and `antwort` (and the raw history of a conversation) — results
can contain credentials; **shared** (`geteilt`) is everything else. An instance reads what is shared and its own; private
objects of other instances count as unknown for it. The server (loop) sees everything.

## Collective: instances learn from each other

An **instance** is an agent system with its own token (e.g. `claude-code`, a control room, another agent) —
named after the system, not after a person. All instances share one memory; what they learn from each other goes through
five paths:

1. **Before the action** `vi_before` delivers insights, rules and learned searches of *all* instances, each with
   its owner ("from b, confirmed by 2 other instances"). With `context_hashtags` a client reports what it is currently
   working on — more triggers, better hits.
2. **Confirming across instances:** `bestaetigt_von` counts per instance. Only confirmations by *other* instances add weight
   (no self-confirmation, CLAUDE.md rule 5).
3. **Contradicting across instances:** A single other instance makes an object `strittig` (disputed; stays visible, with a
   note) — it cannot delete another instance's knowledge. It becomes `widerlegt` (refuted) through the owner itself or
   through two different instances; a confirmation by another instance lifts `strittig` again.
4. **Questions:** `vi_ask(to, text)` → the target instance sees the question at its next action (once per
   instance), answers with `vi_answer(id, text, evidence)` (evidence mandatory); the asker sees the answer at
   its next action or via `vi_questions`. After 7 days without an answer: `abgelaufen` (expired).
5. **The loop condenses across instances:** same error ≥ 3× in 24 h → rule; if it occurred at ≥ 2 instances,
   it carries `kollektiv:ja` and names the instances. The rule contains only tool and error signature, never results.

Remembered answers (`antwort`) apply **only within one instance** since 0.2.0.

## Rules for clients

On connecting, every client receives fixed rules in the MCP `instructions` (`tools.RULES`, since 0.20.7): consult before starting
any task, before changing actions, on errors and on questions about internal systems; learn after solved non-obvious
problems, on lasting instructions from the user, after looked-up system facts and on corrections; never secrets, unproven or
transient things. Without a token, `tools.RULES_WITHOUT_TOKEN` is added. Whether the rules are followed has not been measured yet.

## Usage statistics

Since 0.21.0 the server counts every call of a VI tool (`usage_stats.record`, table `nutzung`, 90 days, without arguments and text).
`vi_stats(days)` evaluates usage, compliance with the rules, hints and warnings, knowledge, search, as well as sleep and training
(`usage_stats.report`). A changing action counts as prepared if the same instance consulted the VI in the 30 min before it. Since 0.24.0 each section names the period it really has data for: tool calls exist only since the table was created, so the rule rate counts only actions from then on, and the automatic `vi_before` of the hook does not count as consulting. Actions are also listed **per project** — the last part of the working directory the hook sends at `initialize` (`clientInfo.cwd`), stored as `daten.project` of the conversation (only the name, never the path).

## What is shown unasked

Since 0.21.1, disputed knowledge and language-model hypotheses from sleep (`herkunft:schlaf-llm`) no longer appear as hints before
actions unless another instance has confirmed them. They remain findable via `vi_recall`; `vi_before` states their number
("only on request"). Reason: a disputed hypothesis was the most-shown hint, with 719 reinforcements.

## Warning before risky actions

Since 0.20.8, `vi_before` warns when the router model classifies the situation of an action as risky (`learning.warning`). The threshold
is set by training on the holdout (≥ 50 % failed with ≥ 10 cases, otherwise off); the justification is counted rates per feature
(`quoten` in the object `modell:router`), because the probabilities of the balanced model are not calibrated.

## Recall

Filter language: `art:wert` (AND), `(a OR b)`, `!art:wert`, prefix `art:wert*`, free words → FTS5.
Weight = **relevance** (FTS rank normalised, otherwise 1) + **recency** `(1 + hours since last access)^−0.3` (power law,
Wixted & Ebbesen 1991 / ACT-R — docs/FORSCHUNG.md A9; exponential up to 0.3.0, see correction below) + **importance**
`importance/3·0.6 + log1p(2·confirmed + accesses)/6 − 0.5·refuted` (capped at 1) + **collective bonus**
0.2 per *independent line* of confirmation (at most 0.6). After Park et al. 2023, "Generative Agents" (arXiv 2304.03442).
Since 0.33.0 a line is a model family, not an instance (Condorcet's jury theorem needs independent voters; "common causes create
correlations", SEP *Jury Theorems*): instances of one declared family (`vi-mcp family INSTANCE claude`) count once, a confirmation
citing the object's own source counts as none, an instance without a declared family counts as its own line. The same rule decides
`widerlegt`: the author, or two different families — two sessions of one model only make an entry `strittig`.
The family is found automatically (0.34.0), per conversation: the client announces it with the header `X-VI-Family` (`vi-mcp setup`
writes `claude` for Claude Code and `gpt` for Codex), or it is recognised from `clientInfo.name` (prefix `claude` → claude, `codex` →
gpt). A family declared by the operator (`vi-mcp family`) wins over the announcement; a client that announces nothing and is not
recognised (a script) leaves the instance its own line. `vi-mcp family INSTANCE` shows the declared and the announced families.
Every hit of `vi_recall` is **reinforced** (`zugriffe + 1` atomically, `zuletzt = now`) — except with `reinforce=false` (0.31.0), the
read-only search for measurements and probes: a benchmark of 49 questions had reinforced 733 objects once each.

> **Correction 2 (0.4.0):** The exponential decay made everything older than two weeks practically disappear (30 d: 0.03).
> Now a power law; `memory.DECAY_D = 0.3` is a starting value: 1 h 0.81 · 1 d 0.38 · 7 d 0.21 · 30 d 0.14 · 1 y 0.07.
> *Observation point:* ranking old/new on the same queries before/after the switch; hint lift.
>
> **Correction 1 (08.11.2026):** This document used to say the decay factor 0.995/h was an *unverified assumption*. Checked
> (docs/FORSCHUNG.md, B1): Park et al. give 0.995 in section 4.1 — but **per game hour**, and a game hour there
> corresponds to about one minute of real time (appendix A). vi-mcp applies the factor **per real-time hour**
> (half-life ≈ 5.8 days). So the factor is backed by the source, the time unit is our own choice. In addition, Park
> normalises the three components with min-max to [0,1]; vi-mcp does not. Both are listed under "What is still missing" in the CHANGELOG.

**Drill down**: the most frequent content hashtag of the hits that is not in the filter (≥ 2 hits) is appended;
search again; at most 3 (max 5) levels.

## Reporting an action: before / after

The VI **never acts in the world itself** — no tool call, no writing outside the memory. Within the
memory it does act (loop: condense rules, expire questions), every change with a reason and owner `vi`.
A client reports every action:

```
vi_before(tool, args, read_only?)  → {antwort, antwort_alter_s, antwort_ttl_s, args, hinweise, vorher_id, zugriff}
   1. before-reflexes (active: may change args; test: hint only)
   2. triggers: tool:, skill: (prefix up to the first _), host: (from host/hostname/node/device), instanz:
   3. insights + rules for the triggers → hints
   4. learned searches for the triggers → run, hits as hints
      At most **4 hints** from memory (working memory, Cowan 2001 — docs/FORSCHUNG.md A2); the rest
      is stated as a count and can be retrieved via `vi_drilldown` (progressive disclosure).
   5. read_only? → fresh remembered answer → client does NOT execute; the experience is stored immediately
vi_after(tool, args, ok, duration_ms, error?, result?, before_id) → {erfahrung, hinweise, vorher_gefunden, verstaerkt, bewertet}
```

The answer keys stay German (stored format, see "Data model"): `antwort` = remembered answer, `hinweise` = hints, `vorher_id` = the id
to pass back as `before_id`, `zugriff` = memory access; `erfahrung` = id of the stored experience, `vorher_gefunden` = a matching
`vi_before` was found, `verstaerkt` = number of reinforced objects, `bewertet` = number of shown hints whose Thompson counters were updated (`bandit.book_entry`).

**Reinforcement happens on success, not on display.** Up to 0.2.0 every displayed hint counted as an access —
what was shown became more important merely by being shown and was therefore shown again (self-confirmation, Matthew effect;
CLAUDE.md rule 5). Since 0.2.1, `vi_after` with `ok=true` reinforces the objects found beforehand. That is an
**assumption** ("the hint helped"; testing effect: only successful retrieval strengthens, docs/FORSCHUNG.md A10).
*Observation point:* **hint lift** (`metrics.py`, in `vi_experience` per tool and in `vi_status` overall):
success rate of actions with a hint versus without; under 10 cases per side "too little data"; lift < −5 points means
"hints do harm — assumption refuted". Deliberate searching still reinforces immediately: the hits of `vi_recall` (unless `reinforce=false`) and a learned search used by
`vi_drilldown`. `vi_object` reads without reinforcing (corrected 0.31.0; this line said otherwise before).

**Read-only or writing?** If the client states `read_only`, its statement applies; otherwise the name pattern
`intuition.WRITING` (create, update, delete, send, …). Writing tools are **never** answered from
memory.

**No after?** The access does not disappear: at the end of the conversation or after 1 h it is stored as an experience
`ok:unbekannt` ("no result reported").


**Triggers from command lines (since 0.18.0).** For shell tools (`Bash` and others), `intuition.command_triggers` splits the command line into sub-commands (at `; & | ( )`, backticks,
`$(` and quotes), skips variable assignments and `sudo`/`env` together with their options, and takes the first word. Known commands become `thema:<command>` and
`skill:<area>` (`intuition.COMMAND_SKILL`: Proxmox, Ansible, Docker, PostgreSQL), `ssh [user@]host` becomes `host:<host>`. So knowledge about `vzdump` appears before `ssh pve1 'vzdump 101'`.
Since 0.19.4 **every** domain command becomes `thema:<command>` (`ipa-client-install`, `llama-server`, `pip3` …); everyday shell commands (`intuition.SHELL_EVERYDAY`: cd, ls, echo, cat, head, sleep, interpreters such as sh and python3 …) do not. Since 0.20.2, grep, sed, find, pkill, chmod & co. are deliberately triggers, because there are real pitfalls with them; prefixes such as `sudo`, `timeout 300`, `setsid`, `nohup`, `nice -n 10`, `env X=1` are skipped.
Text in quotes only counts as a command if it is executed (`ssh host '…'`, `sh -c '…'`, `su -c '…'`); `psql -c "select 1"` does not produce `thema:select`.
Host names after `ansible -l/--limit` (with a dot, without `!`) become `host:`. `thema:ssh` counts as generic when matching, like `tool:Bash`.
## Conversations — the time slices

`initialize` → new session (`Mcp-Session-Id`, random) → conversation object with serial number
(highest of the day + 1, compared **numerically**, `INSERT` as the lock — unique even with concurrency,
even beyond 999). During a request, new objects belong to this conversation (`contextvars`).

States (exhaustive): `offen` (open) · `beendet` (ended, DELETE) · `abgelaufen` (expired, 4 h without a request) · `unterbrochen`
(interrupted, server stopped). On every transition out of `offen` the conversation is saved; afterwards the session id returns 404.

## Deleting — nothing disappears silently

`vi_delete_conversation(serial, reason)`: only the owning instance, only ended conversations. Removes experiences,
remembered answers, raw history and their edges; the conversation object remains as a **tombstone** (`zustand:geloescht`,
time, owner, reason, count). Shared knowledge from the conversation remains — it is knowledge, not history.
Instance-wide (person): `vi-mcp delete-instance <name> "<reason>"` on the host (admin, not via token).

## Skills — solution paths that evolve

`skills.py` (procedural memory). A skill is created when something counts as solved: an instance reports it with
`vi_solved`, or sleep recognises that an action succeeded after errors of the same tool in the same conversation
(`ueberraschung:erholt`; the sequence of tools from the first error to the success is the solution path). It appears as a
hint before matching actions and is **text**: knowledge only becomes executable through reflexes in the sandbox.

**Evolution:** The same name or the same problem yields a new version with reason and evidence; missing
steps are added, old versions remain in `daten.versionen`. If a skill repeatedly does not help (≥ 3 failures,
success rate < 30 %), sleep sets it to `strittig`. **Merging:** `vi_skill_merge(a, b, name, reason)` creates
a new skill from both (triggers and evidence united, steps one after the other); a and b become `aufgegangen` (merged) with a
reference, no longer appear in searches, but remain retrievable. Sleep only proposes merges (`fusion:vorschlag`
for the same tool + error signature); an instance has to decide.

## Self — the virtual personality as an object

`selbst:kern` (docs/FORSCHUNG.md A12, C1; models: Conway's Self-Memory System, Park's agent profile). **Intension and
extension kept apart:** `soll` (target: values, goals, style, limits — each sentence with origin and date) and `ist`
(actual: competence per skill, weaknesses, relationships — computed by sleep from 30 days of experience, never by hand).
The `erzaehlung` (narrative, ≤ 150 words, from a template, never a source of its own facts) is in `initialize.instructions` of every
session and is repeated as a hint every 25 actions (persona drift after a few rounds, Li et al. 2024).

**Changing the target** only via `vi_self_propose` (≥ 3 pieces of evidence as object IDs from ≥ 2 days — spacing instead of
burst) and confirmation by **another, trusted** instance (`vi_confirm` on the proposal). "Trusted" currently
means the reflex permission — **assumption:** behind a trusted instance there is a human who approves. Every version
is stored in full in `selbst_version` (not truncated). Version 1 comes from the project rules (CLAUDE.md).

## Training on demand (since 0.20.0)

`on_demand.py`: A background thread learns as soon as new data is there — `vi_after` with a result and `vi_learn` trigger it, at the earliest
60 s after the last run (several events yield one run). Steps: embed missing vectors (at most 120 s per run; a remainder
triggers the next run immediately) → proximity edges only for new vectors (column `vektor.verglichen`) → KMeans content groups as soon as 200 new
vectors have been added → bandit counters → router (LogisticRegression). Measured on a copy of the production data (09.11.2026, 5,118 objects):
router 68–487 ms, bandit 30 ms, proximity edges 21 ms without new vectors (full comparison before: 9.6 s, grew quadratically). Sleep and training
share the lock `on_demand.TRAINING`. Status in `vi_status` ("training on demand: … runs, duration per step").
Sleep remains responsible for what needs a language model or condenses experiences (reflection, abstraction, skills, scorer, archive).

## Visibilities

`privat` (private: only the owning instance), `geteilt` (shared: everyone, including the tokenless instance `offen`, and the P2P network), `intern`
(internal, since 0.20.0: all instances with a token, never `offen`, never the network — `p2p._collect` only takes `geteilt`). For company knowledge
such as Confluence: in open-wiki mode it would otherwise be readable without login, including what has read protection in Confluence. Set via
`vi_learn(visibility="internal")`; checked in `memory.visible_to` and `memory._filter_sql` (one place for search, hints, semantic search).

## Sleep — consolidation

A run in its own thread that the loop starts (`sleep_cycle.py`; since 0.20.5, before that synchronously in the loop, which then stood still for minutes) as soon as the importance sum of new experiences is ≥ 80 and the last sleep is at least 120 min ago (since 0.21.1; before: ≥ 40 without a gap); at 03:00 UTC only as a safety net
if no sleep has run for 24 h (since 0.20.3) (Park's reflection trigger on a 0–3 scale). Seven core steps, each counted, everything in the report `schlaf:<time>`:
triage (surprise + importance + future relevance) → replay by (host, skill) interleaved with older experiences
(CLS: read the new against the old, do not overwrite) → schema matching (**new** experiences against
existing insight: same outcome = evidence edges; different = `konflikt:offen`, no silent change) →
abstraction (cluster without schema, ≥ 3 experiences on ≥ 2 days → insight `test` from a template with evidence edges) →
housekeeping (see "Long-term archive") → self actual → report. Further steps (reflection, skills, scorer, reviewer, vectors,
proximity, content, learning) are described in their own sections; the step names in the report are `1_triage` … `8_lernen`
(`sleep_cycle._run`). A confirmation by the server does not count as another instance (no weight from automation).

## Learning — the router learns its weights

Up to 0.4.0 the order of the hints was a fixed formula (recency + importance + bonus). Since 0.5.0
a **logistic regression** (scikit-learn, in sleep; since 0.20.0 on demand) learns from its own observations which hint led to success in
which context — docs/TRAINING.md 4a/4b.

- **Observation** = reported action with label `ok`; features = triggers (`tool:`, `skill:`, `host:`, `thema:`,
  `stunde:`) × hints shown (`hinweis:<id>`, `hinweisart:<kind>`, `hinweis_n`). Stored in `objekt`/`tag`/`daten`;
  the view `beobachtung` shows them flat (no copy — one source of truth).
- **Matrix**: built from the DB at training time (`DictVectorizer`, sparse 0/1); sklearn has no DB format.
- **Model** `modell:router`: weight per feature + intercept as **readable JSON** (no pickle); `vi_model`
  shows the strongest weights. Prediction = sigmoid sum in plain standard library.
- **Router score** = lift = P(ok | triggers + hint) − P(ok | triggers). Only if the model is `aktiv`; otherwise heuristic.
  Every observation names `router` (`heuristik`|`modell`), `kandidaten`, `gezeigt`, `exploration`.
- **Minimum amounts** (Peduzzi 1996): features with < 10 occurrences are dropped; min(ok, not ok) < 50 or holdout AUC
  ≤ 0.6 → mode `test` (stored, shown, not used). Holdout = the chronologically last 20 %.
- **Ranking utility gate** (0.30.0, `learning.utility`). AUC says whether the model tells ok from not ok — it can do that from the
  situation alone and still order the hints at random. Before the router uses a model, its order has to pay off on the holdout: the
  holdout pairs (a shown hint and its label) sorted by the model's lift, mean advantage over the tool's base rate of the top quarter minus
  the bottom quarter; it must be > 0 and larger than two standard errors (0.32.0, Mayo's severity: with one it passed without any real
  effect in about 16 % of trainings), in both reference classes — base rate of the tool and of tool + host (0.32.0, the generality
  problem of reliabilism: which reference class defines "reliable" is a choice, so no single choice may decide) — with at least 30
  pairs per quarter, else `nicht_bestimmbar`
  (named, mode stays `test`). A proxy on shown hints, not an off-policy estimate: propensities exist only for the ε slot (`rest_n` is
  logged since 0.30.0 so one can be computed later). Not compared with the previous model, because training on demand runs about every
  minute and the previous model has already seen most of this holdout. Same principle as the "non-decreasing validation utility" gate of
  WeightLoop (arXiv 2611.07319) and the downstream check of Google's sleep framework: what is learned goes live only when it pays off.
  Any weight vector passes through this gate the same way — retrained, written by hand or by a language model.
- **Inseparable hints** (0.32.0, `learning.inseparable`, Duhem): hints always shown in the same actions (≥ 10 times) are confirmed or
  refuted only together; `vi_model` names them, so their weights are not read as individual evidence. Direct feedback on one hint
  (`vi_confirm`/`vi_refute`) is what separates them.
- **Warning and ranking are two abilities with two gates** (0.30.0): the warning before risky actions needs only the AUC (it classifies the
  situation); the ranking also needs the utility gate. A model in mode `test` can therefore still warn.
- **Hint age as a feature** (0.30.0): `alter:neu` when the hint was at most `metrics.NEW_DAYS` (7) days old when shown — the same threshold
  as the cold-start observation point, so its weight answers the cold-start question directly.
- **Documentation gets triggers** (0.26.0, sleep step `6b_doc_triggers`, `doc_triggers.py`): imported documentation (company docs, vendor
  docs, manuals) gets `host:` for hosts the memory already knows from outside the documentation and `thema:` for topics learned knowledge
  already uses (title only). Links are ignored; a host in more than 2 %, a topic in more than 5 % of all documentation is skipped; at most
  5 each per object; no new edges; recorded in `daten.derived_triggers`. Documentation of all three kinds counts as reference material
  (`intuition.LOOKUP`): at most one slot before an action.
- **No repetition within a conversation** (0.24.0): a hint shown in the same conversation during the last hour (`intuition.REPEAT_S`) is held back, counted in the closing line ("N already shown in this conversation …") and listed in `daten.vorher.repeat_suppressed`. Measured 09.11.2026: three objects made up about 2,300 of 5,841 shown hints.
- **ε-exploration 10 %**: one slot of the budget goes to a random candidate from further back, marked
  "(exploration)" — otherwise the model only learns about what the heuristic shows anyway (off-policy, Li et al. 2011).
- **Reference material at most once (since 0.19.3)**: imported vendor documentation (`art_wissen:doku-extern`) takes at most
  one slot before an action; further paragraphs only come via exploration. In `vi_recall` everything remains findable. Reason: manual paragraphs match
  almost every command via `skill:` and pushed experience knowledge (warnings, pitfalls) out of the budget.
- *Observation point:* hint lift (`vi_experience`) before/after `router: modell`. If it does not rise, the model is not
  better than the heuristic → back to `test`.
- **Taught through labels, never through weights** (0.29.0). The teacher is already there: the scorer's verdicts (language model) and the
  direct feedback on a shown hint are the labels. Writing weights from outside (as in "weight space programming") would not survive the
  next training (scikit-learn regularises towards 0) and would replace measurement with opinion. Weights are read: `vi_why` lays open one
  decision (contributions weight × value; they plus the intercept are the logit), and after training the sleep step `8b_gewichte_pruefen`
  (`weight_audit.py`) applies fixed rules — `dominant`, `contradicts` (weight against the bandit's measured lift), `network` (unconfirmed
  hint from the network with a strong weight), `hour` (time of day among the strongest weights, post hoc). It reports, it never changes.
- *Observation point for cold start:* `metrics.lift_by_age` in `vi_stats` — advantage over the tool's base rate for new (≤ 7 d) against
  older hints. Only a measured gap justifies teaching new hints (e.g. weighted pseudo-observations); not built.

**Stage 2 — Thompson sampling (`bandit.py`)**, effective from the first action, without sklearn: every hint keeps
`daten.nuetzlich = {ja, nein}` (actions after display succeeded / failed; atomically via `json_set`). If no
model is active but at least one candidate has been rated, the router draws a sample from Beta(1+yes, 1+no) per candidate
and sorts by it (`router: bandit`) — rarely shown hints stay in play, frequently failing ones move back.
`vi_object` shows the counters ("helped 20 / not 1, expectation 91 %"). Ranking exhaustive: `modell` > `bandit`
> `heuristik`. Sources: Russo et al. 2017 (arXiv 1707.02038), Agrawal & Goyal 2012 (arXiv 1209.3352).

## Scorer — whether work succeeded

"The tool did not crash" was true in 63 of 64 cases and therefore almost worthless as a learning signal. `scorer.py` rates in three stages:

| Stage | When | Result | Counts for learning |
|---|---|---|---|
| Code | every sleep | `erfahrung.daten.score` = grade 0–1, features (`fehler`, `fehler_wiederholt`, `identisch_wiederholt`, `test_rot_danach`, `test_gruen_danach`, `korrektur`, `erholt`), version | always |
| Model | every sleep, ended conversations from 5 turns | object `bewertung`: grade on a fixed scale, justification, turn numbers as evidence, confidence | only once calibrated: at least 20 conversations with a human grade, 70 % of them within 0.25 |
| Human | immediately via the hook | object `bewertung` | always |

Router, Thompson counters and hint lift use the grade instead of `ok` where it is available. Since 0.19.0 the Thompson counters measure the advantage over the tool's base rate (`bandit.py`). If the scorer finds that an action counted as successful
actually failed, it rebooks the yes of the hint shown into a no. A conversation grade below 0.4 turns all actions of the conversation
into failures for learning. Ratings are private. The log for the model contains only tool, outcome, shortened arguments and errors.
`tests/evals/router.json` is a fixed set of test cases for hint selection that runs with every version.

## Vectors — meaning instead of word equality (stage 3)

`vector.py`: embeddings (OpenAI-compatible service, config `embed`) for shared knowledge objects, as a float32 BLOB in
table `vektor` (TRAINING.md 4c). Only `text` (the core statement) is embedded, not `inhalt`. Catching up happens in the background:
during training on demand (at most 120 s per run) and in sleep (step 7, at most 300 s), in batches of 16. The service is shared on the
production host; since 0.20.5 the VI can pause after each batch in proportion to the batch duration (`embed.pause_anteil`,
default 0 = unthrottled; 1.0 = at most half the load). Reason: a single request by other users took 23–27 s there (measured
09.11.2026 07:00 UTC; whether the VI was the cause is not proven). For `vi_before` the service remains too slow. Step 7b: cosine ≥ 0.85
→ edge "semantically similar", since 0.20.6 only to the 10 nearest and only mutually (mutual kNN, `vector.cap`); ≥ 0.95 between **different** instances → `dublette:moeglich` (merging
is decided by an instance, not by the server). `vi_recall(filter, semantic=true)` explicitly embeds the free text
now and ranks **all** visible candidates by proximity (since 0.19.2 without an upper limit); since 0.19.5 hybrid: the semantic and
full-text rankings are merged with Reciprocal Rank Fusion (k = 60), so that freshly learned items without a vector and exact terms
(error messages, options) are found. The duration and the number of hits found only via full text are in the result. Without configuration: steps skipped
by name, the tool refuses with a reason.


**Content as a router feature (since 0.16.0, `content.py`).** Nothing is embedded live. Sleep (step `7c_inhalt`) computes, for each trigger hashtag with at least 3 knowledge objects,
the centroid of their vectors and groups all knowledge objects with K-means (k = √(n/2), at most 40; name of a group = its most frequent hashtags). `vi_before` gives the model, per candidate,
`naehe` = cosine between the hint and the mean of the centroids of the current triggers (with the hint itself taken out) and `inhalt:<group>`. So the model also weights by content,
and a new hint inherits the weight of its group. `learning.CONTENT = False` switches this off for comparison.
## Images — with description and regions in the format of SAM 3 (since 0.35.0)

`images.py`. An image belongs to an insight (`erkenntnis`): `text` = what it shows in one sentence (the hint text, embedded like any
other), `inhalt` = the complete description, `daten.bild` = reference {`sha`, `mime`, `breite`, `hoehe`, `bytes`}, `daten.regionen` =
what is where. The bytes are in table `bild`, **content-addressed** by SHA-256 (the same image twice is stored once).

**Regions follow the output of SAM 3** (Meta, *Segment Anything with Concepts*, arXiv 2511.16719, github.com/facebookresearch/sam3):
SAM 3 is prompted with a concept — a short noun phrase such as "red plug" — and returns every matching instance with a mask, a box and a
score. One region per instance: `{"concept", "box": [x0, y0, x1, y1] (absolute pixels, xyxy), "score": 0–1, "mask"?: COCO RLE
{"size": [height, width], "counts"}}` (stored as `begriff`, `box`, `score`, `maske`). The VI **segments and describes nothing itself**:
the client (a person, a model with vision, a SAM 3 run) delivers, the VI checks, stores, finds and returns. From SAM 3 with Hugging Face
Transformers, roughly:

```python
from pycocotools import mask as rle                      # results = processor.post_process_instance_segmentation(...)[0]
regions = [{"concept": prompt, "box": [round(v, 1) for v in box.tolist()], "score": float(score),
            "mask": {"size": list(m.shape), "counts": rle.encode(np.asfortranarray(m.numpy().astype(np.uint8)))["counts"].decode()}}
           for m, box, score in zip(results["masks"], results["boxes"], results["scores"])]
```

**Checks (fixed rules, each refusal names its reason):** the type comes from the bytes (PNG, JPEG, GIF, WebP magic numbers), never
from the client's word; width and height from the header; at most 5 MiB per image (`IMAGE_MAX` — what fits base64-encoded into a request
of 8 MiB, and the largest image the Claude API accepts) and 2 GiB together (`TOTAL_MAX`, the database is backed up as a whole); every
box inside the image and not empty, score 0–1, mask size = [height, width], at most 200 regions. Regions are checked **before** the
bytes are stored: a refused image leaves nothing behind. No images without a token (open-wiki proposals are text), no image with `key`.

**Finding:** hashtags `medium:bild` and `zeigt:<concept>` per concept (lower case, blanks → `-`), so `vi_recall zeigt:red-plug` finds
every image showing one; the concepts are also in the full-text index. A hit line names the image ("image png 1024×768, 213 KiB,
3 regions (red plug ×2, network cable)"). **Returning:** `vi_object` sends the image as MCP content `{type: image, data, mimeType}`
next to the text, with every region; `image=false` leaves it out. **Writing from a file:** `vi-mcp image FILE --text … --hashtags …
--source … [--content-file F] [--regions F.json]` (an AI session runs it instead of pasting base64), `vi-mcp image get ID FILE` fetches
it back; both talk MCP to the server the clients use. There is one way in: `vi_learn` with `image`.

**Never onto the network:** `p2p` holds an object with an image back ("has an image (images stay on this server)") — the network
carries text, and what a photo shows is internal more often than its description suggests. Visibility is the object's: an internal image
is visible only with a token.

## P2P import — foreign knowledge only comes in checked

`p2p.py`, `checks.py`, `reviewer.py`. Foreign knowledge arrives as a signed logbook entry via the net service (see "Network — logbooks instead of bundles"), only source code and text as JSON. A torrent hash
proves that a file is unchanged, not who it comes from; that is what the Ed25519 signature provides.

| Layer | Effect |
|---|---|
| Logbook | chain, signature, membership by invitation, daily quota, fork. In the memory the signature is checked again. |
| Fixed rules | Only they reject for good: wrong kind, form, binary content, invisible characters. Instruction patterns are recorded as a finding. |
| Language model | Reads every object, may only tighten. Before every run a self-test with a known attack checks whether it holds. The model can be deceived and is therefore never the last authority. |
| Quarantine | Mode `quarantaene`: in no search, no hint, no edges, cannot be merged. |
| Release | Inconspicuous items by an instance with reflex permission. Reflexes, write access, rule findings and everything without a positive review verdict only with release permission (`vi-mcp release` on the server, token readable only by root). Afterwards mode `test`. |
| Effect | Imported items are text hints with visible origin, `herkunft:p2p` cannot be removed. Own namespace, no overwriting of local objects, no weight from foreign counters. Imported code only runs in the sandbox, may only be `vorher` (before) and never change arguments. Imported items are not re-exported. |

Limits: patterns and model do not recognise every attack. Whoever has root on the server can release. The reviewer instructions are deliberately not in the public repo (config `pruefer_prompt`).

## Network: anonymous and deletable

`anonymize.py` is the only pattern list for IPs, MAC addresses, internal domains, numbered host names, credentials, user names and proxy settings. Domains count as internal as long as they are not on the list
of public domains (`anonymize.PUBLIC`, extendable with `p2p.oeffentliche_domains`). The export additionally knows all host tags, instances, system accounts and `p2p.interne_namen`.

| Direction | Behaviour |
|---|---|
| Export | Text and source: replace, check again. Hashtags referring to places or persons are dropped. MCP server names are removed from tools. If a text talks about credentials, it stays at home. The result must pass the own import rules. |
| Import | Any finding in text, source, hashtags, triggers, steps, filter or code rejects the object. The report names only the class. |
| Local | Credentials with an unambiguous form are removed in `memory.new_object` (not from reflex source code). Host names and IPs stay local, the router needs them. |

Entries carry neither host names nor instance. The publisher is `vi-` + the first 12 hex digits of the SHA-256 of its public key.

**Right to be forgotten.** An instance without a net token distributes nothing. Per object: `netz_id = HMAC(token, "id|"+oid)[:32]`, `objekt_token = HMAC(token, "vergessen|"+oid)`, `loesch_hash = SHA-256(objekt_token)`.
The network sees `netz_id` and `loesch_hash`; the two cannot be linked to each other. `vi_net_forget` checks the instance token and only allows own objects. Revocations are separate logbook entries and prove themselves: deletion only happens if `SHA-256(token)` matches the `loesch_hash`. The recipient deletes object, tags, full text, edges, archive and vector and keeps a tombstone without content. If a revocation arrives before the object, the object stays away.
Abstractions derived by sleep from a deleted object remain.

## Network — logbooks instead of bundles

One logbook per server (`logbook.py`): entries with `seq`, hash of the predecessor, type (`objekt`, `widerruf`, `einladung`, `ausschluss`, `adresse` — object, revocation, invitation, exclusion, address), hash of the content, date, Ed25519 signature.
Header and content are stored separately: a revocation deletes the content, the chain stays verifiable. Two different entries with the same number are a fork; the publisher is no longer accepted afterwards.
Foreign entries are only accepted if chain, signature, membership, daily quota (5,000) and, for objects, the fixed rules including `anonymize.py` pass. An object that violates the rules is taken into the chain without content and counted as a violation.

The net service (`net_service.py`, systemd `vi-p2p`, own user, `InaccessiblePaths=/var/lib/vi-mcp`) does per round: outbox of the memory into its own logbook (`vi_net_outbox`), sync with up to 6 random peers
(exchange heads, fetch what is missing, push its own), new items to the memory (`vi_net_inbox`, instance `p2p`), nudge neighbours. Interval 300 s, a nudge wakes it immediately. Peers come from the start list and from `adresse` entries.
Every request carries `Authorization: VI-Netz <key> <time> <signature over method, path, time, SHA-256 of the body>`, valid for 300 s; only members get an answer, 240 requests per minute and key.
Unencrypted HTTP only to the own machine or with `http_erlaubt`. TLS is verified via the CA (`ca_datei`) or, if a pin is known for the address, via the SHA-256 of the certificate in DER form.
A pin only comes from a signed source: the `adresse` entry of the peer itself (field `pin`, since 0.15.0) or a join code. A `proxy` is used for foreign peers via CONNECT; `kein_proxy` exempts domains.
Joining: `vi-mcp net invitation` stores on a peerhost the SHA-256 of a random secret with an expiry time and prints a code (`vinetz1.` + Base64 of founders, address, pin, secret, expiry).
`vi-mcp net join` sets up the server and sends the secret to `POST /netz/beitritt`, signed with the new key (proof of possession, no membership needed, 10 attempts per minute).
If it matches, it is marked as used and the peerhost writes an invitation into its logbook. From 1,000 missing entries of one publisher, the service fetches finished segments (2,000 entries, JSON lines) via BitTorrent directly from the peer
(private, without DHT, LSD, UPnP); a segment with forgotten content is discarded.

In the memory (`p2p.py`) every signature is checked again, because the net service reads foreign data. `glauben` (believe) in `/etc/vi-p2p/config.json` limits whose objects get into the memory at all; revocations always apply.
Usefulness per publisher = beta mean of its hint counters; from 20 judgements and a mean < 0.3 its objects are no longer shown. `p2p.auto_freigabe` provisionally releases inconspicuous items during sleep.

## Housekeeping — the long-term archive

`archive.py`, sleep step 5. Entries no longer in use move to a separate file (`<db>-lager.db`, 0600), so that
the active store stays small. A stub remains in the memory.

| What | When (starting values, config `lager_tage`) |
|---|---|
| Experience | 30 days old, never retrieved, no evidence |
| Sleep report | 90 days old |
| Insight, rule, search, skill | 180 days neither retrieved, changed nor shown as a hint |
| Raw history of a conversation | 30 days after the last change, conversation not open |

Never automatically: self, model, questions, reflexes (that would silently switch off a behaviour), conversation summaries.
If archived knowledge matches an action, `vi_before` says so in one line. `vi_archive` shows status and content,
`vi_archive_restore(id, reason)` brings an entry back in its old mode. The deletion paths for conversations and instances also apply
in the archive. The main file is rewritten when more than 25 % is free. The periods are uncalibrated. *Observation point:*
how often `vi_archive_restore` is needed; frequent restoring means the period is too short.

## Reflection — the language model thinks during sleep (stage 4)

`reflection.py` (Park et al. 2023, 4.2): for each cluster without schema, sleep asks a local language model (config `llm`,
OpenAI-compatible, static system prompt, no `max_tokens`, thinking off) for **at most one** insight as
JSON (sentence ≤ 300 characters, ≤ 5 hashtags, ≥ 3 evidence numbers). The answer is **checked deterministically** — hashtags by
the TAG rule, evidence must be numbers from the cluster, instruction patterns ("ignore…", "execute …", "delete", shell,
Base64, password/token) lead to rejection with a reason in the report. Result: insight in mode `test`,
`herkunft:schlaf-llm`, evidence edges to every experience named; only effective after confirmation by another instance.
The template abstraction (step 4) remains the fallback for clusters without reflection. The model on the production host
answers in ≈ 1.7 s (measured 08.11.2026).

## Loop

Exactly one, every 60 s: delete answers older than 1 h · repeated errors → rule (test, idempotent) ·
save open conversations · idle → `abgelaufen` · WAL checkpoint. Errors are counted and shown in `vi_status`.

## Reflexes

Code in the memory that the VI writes for itself. Checked via AST: import whitelist
(`reflexes.REFLEX_MODULE`), no `exec`/`eval`/`open`/`getattr`/…, no dunder attributes; time limit 10 s; after 3
errors `defekt` (broken; named, unloaded).

**Sandbox (`sandbox.py`, since 0.9.0):** Every run is a separate process (`python3 -I -S`) that irreversibly restricts itself before compiling
the foreign code: Landlock (readable only `/usr`, `/lib`, `/lib64`, `/bin`; nothing writable or
truncatable; no TCP), seccomp (no `socket()`, therefore no UDP either; no `execve`, `fork`, `clone`, `ptrace`), limits for CPU,
memory, files; wall clock and output limit are enforced by the server. The sandbox assumes that the AST check
has failed, and also protects `vi.db`, although the child runs as the same user. If it cannot be established
(no Landlock ABI ≥ 4, not x86_64), the code does **not** run (`isolation: keine`). Cost: ≈ 14 ms per run
(measured 08.11.2026). Only instances with `reflexe: true` may learn or switch reflexes.

## Open-wiki mode

`"offen": true` assigns requests without `Authorization` to the fixed instance `offen` (`config.OPEN`, reserved as a name). A wrong token stays 401.
`offen` only sees the tools in `tools.OPEN_ALLOWED`: reading, `vi_before`/`vi_after`, `vi_learn`. A `vi_learn` from `offen` becomes an object in quarantine with
`herkunft:offen`, a rule finding (`checks.directives`) and a pending review; it goes through the same path as a network import (`p2p.sensitive`, `p2p.approve`, `p2p.auto_approve`).
`offen` has no answer store: all guests share one instance, remembered answers would give a colleague's result to everyone.
Remaining limit: guests' actions flow into the hint counters and the router training. A guest can thus influence the order of checked hints, but cannot bring in content.

## Protection

- Bind `127.0.0.1` (default). Other hosts only via a TLS proxy.
- **Bearer token per instance**; the configuration only contains the SHA-256, compared with `hmac.compare_digest`.
  The instance becomes the owner: hashtag `instanz:<name>` on conversations, experiences, learned items; `wer = ki@<instance>`.
- **Origin check** (protection against DNS rebinding, MCP spec): foreign origin → 403.
- A session belongs to its instance: foreign session id → 404.
- **Local socket instead of a token (0.36.0, Linux):** the service also serves `/mcp` on a Unix socket (config `socket`, the package
  sets `/run/vi-mcp/mcp.sock`). The socket is open to everyone (0666), but the kernel names the connecting user (`SO_PEERCRED`), and
  only users listed in config `lokal` (`vi-mcp local USER INSTANCE`) get in, each as its instance — with its visibility, internal
  knowledge included. Others get 403 with the command that would allow them. Whoever can log in to the server host as that user is
  trusted as that instance; that is the same trust as a token file readable by that user, without a token to copy around. Not on
  Windows (no `SO_PEERCRED`); not reachable from containers unless the socket is mounted.
- Database, configuration, token file: `0600`, directories `0700` — the memory contains conversation histories
  and tool results, which can contain credentials.

## Protocol

MCP "Streamable HTTP" (https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):
`POST /mcp` (single or batch; only notifications → 202), `GET /mcp` → 405 (no server push), `DELETE /mcp`
ends the session. Answers as `application/json`, no SSE. Protocol versions 2025-06-18, 2025-03-26,
2024-11-05 (the requested one is returned, otherwise the newest). Tool errors come as a result with
`isError: true` and a reason ("abgelehnt: …" — rejected), protocol errors as JSON-RPC errors.

**stdio (0.36.0):** `vi-mcp stdio` is a bridge, not a second server: it reads one JSON-RPC message per line from stdin, sends it as
`POST /mcp` over the local socket, and writes the answer as one line to stdout (only JSON-RPC there; notes go to stderr). So there stays
one process that writes the memory. If the service restarted (404, session unknown), the bridge repeats the client's `initialize` once
and resends; at the end of stdin it ends the session (`DELETE`). A refusal or a service that is not running comes back as a JSON-RPC
error with the reason.

## Logic check (according to CLAUDE.md)

| Rule | Implementation |
|---|---|
| Identity | one memory, one process, one loop; one serial number per conversation; terms in code = docs = tool texts |
| Non-contradiction | reason is checked before the change (a rejection changes nothing); counters atomic; writing tools never from memory |
| Complete case distinction (excluded middle for cases, not truth values — three-valued, Kleene K3) | `ok:ja/nein/unbekannt`; conversation states and modes exhaustive; before without after is stored, not discarded |
| Sufficient reason | every rejection names the reason; every change carries reason and owner; hints name their source; loop errors in the status |
| Intension/extension | rule/search/reflex (target) separated from experience/conversation (actual); origin via `instanz:` and `aenderungen` |

## Origin

The core comes from the VI part of a stdio MCP skill server (version 3.0.0, 08.11.2026), built into a
skill server there: the VI wrapped itself around every tool call. Here it is **standalone**: it loads no
foreign tools, but gets actions reported via `vi_before`/`vi_after` — from every client that wants to.
Adopted ideas and sources: Generative Agents (Park et al. 2023), A-Mem (Zettelkasten linking),
filter language `art:wert`. Changes compared with the original: see [CHANGELOG.md](../CHANGELOG.md).
