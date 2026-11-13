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
> values (`geteilt`, `intern`, `privat`, …), object kinds (`erkenntnis`, `erfahrung`, `regel`, …) and the P2P wire format — so existing
> databases and peers keep working. The configuration files are English since 0.51.0 (keys and network kinds `free`/`open`/`company`); the
> German keys of older files are still read (`config.normalize`, `net_service.english_file`) and rewritten in English at package install. The MCP interface (tool names, parameters, enum values) is English since
> 0.22.0; the German names are accepted as aliases and English enum values are translated to the stored German values (`api_en.py`).

**Everything is an object** (`memory.MemoryObject`, table `objekt`; mapping without an ORM): fixed fields `id`, `art` (kind),
`zeit` (time); changeable only through methods — `tag`, `confirm`, `refute`, `link`, `access` —, each with an
entry in `aenderungen` (who, when, **reason — mandatory**, checked before the change). The history keeps 50
entries; older ones are truncated **with a count** (`daten.aenderungen_gekuerzt`, shown in `vi_object`).

| Kind | What for | Created by |
|---|---|---|
| `erfahrung` (experience) | every reported action: tool, arguments, duration, `ok:ja`/`ok:nein`/`ok:unbekannt`; `daten.vorher` = memory access before it; **importance from surprise** (`ueberraschung:neu` 3 · `wiederholt`/`erholt` 2 · `chronisch` 1 · `keine` 0 — prediction error as a learning signal, docs/FORSCHUNG.md A7) | `vi_after`; `vi_before` with a remembered answer; before without after (session end/1 h) |
| `antwort` (answer) | remembered result of a **read-only** call (`frage:<hash>`), valid for 120 s (configurable per tool, max 1 h) | `vi_after` |
| `erkenntnis` (insight) | something learned, with source and importance 0–3; with `key` (0.23.0) **one object per recurring finding**: the same key from the same instance updates it (`daten.key`, `daten.repeats`, earlier states in `daten.history`) instead of adding a new one; (an image is its own kind `bild` since 0.37.0) | `vi_learn` |
| `regel` (rule) | condensed: same error ≥ 3× in 24 h, mode `test` | loop |
| `reflex` | Python code: kind `werkzeug`, `vorher`, `nachher` (MCP: `tool`, `before`, `after`) | `vi_reflex_learn` |
| `suche` (search) | mnemonic: name, filter, **triggers**, story | `vi_learn_search` |
| `gespraech` (conversation) | one session, serial number `YYYYMMDDNNN`, summary + hashtags; history zlib-compressed in `gespraech_roh` | `initialize` |
| `frage` (question) | question from one instance to another or to all; states `offen`/`zugestellt`/`beantwortet`/`abgelaufen` (open/delivered/answered/expired) | `vi_ask` |
| `skill` | solution path: problem (triggers), steps, instructions, versions, evidence; modes `test`/`aktiv`/`strittig`/`aufgegangen` (merged) | `vi_solved`; sleep (success after errors) |
| `selbst` (self) | `selbst:kern` = the self (target/actual/narrative, versioned); otherwise proposals for the target (mode `test`) | start / `vi_self_propose` |
| `bild` (image, 0.37.0) | an image with its key statement (`text`), full description (`inhalt`), `daten.bild` (reference into table `bild`) and `daten.regionen` (SAM 3 format); hint before matching actions | `vi_learn` with `image`, `vi-mcp image` |
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

## The memory index — pushed like a MEMORY.md (since 0.38.0)

`index.py`. A file memory of a single assistant works because nobody decides to look into it: its index is in the context from the first
message, one line per entry, and an entry is read when its line fits. The VI only had the pull side — `vi_recall` — and was consulted
before 63 % of changing actions (`vi_stats`, 7 days to 10.11.2026). So `initialize` appends a short index to the instructions, per
instance, after the rules (a client that cuts long instructions loses the index, not the rules):

| Section | What | Order |
|---|---|---|
| Requirements and decisions | objects with `thema:vorgabe` — rule 6 asks for this hashtag on what the user requires or decided beyond one session | newest first, 8 |
| Proven or most used | knowledge with a confirmation, then by accesses; bulk imports (manuals, Confluence, Stibo, log findings, network) excluded | 6 |
| Learned by this instance recently | its own knowledge, imports excluded | newest first, 6 |

One line per entry (`- [id] text`, at most 110 characters, images marked `image:`), at most 2,000 characters together — Claude Code is
reported to cut server instructions at 2,048 characters in some versions (GitHub issues; not in its documentation; in the version used
on 10.11.2026, 3,853 characters arrived complete). A cut is named. Only active objects the instance may read; without a token only
shared ones. The index never breaks `initialize`: on an error it is left out.

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

`privat` (private: only the owning instance), `geteilt` (shared: everyone, including the tokenless instance `offen`, and every network), `intern`
(internal, since 0.20.0: all instances with a token, never `offen`; never an open network — since 0.39.0 a company network (kind `company`)
carries it to its members, `p2p._collect` takes `intern` only there). For company knowledge
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
- **Taught through labels; an LLM weight layer only after measurement** (0.29.0, changed 0.58.0 on the user's decision "hybrid — unser
  scikit-learn-Stack und dann die KI"). The labels (scorer verdicts, direct feedback) train the fitted weights. On top, the language model
  may propose a small layer (`weight_writer.py`): deltas |Δ| ≤ 1 or deletions, only for features the audit flagged or for new hints the fit
  has not seen; stored beside the fitted weights (`llm_schicht`), so the daily fit does not overwrite it; acting only after an offline gate
  (paired log loss and ranking utility with/without, on the holdout — the card the model sees holds only numbers from the training part)
  and a randomized online test (20 % of actions, arm `vorher.arm`); re-checked daily. "Language-model verdicts only tighten" stays for
  releases and reviews; for weights the rule is "acts only after measurement". Before 0.58.0: writing weights from outside would not have
  survived the next training and would have replaced measurement with opinion — the layer answers both. Weights are read: `vi_why` lays open one
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

## Indexes — projects and special VIs (0.61.0)

The user wanted indexes "like OpenSearch" — for projects and to train a special VI — and a primary key: every object belongs to
exactly one index (column `objekt.idx`, default `global`), and the indexes themselves stand in table `vi_index` (name = primary key,
kind `global`/`projekt`/`spezial`, description, tags). An added column cannot become a real foreign key in SQLite without rebuilding
the table, so the reference is kept by the code (`memory.save` registers an index on first use) and checked by a test. The column is not
a hashtag on purpose: no export form, web page or content hash carries it — a project or customer name never leaves the server.

- **Which index:** an explicit `index` wins (`vi_learn`, `vi_recall`); else the project of the session — the hook sends the working
  directory, `indexes.from_project` maps it (config `indexes.map`, `indexes.ignore`; the home directory, hidden and temporary
  directories are global). `session.on_behalf` makes it the current index, so experiences and knowledge of a hook session land there.
  The agent's own MCP session does not know its directory: the hook calls `vi_context` right before `vi_learn`/`vi_recall`, and the
  call that follows within 15 s takes that project. Rejected: changing the tool input in the hook (`updatedInput`) — in auto mode
  Claude Code may deny a changed call, and with `allow` the hook would approve calls on its own.
- **Effect — Vorrang, kein Ausschluss:** in a project its index comes first — in `vi_recall` after rank fusion and reranker (before
  them it would be lost), in the hints before an action right after "important and matching", in the prompt hints at equal score.
  General knowledge stays visible; `vi_recall(index=…)` searches one index alone (`memory.search_index` in `_filter_sql`, so full
  text and hybrid search obey it alike). `vorher.idx`/`idx_vorrang` record it.
- **Special VI:** an index with ≥ 300 observations and ≥ 30 failures gets its own router model (`learning.train_index`, sleep step
  `8d_index_modelle`), compared on the index's newest observations with a shared reference fitted on everything except that holdout
  (a shared model trained on everything would know it — leakage). It ranks the project only if better by more than 2 standard errors
  of the paired log loss. *Measured on a production copy (13.11.2026):* the largest index (vi-mcp, 2,610 observations, 79 failures)
  was worse than the shared model (AUC 0.29, +0.427 ± 0.023 log loss) and stays with the shared one — the gate does its job.
- **Code in the index:** `vi-mcp index import-code REPO --index X` (vi_mcp/code_import.py) runs where the repository is and sends the
  versioned code of the current commit over MCP (`vi_code_sync`): Python by `ast` into functions and classes, other text in blocks;
  only changed files (blob SHA); pieces that are gone are archived. Pieces are internal, never a router or prompt hint; before
  Read/Edit/Write the file line names what the index holds of the file; outside its project, code of other indexes is hidden in
  `vi_recall` (counted).

## Index files — the same content measured in two places (0.62.0)

The user: "Der Export oder Import von Projekten kann uns beim Scoring der Inhalte helfen. So können wir vergleichen." `index_transfer.py`
adds no second mechanism; it reuses the network's: content hash, holders and ratings (`net_score`), the internal export form of a company
network (`p2p.internal_form`) and the import path fixed rules → quarantine → reviewer → release (`p2p._create`, channel `datei`).

- **Export** (`vi-mcp index export INDEX FILE`): knowledge of one index (kinds of `p2p.EXPORT_KINDS`, shared or internal, active) with this
  server's own measurement per content (`net_score.own_measurement`: hint bandit, confirmations, refutations). Never private objects,
  experiences, conversations, code pieces; skipped objects are counted with their reason. Signed with Ed25519 (`export.key` in the
  network directory, `VI_MCP_EXPORT_KEY` overrides). The file is internal — company knowledge unanonymised, like a company network —
  but carries no instance, conversation or object id.
- **Import** (`vi-mcp index import FILE --as INDEX`): signature first, nothing is stored before it holds. The content hash is computed
  here (never taken from the file). A content this memory has (`net_score.find`, then `find_local`) is no second object: only the
  exporter's measurement becomes a rating (`p2p_bewertung`, `netz = 'datei'`). A new one goes into quarantine in the target index,
  internal. A file from this server is refused: a server does not rate itself, and one object stays in one index.
- **Way back:** the target exports in turn, the origin imports — its own contents get the target's measurement as a foreign rating.
- **Comparison** (`vi-mcp index compare INDEX`, sleep step `8e_index_vergleich`): per content and exporter, success `yes/(yes+no)` on both
  sides with its 90 % beta interval, at least 10 observations per side. Classes (exhaustive): `allgemein` (both lower bounds > 0.5),
  `nur_ursprung`, `nur_ziel`, `schwach` (both upper bounds < 0.5), `unentschieden`, `zu_wenig`. A content good only at its origin loses
  the project priority at the target (`daten.vorrang_aus`, one rule for hints, prompt hints and `vi_recall`: `indexes.first`) and gets it
  back when a later comparison no longer says so. Ratings from files count in the network score but never hide an own object: knowledge
  that fits only here must not vanish here.

## Total effect of hints — held back at random (0.61.0)

The randomized ε-exploration measures the choice of hints (ranked against random). Whether showing hints at all raises the success of an
action cannot be read from actions with and without hints — hints appear on the hard ones (matched lift −1 point, 12.11.2026). So on a
random `hold_back` share (default 5 %) of the actions that have hints, the hints are held back (the risk warning stays; the answer does
not say it); `vorher.zurueckgehalten` and `haltewahrscheinlichkeit` record it, `metrics.holdback_effect` compares (Mantel-Haenszel
within instance and tool, verdict only beyond 2 SE). A difference of a few points needs a few hundred held-back actions: weeks.

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

`images.py`. An image is a memory of its own kind, **`bild`** (since 0.37.0; 0.35.x stored it as `erkenntnis` with `medium:bild`, the
migration changes kind and hashtags and keeps the id): `text` = what it shows in one sentence (the hint text, embedded like any
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

**Finding:** `art:bild`, and `zeigt:<concept>` per concept (lower case, blanks → `-`), so `vi_recall zeigt:red-plug` finds
every image showing one; the concepts are also in the full-text index. A hit line names the image ("image png 1024×768, 213 KiB,
3 regions (red plug ×2, network cable)"). **Returning:** `vi_object` sends the image as MCP content `{type: image, data, mimeType}`
next to the text, with every region; `image=false` leaves it out. **Writing from a file:** `vi-mcp image FILE --text … --hashtags …
--source … [--content-file F] [--regions F.json]` (an AI session runs it instead of pasting base64), `vi-mcp image get ID FILE` fetches
it back; both talk MCP to the server the clients use. There is one way in: `vi_learn` with `image`.

**Before actions:** an image is a hint candidate like an insight (same triggers, same ranking, bandit and router): before a matching
action the client gets "Image [id] …: what it shows — image png 1024×640, 2 regions (…); vi_object <id> shows it". **Screenshots:** the
rules tell the AI to save one when it shows what text would lose (an error dialog, a UI state, a configuration screen, a graph) — taken
with its own tools (e.g. Playwright `browser_take_screenshot`) and stored with `vi-mcp image`; never with passwords or tokens on screen.

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
| Effect | Imported items are text hints with visible origin, `herkunft:p2p` cannot be removed. Own namespace, no overwriting of local objects, no weight from foreign counters in training (0.40.0: foreign ratings get capped, aggregated weight in the network score — shown, and hiding a hint — see "Network score"). Imported code only runs in the sandbox, may only be `vorher` (before) and never change arguments. Imported items are not re-exported. |

Limits: patterns and model do not recognise every attack. Whoever has root on the server can release. The reviewer instructions are deliberately not in the public repo (config `reviewer_prompt`).

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

**Several networks (0.39.0).** One net service per network: `vi-p2p` is the network `standard` (config `/etc/vi-p2p/config.json`,
memory instance `p2p`); every further one runs as `vi-p2p@<name>` with `/etc/vi-p2p/<name>.json`, `/var/lib/vi-p2p/<name>/` and the
memory instance `netz-<name>`. The kind is set in the memory (`p2p.netze`: `{name: {art, instanz}}`), never by the service, because the
service reads foreign data: `open` exports only `geteilt`, anonymised; `company` exports `geteilt` and `intern` unanonymised
(`p2p._company_form`), imports become `intern` with the fixed hashtag `netz:<name>`, and `!herkunft:p2p` keeps them out of every export.
`netz_id` and object token are derived per network (`HMAC(token, "id|<netz>|"+oid)`; the network `standard` keeps the form without a
scope, so existing entries stay revocable). The service's own relay check (`Logbook(internal_ok=…)`, `checks.check(internal_ok=…)`)
follows its configured kind; the memory checks again with the kind it knows.

**Forward compatibility (0.39.0).** An entry of an unknown type (`[a-z_]{2,20}`) is accepted when signature, chain, membership and quota
hold; its content is checked against checksum and size only, stored, relayed and counted (`unbekannte_typen`), but has no effect.
Up to four extra header fields and extra fields in `adresse` are tolerated likewise; `einladung`, `ausschluss` and `widerruf` stay
exact. `/netz/health` reports the version; `peer.version` keeps it, and `Logbook.peers_below(v)` names the peers that would not yet
understand a new type — new types are written only when that list is empty. With every outbox call the service sends a snapshot
(peers, versions, backlog both ways, transport counts); the memory keeps the last one per network (`netz_stand`) for `vi_net_status` and
section W of `vi_stats`.

In the memory (`p2p.py`) every signature is checked again, because the net service reads foreign data. `glauben` (believe) in `/etc/vi-p2p/config.json` limits whose objects get into the memory at all; revocations always apply.
Usefulness per publisher = beta mean of its hint counters; from 20 judgements and a mean < 0.3 its objects are no longer shown. `p2p.auto_freigabe` provisionally releases inconspicuous items during sleep.

## Network score — the same information on several servers (0.40.0)

`net_score.py`. **Content hash** = SHA-256 over `{art, text, inhalt, hashtags sorted}` (plus filter, name, steps for searches and skills),
whitespace normalised in text, line ends and trailing blanks in content; without `netz_id`, `loesch_hash`, `zeit`, `quelle`. Computed by the
receiver, never taken from the sender.

**Holders.** `p2p_halter(inhalt_sha, pub, netz, netz_id, seq)`: every publisher whose objekt entry carries the content. `p2p_inhalt(inhalt_sha → oid)`:
the one object for it — an import, or an own object of the same meaning (found by exact text, confirmed by the hash). A second arrival
adds a holder line (`dedupliziert`), a revocation removes one (`drop_holder`); the import goes with its last holder, an own object never.

**Ratings.** Logbook type `bewertung` `{ziel, gezeigt, ja, nein, bestaetigt, widerlegt}` (`logbook.valid_rating`, exact fields, numbers
0–1e6): this server's own measurements of an import (bandit counters, confirmations and refutations by its instances). The network
service writes a rating only when it changed, once per content and day, at most 1,000 a day, and only while `peers_below("0.39.0")` is
empty (older peers would reject the type). The memory keeps the latest per rater and content (`p2p_bewertung`, by `seq`).

**Score.** yes = ja + bestaetigt, no = nein + widerlegt per rater; scaled to at most `CAP` = 20 observations; weighted by the rater's
publisher benefit (`publisher_value`, 0.5 unknown); holders' ratings of their own content left out; this memory's own measurement of an
import as one more rater. Score = (1 + Σ w·yes) / (2 + Σ w·(yes+no)), 90 % interval from the beta distribution (scipy; normal
approximation without it). `ausgeblendet` = at least 20 observations and score < 0.3 → `p2p.without_blocked` drops it from hint candidates.
The router (learning.py) never sees foreign counters.

## Network wiki — pages without a master (0.41.0)

`wiki_merge.py` (pure), `wiki.py` (memory side), logbook type `seite`.
- **Revision.** Content `{seite, titel, text ≤ 64,000, eltern ≤ 8, hashtags, quelle, notiz, geloescht, netz_id, loesch_hash, zeit}`
  (`checks.PAGE_FIELDS`), id = SHA-256 of the content (the header's `sha`). A revocation (`widerruf` on its `netz_id`) deletes the text;
  the revision keeps its place in the graph (status `vergessen`).
- **Multi-master without coordination.** Every server appends only to its own logbook; the revisions of a page form a grow-only set
  over a DAG.
- **View** (`wiki_merge.view`):
  - Heads are the accepted revisions without an accepted descendant.
  - Several heads are folded in id order with `merge3`, a three-way merge of paragraph lists (difflib opcodes against the deepest
    common ancestor, ties by id).
  - Overlapping hunks, and insertions at the edge of the other side's change, form a cluster. Equal results merge; different ones are
    a `Conflict`. Neighbouring paragraphs merge.
  - Conflict markers carry revision ids only (author labels differ per server); the authors are named in the page header.
  - The result is a view, not a revision, and is equal everywhere for equal sets.
- **States of a revision** (exhaustive): `ausstehend` (waiting for review), `frei` (counts), `verworfen`, `vergessen`.
  - Own revisions are `frei` at once.
  - A foreign one becomes a quarantine object `seite:rev-<id>` (content: the unified diff to its first known parent, so the reviewer
    reads what changed), and goes through `reviewer` → `p2p.approve`/`discard` → `wiki.on_release`. The released object becomes
    `aufgegangen` (merged into the page).
- **Page object** `seite:<netz>:<slug>`, kind `seite`:
  - It is rebuilt on every change (`materialize`): text = title and first paragraph, content = header line + view.
  - It is in mode `test` while a head is foreign, `intern` in a company network, and is deleted when the page is deleted.
- **Transport.** The network service writes own revisions once (by checksum), oldest first, and only while `peers_below("0.39.0")` is
  empty. Logbooks of 0.39.0 and 0.40.0 already relay the type unread.

## Live search (0.42.0)

`p2p.live_search` → network service local listener `POST /lokal/suche` (127.0.0.1, bearer token whose SHA-256 is in the service
config as `lokal_token_sha256`; the token is in the memory config `p2p.lokal` / `p2p.netze.<n>.lokal`) → `NetService.search`:
`POST /netz/suche {q, max}` to every peer with an address (at most `SEARCH_FANOUT` = 20, `SEARCH_TIMEOUT_S` = 5, parallel, no
forwarding) → the member's service (`authenticate`, then `SEARCHES_PER_MIN` = 30 per key) → its memory `vi_net_answer_search`
(`p2p.answer_search`: the query reduced to words, `!herkunft:p2p`, visibility and mode as `_collect` for that network without
"proven", export form via `_export_form`) → each hit signed with the member's key. The asking service drops hits whose signature
does not match or whose sender is no member; the memory checks the signature again, applies `checks.check`, merges by content hash
and keeps the hits in process memory for an hour (`_live`), nothing in the database. `take` creates the quarantine object as an
import (`_create`, `herkunft:live`, holder line, `p2p_netz`). Counted in `netz_suche` (searches, takes) and the service snapshot
(answered, refused).

## News without waiting for the round, relayed live search (0.52.0)

Shape it is built for: a peerhost that knows nothing itself and peers behind firewalls (mode `peer`) that hold the knowledge. BitTorrent
keeps connections open and announces a new piece at once (`have`, BEP 3); a peer behind a firewall can only connect out (BEP 55 punches
holes over UDP, which corporate firewalls with HTTPS proxies usually do not allow). So the peer connects out and keeps the request open:

- **Long poll.** `NetService.wait_loop` (mode `peer` only, started by `main`) keeps one `POST /netz/warten {koepfe, max_s}` open at the first
  reachable peerhost (`wait_targets`). The peerhost (`wait_for`) answers at once if its logbook holds entries the caller lacks (`_news_for`
  compares heads) or a relayed search waits for it, otherwise it waits on a condition up to `WAIT_MAX_S` = 50 s (below the 60 s many proxies
  allow; the nginx snippet sets `proxy_read_timeout 120s`). At most `MAX_WAITERS` = 500 open waits; beyond that `voll` and the peer
  retries in 10 s. On news the peer reconciles with that peerhost at once (`wait_once`, under the round lock) and hands the entries to its
  memory. A peerhost without the endpoint (404, older than 0.52.0) is left to the rounds for an hour (`_no_wait`).
- **Signals.** `_signal` wakes all waits: after `POST /netz/eintraege` with new entries, after a round that brought something new, when a
  search is queued, at stop. The memory calls `POST /lokal/anstoss` (`p2p.nudge_service`) after a question, an answer or a wiki revision,
  so it goes out at once. A round always includes the peerhost of the long poll (`_wait_target`). `tick_s` = 300 stays as the fallback.
- **Relayed live search.** A peerhost answering `POST /netz/suche` also calls `relay_search`: the search goes to the peers waiting at it or
  whose wait ended less than `RECONNECT_S` = 5 s ago, without the asker; they get it in their long poll, answer from their own memory with
  their own signature (`POST /netz/suche/antwort`, accepted only from a peer the search was given to) and the peerhost returns them as
  `weitergeleitet` after at most `RELAY_WAIT_S` = 3 s, with `weitergeleitet_an` and `ohne_antwort`. One hop: a peer answers, it never relays.
  The asker verifies every relayed hit against its author's key (`search` → `verified`), so a peerhost cannot forge one; it also searches
  its own waiting peers when its own memory asks.
- **Questions released after review** (`forum.release_questions`, after `reviewer.work_off` in `p2p.review_and_release` and in sleep): a
  quarantined question from the network whose review is done, without rule findings or reviewer doubts (`p2p.sensitive`) and from a
  publisher not blocked is approved by `vi`. Answers keep the full path. Without a reviewer a question waits for `vi_release`.

## Conversations between AIs in the network (0.43.0)

`forum.py`, logbook type `beitrag` `{faden, eltern, art (frage|antwort), text, inhalt, hashtags, reize, autor, netz_id, loesch_hash, zeit}`
(`checks.POST_FIELDS`, `checks.check_post`). A post's id is its SHA-256; a question has neither `faden` nor `eltern`, an answer
names both.

**Outgoing.** `vi_ask(to="netz[:<name>]")` → local `frage` object (`an = netz:<name>`, never delivered locally) + `beitrag_aus`.
`vi_answer` on a question with `beitrag.richtung = ein` → an `antwort` post.

**Incoming** (`forum.ingest`, called by `p2p.inbox`):
- A question becomes a quarantine `frage:post-<id>` (`an = alle`, `von = <autor>@<netz>`). After release it is mode `aktiv`; it is not
  knowledge, but a question for the local AIs, delivered by `questions.deliver`, which skips quarantine and refuted ones.
- An answer is kept only if its `eltern` is an own question. It becomes a quarantine `erkenntnis:post-<id>` with a content hash and a
  holder line. After release (`forum.on_release`) it is appended to the question's `antworten` with `objekt`, and stays mode `test` as
  every import does.
- Confirmations of such an answer are this server's own measurements, so `net_score.outgoing` publishes them as ratings.

**Authors.** In an open network `ki-` + HMAC(network token, "autor|"+network)[:10]; in a company network the instance name.

**Bounds.** `MAX_OPEN_PER_INSTANCE` = 20, `net_service.POSTS_PER_DAY` = 200; written only while `peers_below("0.39.0")` is empty.

## Memory for every prompt (0.44.0)

`intuition.prompt_hints` behind the tool `vi_prompt_context`:
- `prompt_words` takes up to 20 words of at least three characters, without stop words (German, English) and pure numbers.
- `g.recall` over the knowledge kinds runs with the OR fallback (BM25), with the asking instance as viewer.
- Lexical gate: at least two prompt words (one if there is only one) must appear in text or hashtags.
- Left out: disputed and refuted items, unconfirmed sleep hypotheses, quarantine, blocked publishers, ids already shown (the hook keeps
  them per session, at most 200).
- Hits are not reinforced. The server keeps nothing of the prompt; the usage row has no arguments.

Clients:
- Claude Code: `UserPromptSubmit` → `hookSpecificOutput.additionalContext`.
- Hermes: shell hook `pre_llm_call` → `{"context": …}`; it reads the message from `extra.user_message`.

## Free network (0.45.0)

`art: frei` in the service config and in `p2p.netze`. `Logbook(free_bits=…)`:
- Membership = the keys whose entry 1 is a valid `identitaet` with at least `free_bits` (`lb.pow_ok`: SHA-256(pub ‖ nonce as 8 bytes)
  starts with that many zero bits), minus `Logbook.blocked`. No founders, no invitations, no exclusions for everyone.
- `ingest` lets entry 1 of an unknown key through only if it is that identity; everything else of a key without one is "no identity
  proof known".
- Daily quota per publisher from `quota_of`: `NetService._quota` gives `quote_neu` (100) to unknown publishers and `MAX_PER_DAY` to
  those in `trusted`.
- `trusted` and the blocked keys come from the memory (`p2p.trust`: at least 20 judgements and mean ≥ 0.6, or blocked by
  `publisher_value`) plus `sperren` in the config.

Requests:
- Signed as always, but no membership needed. Limited per key (240/min) and per client address (600/min), refused for blocked keys.
- `reconcile` fetches every key not blocked; its entry 1 is checked on arrival. Afterwards `exchange_peers` asks `GET /netz/peers`
  (addresses reached in 7 days, own address first) and remembers new ones (at most `PEERS_MAX`).
- `_public_target` refuses targets resolving to private, loopback, link-local, reserved or multicast addresses unless `privat_erlaubt`.

`ensure_identity` makes the identity entry 1 at the first start (refuses on a logbook that already has entries).

## Vocabulary — the words of the AI language (0.62.0)

`vocabulary.py`. The words of the search language are the hashtags `kind:value` the memory holds; this module counts them over what the
asking instance may see (`memory._filter_sql` — the same visibility as search; bookkeeping kinds such as `instanz:` are not vocabulary).
`vi_vocabulary` lists kinds, values and completions; the internal search shows them as a page and as a `<datalist>`. A search without hits
is classified by `empty_reason`: `unbekannt` (a hashtag no visible object carries, or free text none of whose words occurs — the full-text
search already fell back to OR) or `verfehlt` (all words known, not together); the answer names it, `nutzung.leer_grund` records it for
`vi_stats` E. Suggestions compare the first label of a value first, so host names that only share a domain are not "close". The tool
takes the visibility from the calling instance, not from the session context alone — without a session that would be the server's view
of everything (found by the test of a private host name).

## VIL — the AI language, symbol layer (0.62.0)

`vil.py`. Design (README): a readable symbol layer — speech act plus words — over a weight layer — vectors and measured weights per word,
exchanged as measurements, each server training its own. Research behind it (13.11.2026): speech acts (Searle; FIPA SC00037), evidentials
(WALS 78, Lojban CLL 13.11), the failure of the 1990s agent languages on agreed meaning (Singh 1998) — here meaning is what is measured;
weight-only languages work only between identical base models and leak content (vec2text), so the symbol layer stays readable.
- `parse` (pure, tolerant): `ACT[.TYPE] WORD…`; no known act → an ordinary filter, untouched. Short forms `@`, `#`, `since:`.
- In `tools.search`: only `ask` runs; the question type re-sorts hits stably by `PRIOR` (a fixed prior), recency drops older hits,
  counted. The raw utterance stays in `suche_log`, so every question's type is there to learn from.
- `tell_line`: memory (from the kind until labels exist), evidence (measured · documented · hearsay · inferred · unknown — a named
  state), weight = beta mean of helped/not helped with its count, source.

## Incubator and training data (0.62.0)

The goal the user set: "Wenn eine VI aus dem Inkubator kommt, soll man damit dann eine KI fine-tunen." — decided as a maturity phase with
measurement. `incubator.py` measures seven required criteria (knowledge, checked share, search MRR, router AUC, no harm from hints,
labels, training data) plus an informative one (refuted knowledge marked, not deleted); each criterion is `erfuellt`, `offen` or
`nicht_gemessen` — unmeasured never counts as met. `hatch` refuses an immature VI with the open criteria (or exports with `--force`, and
the datasheet says so). `dataset.py` writes the data: `qa` (SFT), `kto` (binary helped/not helped — Ethayarajh et al. 2024 take exactly
this signal), `dpo` (pairs under one trigger), from shared and internal knowledge and the aggregated hint counters — never private
objects, experiences or conversations. The targets of the fixed question set are held out (contamination guard), every text is scrubbed
again and the changes are counted, and `DATASHEET.md` records composition, exclusions, versions, label quality and gaps (Gebru et al.,
Datasheets for Datasets). vi-mcp itself still trains no language model; the export is the input of a fine-tuning.

## Internal knowledge search (0.62.0)

The user: "Mache die Prod-Oberfläche aktiv, ich möchte wie bei Wikipedia darin suchen können" — decided: internal, with sign-in. The
public page `/web` stays as it is (never internal knowledge); `web_internal.py` is a second, separate page under `/intern`.
- **Sign-in:** the token of an instance, checked by `config.instance_for` like `/mcp`; the session is a random id in a cookie
  (`HttpOnly; Secure; SameSite=Strict; Path=<web_internal_base>`, 8 h), the instance name lives only in the server process. The POST must
  come from this site (`Origin` equal to `Host`/`X-Forwarded-Host` or in `origins`; `null` is refused). The pages send
  `Referrer-Policy: same-origin`: with `no-referrer` (as on `/web`) Chrome sends the sign-in with `Origin: null` — found in the browser
  test, invisible to unit tests that set the header themselves.
- **One search path:** `tools.search` is the core of `vi_recall` (full text, meaning, rank fusion, reranker), taken out of `_recall` so
  the page and the MCP tool give the same hits; the page reads only — no reinforcement, no search log with the query. Visibility is that
  of the signed-in instance; then private objects (also its own), quarantine and non-knowledge kinds are dropped and counted under the
  hits ("N not shown (private)").
- **Pages:** home (search, indexes, recently learned), search, article (content, facts with measurements and network score, related,
  history), index (description, counts, model, index-file comparison). Server-side HTML, no script, CSP of `/web`, `Cache-Control: no-store`.

## Web page (0.46.0)

`web.py`, served by the memory server under `/web` when the config says `web: true`; links use `web_base` (the path the browser sees).
- **What may appear** (decided by the user: read-only, only free and open networks):
  - page views of networks of kind `free`/`open`;
  - their forum threads (questions sent from here or received and released, with the answers this server holds);
  - released imports of those networks (mode `test`/`aktiv`, visibility `geteilt`, not forum answers);
  - this server's own knowledge in exactly the export form the network gets (`p2p._collect`, cached 300 s).
- **What never appears:** company networks, internal or private objects, anything in quarantine. Local instance names never appear:
  own wiki revisions say "this server", forum authors are the pseudonyms the posts carry, and an own answer appears only if it left as a
  post.
- **Rendering.** Every value goes through `html.escape`. Text is a small safe subset (paragraphs, headings, lists, fenced code, inline
  code, http(s) links with `rel="nofollow noopener noreferrer"`). Conflict blocks are shown as two columns.
- **Headers.** `Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none';
  frame-ancestors 'none'` (no script at all), `nosniff`, `no-referrer`.
- **Limits.** 120 requests per minute and client address (the first `X-Forwarded-For` behind the proxy).
- **Routes:** `/`, `/suche`, `/netze`, `/wiki/<netz>[/<page>[?verlauf=1|?rev=…]]`, `/forum/<netz>[/<thread>]`, `/wissen/<netz>`,
  `/eintrag/<id>`, `/eigen/<netz>/<netz_id>`, `/stil.css`.

## Default wiki network and switch (0.47.0)

`p2p.WIKI_NET` = `wiki`, `WIKI_START` = `https://vi-wiki.org/vi-p2p/wiki`. A first installation (Debian postinst without an old version,
RPM `.erstinstallation`) runs `nach-installation.sh wiki` → `vi-mcp net wiki on` → `net_cli.setup` with kind `free`, mode `peer` and
the start address; `VI_MCP_KEIN_WIKI` skips it.

The memory-side switch `netz_schalter(netz, an, zeit, wer, grund)` (`p2p.switch`, tool `vi_net_switch`, any instance with a token,
reason required) is checked in `outbox` (returns `aus` and nothing), `inbox` (takes nothing), `answer_search`, `live_search` and
`web.public_nets`. The network service sets `paused` from `aus` and skips reconciliation and inbox, so it needs no root and no restart.
`p2p.notice()` adds one line to `initialize` for every public network that is on, so the AI can tell the user.

## Housekeeping — the long-term archive

`archive.py`, sleep step 5. Entries no longer in use move to a separate file (`<db>-lager.db`, 0600), so that
the active store stays small. A stub remains in the memory.

| What | When (starting values, config `archive_days`) |
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

`"open": true` (before 0.51.0 `"offen"`) assigns requests without `Authorization` to the fixed instance `offen` (`config.OPEN`, reserved as a name). A wrong token stays 401.
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
  only users listed in config `local` (`vi-mcp local USER INSTANCE`) get in, each as its instance — with its visibility, internal
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
