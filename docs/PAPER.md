# Learning What to Put in Front of the Model: Measured Memory, Incubation and a Weighted Language for AI Agents

*vi-mcp technical report · version 0.62.0 (unreleased) · 13 November 2026*

**Abstract.** vi-mcp is a shared memory for many AI agents, served over the Model Context Protocol (MCP). It never trains the language
model it serves. Instead it learns, from the measured outcome of every action of every connected agent, *which context to put in front
of the model next* — which hints, rules and solutions, in which order. This report describes how that memory learns (labels from
outcomes, a logistic-regression router, randomized exploration and hold-back), how a memory *matures in an incubator* until measured
criteria say its data can fine-tune an AI, and **VIL**, a small, code-like language in which an AI asks the memory and the memory
answers. VIL has a readable symbol layer — speech acts, evidence markers and words of the form `kind:value` — and a meaning layer of
measured weights per word; memories exchange these weights, not prose and not model weights. Every design decision is grounded in an
explicit epistemic rule set (identity, non-contradiction, exhaustive cases with named unknowns, sufficient reason) and in measurements
taken on a production instance; where a claim is not measured we call it a hypothesis. We report what works (search MRR 0.73 hybrid vs
0.36–0.43 full text; ranked hints beat random ones by 6.9 ± 3.4 points of success; LLM labels agree across prompt variants with
Cohen's κ 0.80), what does not yet (no human gold set, no fine-tuning run, the total effect of hints still being measured) and what we
found wrong in our own work along the way.

---

## 1 Introduction

Agents repeat mistakes. A coding or operations agent that failed yesterday because a host needs a key file, or because `pkill -f` kills
its own shell, will fail the same way tomorrow unless something in its context says otherwise. The usual answer — a bigger model, a
longer system prompt, fine-tuning — is either out of the operator's hands or too coarse. vi-mcp takes the narrow route: a memory that
every agent reports to before and after each action (`vi_before`, `vi_after`) and that, before the next action, offers at most four
lines of context chosen by a model that is retrained daily on the outcomes of all agents. In that sense vi-mcp is *a search for the best
prompt* — not one master prompt, but the few right lines for each situation (tool, host, error, project).

Three questions shaped the work reported here:

1. **How does a memory learn without training the language model?** (Section 4.)
2. **When is a memory good enough to teach an AI?** — the *incubator* (Section 6). The goal set by the system's owner: "a VI that comes
   out of the incubator fine-tunes an AI."
3. **In what language should AIs talk to the memory and to each other?** Prose is the default today and, we argue, inefficient and
   unmeasurable. VIL (Section 5) is our answer; its meaning lives in weights.

The system runs in production for an IT operations department (about 24,400 knowledge objects, five agent instances, a log-monitoring
pipeline issuing thousands of lookups a day). All numbers below come from that instance or from reproducible local tests, each with its
date and method.

## 2 Epistemic foundation

vi-mcp is built against a short rule set that its owner formulated as design and review rules. They are not philosophy here but the
classes of error that cause misuse in practice.

1. **Identity (A = A).** One thing, one name, one place: the same name in code, API and interface; one source of truth.
2. **Non-contradiction.** Never two views with contradictory state of the same object; impossible combinations excluded by type.
3. **Exhaustive cases.** Every case falls into exactly one *named* class; `unknown` is a named state, never silence. Nothing vanishes
   silently: what is removed leaves a tombstone, what is held back is counted with its reason. (Formally three-valued, Kleene K3; only
   the classification of cases is two-valued.)
4. **Sufficient reason (Leibniz).** Every displayed state has a reachable cause; every refusal names its reason; numbers carry unit,
   period and origin.
5. **Valid inference.** No causation from proximity, no self-confirmation, no incomplete disjunction.
6. **Intension vs. extension, parsimony.** Rule and instance are kept apart; two ways to the same result are a logic error. And: how
   would we notice that an assumption is wrong? If there is no observation point, a display or a test is missing.

Three operational rules follow and recur throughout the system: **every statement carries evidence or is called a hypothesis**;
**no instance rates itself** (there is no tool to set one's own grade, and a publisher's rating of its own content does not count);
**a language model's verdict may only tighten** (it can be deceived by the text it checks; only fixed rules reject for good).

These rules are not decoration. In this report's own development they caught concrete errors: an evaluation that let random tie order
pass as a measured effect (Section 5.4), a statistic that mixed "nothing known" with "search failed" (Section 4.6), a parameter whose
values were silently translated (Section 5.2).

## 3 Architecture

**Objects.** Everything is an object in one database (SQLite or PostgreSQL): experiences (one per reported action), insights, rules,
skills (problem → solution), searches, models, conversations. Each object has a kind, a text, a content field (code, tables and commands
stored unabridged — what is missing is a gap in memory), hashtags `kind:value` (`host:`, `tool:`, `thema:`, `fehler:` …), an owning
instance, a visibility (private · shared · internal) and, since 0.61.0, exactly one **index** (`global`, a project, or a special VI).

**The action loop.** A hook in the agent's client calls `vi_before(tool, args)`; the memory answers with at most four hints, a risk
warning if the router predicts failure, and logs what it offered with the offer probabilities. After the action `vi_after` reports the
outcome; the experience object records tool, arguments, outcome, the hints shown and the router version. The user's prompt is masked
and never stored.

**Sleep.** A background consolidation clusters experiences into insights and skills, rates work (the scorer), archives what is no longer
used (with a tombstone), trains models and runs the daily measurement (Section 4.5). Since 0.62.0 it also accounts for machines that are
not up around the clock: a sleep older than 24 h is caught up in the next quiet moment (no MCP request for 10 minutes, something new to
consolidate), and on a workstation the importance trigger waits for such a moment, so the language model does not run while someone works.

**Network.** Servers form networks without a master: each appends signed entries to its own logbook (Ed25519), a separate service
exchanges them, and the memory checks every foreign entry again — fixed rules, quarantine, a reviewer model, release. Open networks
receive only anonymised knowledge; company networks carry internal knowledge to members of one organisation. The same meaning on several
servers is one object with several holders (content hash), rated by every server's own measurements.

## 4 How the memory learns

### 4.1 Labels from outcomes

The label of an action (or of one hint shown before it) is defined once (`scorer.label`) and used by every learner, in this order:
direct feedback on the hint (`vi_feedback`, `vi_confirm`, `vi_refute`); implicit adoption (a distinctive command, path or option of the
hint appears in a later successful action of the same session); a bad conversation grade; the scorer's code stage (repeat, red test,
user correction); the tool's own outcome. Each source carries its weight.

### 4.2 The router

A logistic regression (scikit-learn, `class_weight='balanced'`) predicts the success of an action given its features (tool, triggers,
the hint, its age, content features). The regularisation strength C is chosen on the newest 20 % of the training part by weighted log
loss, then refitted on the whole training part; the newest observations form the holdout. *Measured:* 17,590 observations, holdout AUC
0.863–0.865 (13.11.2026). Platt calibration was tried and rejected: holdout log loss rose from 0.427 to 0.473 (12.11.2026). Since 0.62.0
every training also reports a reliability table and the expected calibration error (ECE, Guo et al. [1]); the balanced class weights
shift the probabilities on purpose, and the table makes that visible instead of hiding it.

A new model must beat the current *champion* on the same unseen observations or the champion stays. An index (a project) with enough
data (≥ 300 observations, ≥ 30 failures) trains its own model, used only if it beats a shared reference fitted without the index's
holdout by more than two standard errors. *Measured on a production copy (13.11.2026):* the largest project index lost (AUC 0.29) and
stays with the shared model — the gate did its job.

### 4.3 Randomization: exploration and hold-back

Ranking hints by a model that learns from its own choices confounds the model's choice with the outcome. Two randomized experiments make
the effect causal:

- **ε-exploration.** With probability ε the last hint slot goes to a random candidate from further back; the offer probabilities are
  logged, so per-hint effects can be estimated by self-normalised inverse propensity scoring (Swaminathan & Joachims [2]).
  *Measured:* exploration minus ranked −6.4 ± 3.7 points (12.11.2026) and −6.9 ± 3.4 points (13.11.2026, daily measurement over 7 days):
  the ranked hint beats a random one. Since 0.62.0 the same probabilities also enter training: a second router is fitted with each observation
  weighted by 1/p (clipped at 10) and replaces the uncorrected one only if it wins on the holdout by more than two standard errors.
- **Hold-back** (0.61.0). On a random 5 % of actions that have hints, the hints are held back (the risk warning stays). Comparing held-back
  with shown actions within instance and tool (Mantel–Haenszel) estimates the *total* effect of showing hints. A raw comparison cannot:
  hints appear on hard actions (raw lift −37 points, matched lift −1 point, 13.11.2026). The hold-back is not yet deployed; a difference of
  a few points needs a few hundred held-back actions — weeks.

Warnings, by contrast, are clearly predictive: actions after a warning succeeded 51 % of the time, without a warning 98 % (24 h,
13.11.2026, 390 warnings).

### 4.4 The LLM weight layer

A language model may propose changes to router weights ("weight-space programming"); they act only after an offline gate (paired log
loss on a holdout) and a randomized online test on 20 % of actions. On 13.11.2026 a proposal of six changes passed offline (log loss
−0.00006 ± 0.00011 per observation on 3,645 holdout observations) and entered the online test. This is the only path on which a language
model may *loosen* a weight; it never sees text from the network.

### 4.5 Fixed measurement

Once a day the memory answers a fixed question set: 150 knowledge objects sampled by stratum, two questions each, written by a language
model. *Measured:* hybrid search (bge-m3 embedding plus full text, reciprocal rank fusion, cross-encoder reranking) reaches MRR 0.735
(12.11.) and 0.732 (13.11.), Hit@5 0.84–0.85; full text alone 0.364 and 0.432. The evaluation targets are held out of every training export
(Section 6.3).

### 4.6 What a statistic hid

The usage statistics reported 26 % of searches without hits. A reading of the search log on production (13.11.2026, read only; 424 searches
since logging began) showed that all 111 empty searches came from the log-monitoring pipeline asking about hosts the memory had never
heard of (57 hosts, none present as a hashtag); agents' searches had no empty result. "Nothing known" is the right answer there, not a
failure. Since 0.62.0 an empty search says why — a word unknown to the memory (with "did you mean" from the same kind) or known words that
no object carries together — and the statistics count both separately. The earlier interpretation ("agents guess tags that do not exist")
was ours and was wrong; it is corrected here and in the memory.

## 5 VIL — a language for AIs, with meaning in weights

### 5.1 Why not prose, and why not only weights

Agents talk to each other in prose today. Prose cannot be checked by a parser, its meaning cannot be measured, and it invites prompt
injection across trust boundaries. The opposite extreme — communicating through model weights, adapters or hidden states — is efficient
between identical models (DroidSpeak: up to 4× throughput when models share an architecture [3]; LatentMAS reports up to +14.6 % accuracy
with far fewer tokens [4]) but works only between identical or closely aligned models, is unreadable to people, and leaks content:
vec2text reconstructs 92 % of 32-token texts exactly from their embeddings [5], and embeddings of different models can be translated into
each other [6]. Adapters can carry backdoors [7]; machine-invented languages drift away from human readability [8, 9]. Between
organisations with different models and a review process, neither extreme fits.

The history of agent communication languages points the same way. KQML and FIPA-ACL standardised an envelope of performatives (FIPA
defines 22 communicative acts and 13 message parameters, only the performative being mandatory [10, 11]); what failed was agreement on
meaning — FIPA's semantics rested on agents' private mental states and was not verifiable [12]. Singh argued that meaning must be public
and social [13]. In vi-mcp, meaning *is* public: it is what is measured.

VIL therefore has two layers: a **readable, executable symbol layer** and a **meaning layer of measured weights**.

### 5.2 The symbol layer

An utterance is a speech act, optionally a question type, and words:

```
utterance  = act [ "." qtype ] { word } ;
act        = "ask" | "tell" | "do" | "promise" | "def" | "rate" ;
qtype      = "how" | "why" | "what" | "who" | "where" | "rule" ;
word       = [ "!" ] ( kindvalue | "@" name | "#" topic | phrase | text | group | "since:" age ) ;
kindvalue  = kind ":" value [ "*" ] ;          (* host:web1.example, tool:nginx, thema:deploy *)
group      = "(" word { "OR" word } ")" ;
age        = digits ( "d" | "h" | "w" ) | date ;
```

Design choices and their grounds:

- **Speech acts as a closed list** (Searle's classes; FIPA [11]): `ask`, `tell`, `do`, `promise`, `def`, `rate`. Only `ask` is executed by
  the search; `tell` is `vi_learn`, `rate` is `vi_feedback`, `def` adds a word. A `do` arriving in a message is never run — foreign
  content is data, not instruction (CaMeL: control flow only from the trusted request [14]; OWASP LLM01 [15]).
- **Question types** follow coarse question taxonomies (Li & Roth: six coarse classes classify at 92.5 % accuracy vs 89.3 % for fifty fine
  ones [16]). The type was meant to order the hits; measured, it does not help (5.4) — it is recorded for learning, not used to rank.
- **Words are the memory's hashtags**, one marker per meaning, linear and order-free — the agglutinative principle, and named roles
  instead of positions (case rather than word order; WALS ch. 20, 81 [17, 18]). Short forms: `@web1` is every host starting with `web1`,
  `@web1.example` exactly that host; `#topic` is `thema:topic`.
- **Small and tolerant.** Language models write rich query languages poorly (ES|QL about 59 % correct [19]; Cypher about 60 % for GPT-4o
  [20]); Elastic advises against strict query strings in search boxes [21]. VIL keeps to a handful of operators; anything that does not
  start with a known act is an ordinary filter, untouched.
- **Vocabulary first.** "What is there, what can I search?" — `vi_vocabulary` lists the kinds of words with counts, the values of a kind
  with their measured weight, and completes half-typed words; the internal search offers the same as autocomplete. Counts cover only what
  the asking instance may see. (A test caught that the vocabulary tool, without a session, would have listed host names from other
  instances' private objects; it now always takes the caller's visibility. A second test caught that values of a parameter named `kind`
  were silently translated by the German alias layer — `tool` arrived as `werkzeug`; the parameter is now `word_kind`.)

The answer comes back in the language, one line per hit:

```
tell.<memory> <id> "<text>" ev:<evidence> w:<weight>/<ratings> src:"<source>"
tell.procedure erkenntnis:… "deploy web1: stop, copy, start" ev:measured w:0.83/10 src:"https://wiki.example/deploy"
```

**Evidence is mandatory.** Like the evidentials of Quechua (`-mi` direct, `-si` reported) or Lojban's attitudinals (`ja'o` I conclude,
`ti'e` hearsay) [17, 22], every statement says how the memory knows it: *measured* (shown and rated), *documented* (a source URL),
*hearsay* (imported from another server), *inferred* (derived by a language model in sleep), or *unknown* — a named state, never silently
"observed". The memory kind (*fact*, *procedure*, *episode*, *rule*) follows the semantic/episodic/procedural distinction of cognitive
architectures for agents (CoALA [23]).

### 5.3 Classification: teaching the words their types

Knowledge must carry its question type and memory kind for `ask.<type>` to work. A language model labels each object with two prompt
variants that differ in wording and label order — both shift LLM labels [24, 25] — and stores a label only where they agree; disagreement
becomes the named state `answers:unsure`. The model's own confidence is not used (verbalised confidence is overconfident [26]). Each label
carries its version (model, prompt hash, schema), so a new prompt relabels instead of mixing. The model also writes up to three questions
a colleague would type to find the object (doc2query; document expansion raised MS MARCO MRR@10 from 0.184 to 0.277 [27]).

*Measured on a stratified production sample* (13.11.2026; 300 objects, both variants, 600 calls, an open-weight model on a shared
llama.cpp server): agreement 86.3 %, Cohen's κ 0.80 for the question type (the threshold for reliable annotation is often put at
α ≥ 0.8, tentative at ≥ 0.667 [28]); 92.3 %, κ 0.88 for the memory kind; most disagreements were what → where and how → what.
**28 of 600 answers (4.7 %) were outside the label enumeration although the request carried a JSON schema** — every answer is therefore
checked again and asked once more, otherwise `unsure`. Latency: median 56 s, 90th percentile 140 s per call on the
shared server. In a check of 26 objects by the author of this report (not a human gold set), about 24–25 primary labels were plausible.

Because labelling every object with a language model is slow, a **student** learns the labels: one logistic regression per label kind on
the bge-m3 vectors the memory already has, trained only on agreed labels (≥ 120, ≥ 15 per class), labelling only where ≥ 80 % sure; 10 %
of its sure labels are audited by the language model and the agreement is recorded, so drift becomes visible. Its gate is the accuracy of
the labels it actually gives: C is chosen by 5-fold cross-validation, and it is active only if its sure labels are ≥ 90 % right on ≥ 10 %
of the objects. *Measured on the production sample* (252 agreed labels, the stored vectors, the gate's own cross-validation): with C = 10
it is sure on 15.5 % of objects for the question type at 94.4 % accuracy and on 24.6 % for the memory kind at 95.0 % (overall accuracy
75–78 %); C = 100 is sure more often but 86–87 % right, below the gate; rare classes (`where`, `rule`) stay with the language model. The first design — C = 1 and an overall-accuracy gate of 0.8 — would never have
labelled anything: on unit-length vectors no prediction reached 0.8. Measuring on real data, not only on synthetic clusters, found it. Classifiers trained on LLM labels reach roughly the quality of those trained on human labels [29]; FineWeb-Edu
used exactly this pattern at scale [30]. Old data migrates where it is used: what a real search returns unlabelled is labelled at once by
the student or queued, and sleep labels the queue first.

### 5.4 The meaning layer: weights per word

The meaning of a word is its measured weight: for every word `kind:value` and question type, the beta mean of helped/not helped over the
knowledge carrying it, recomputed in sleep.

**Does the language rank better? Measured: no.** On a copy of production with its fixed question set (140 questions whose question word
gives the type, two query styles, 280 queries, paired against the plain hybrid order with MRR 0.737) every reordering lost: the fixed
prior as a priority rank −0.059 ± 0.012 (34 worse, 7 better; `where` from 1.0 to 0.54), and −0.289 ± 0.021 once word weights were
computed; a lift of at most two places for objects labelled with the type −0.006 ± 0.003; that plus the word weights −0.056 ± 0.010
(47 worse, 4 better). So the type no longer reorders anything; it is recorded with each search. Our reading (a hypothesis): the word
weights measure whether a *hint helped an action* — a different label from whether a *hit answers a question*. A meaning layer for
retrieval has to be learned from what is used after a search. We report this because the design was plausible, the literature does not
establish type matching as helpful either, and only the measurement showed the harm — the first version would have shipped it.

The missing piece is a relevance label: 3 of 386 searches had a hit opened afterwards, too few for click models [52]. Following
UMBRELA [51], a language model now grades a few real searches per sleep (0–3 per hit; all hits of a search in one call, a stated
deviation forced by about a minute per call on the shared server). On the production copy six searches gave nDCG@10 0.835, a rank-1
answer in 50 % and nothing relevant in the top 10 in 33 %. The grades only measure; a relevance weight trained on them must first win on
the fixed question set.

**Memories talk with weights.** Word weights travel between servers as ordinary signed ratings whose target is
`sha256("vil-word-v1|" + word + "|" + type)`. No new protocol type is needed (older peers would reject it), and the word itself never
travels in clear: a receiver can attribute a weight only to a word it knows. Into an open network go no host names and no word the
anonymisation flags as internal (the hash of a host name could be guessed by dictionary); a company network gets all. A receiver
combines foreign weights with its own, each foreign server weighted by its measured benefit as a publisher and capped at 20
observations — a foreign weight is a measurement, never a command. The symbol stays readable; the meaning travels as measured weight.

### 5.5 The logic layer: rules decided by formal logic, reliability in weights

Words and weights say *where* knowledge is and *how much it helped*; they cannot say what *follows* from rules. The owner asked for a
way to express logical descriptions "in Python, but by the principles of formal logic". We compared a Python-embedded Datalog, a
three-valued evaluator of our own and answer set programming, and chose ASP with the solver clingo [44, 50]: its stable-model semantics
contains stratified Datalog as a special case, it is nonmonotonic (rules with exceptions, as norms have), strong negation gives explicit
falsity next to "not derivable", and it searches and optimises.

**Notation.** A program is written in Python syntax and read by Python's `ast` against a whitelist — never executed: facts
`zone("gate1", "dmz")`, rules `head <= body` with `&`, `~x` for negation as failure, `-x` for strong negation, parenthesised comparisons,
`never(c)` for a constraint and `soft(rule[, belief])` for a weighted rule. A prelude gives the deontic square (obligatory, forbidden,
permitted; a violation is an obligation not done, obligation and prohibition together a named conflict) [45].

**Every case named.** ASP answers an inconsistent program with *no* answer set and treats a violated integrity constraint the same way —
the reason vanishes. We translate `never(c)` into a marker atom and report the violated constraint with its line; a contradiction
between hard rules is solved again with `-p` renamed, and the atoms that hold both ways are listed (Belnap's *both*). An atom is
*true*, *false*, *both*, *unknown* (the program does not mention it), *not derived* (the program defines it, this instance does not follow)
or *undetermined* (answer sets disagree) — the Kleene distinction between "no value" and "false" kept in the answer, not only in theory.

**Rules in weights.** The owner's next step was "clingo is also written in weights, so that with weight-space programming we learn clingo
fast". A `soft` rule is an LPMLN rule [46]: each ground instance may be dropped at the cost of its weight, a stable model's probability is
proportional to exp(−cost), and P(atom) sums over the models. We compile soft rules to weak constraints by the lpmln2asp scheme that
plingo uses [47]; the instance's variables are part of the marker, so a penguin drops its own instance of "birds fly" without the rule
losing its force for other birds (the first implementation dropped the whole rule — caught by the test, fixed before commit). The weight is
the log-odds of the rule's measured probability: the stated belief as two pseudo-observations, plus every conclusion checked against
reality (`vi_logic rate`) booked on exactly the rules that derive it (`fired` markers), plus the same counters from other servers on the
rating channel of the word weights, target `sha256("vil-rule-v1|rule")`, open networks only for rules without constants. In the test, six
"wrong" ratings move `soft(flies(X) <= bird(X), 0.9)` from p = 0.90 to 0.225 and the conclusion to *not derived*; twelve "right" ones
bring it back. Two deliberate limits: a hard rule stays hard whatever is measured (its measurement is shown with the advice to soften it —
the author's assertion and the measured world kept apart), and only weights are learned, never rules — learning rules from examples
(ILASP [49]) and neural atoms (NeurASP [48]) are the next steps, not this one. The counting is a simplification of LPMLN's
maximum-likelihood learning: exact when one rule alone decides a conclusion.

## 6 Incubation and fine-tuning

### 6.1 The incubator

A memory matures in operation. `vi-mcp incubator status` measures seven required criteria, each with threshold, value and state —
*met*, *open*, or *not measured* (never counted as met):

| criterion | measured as | default threshold |
|---|---|---|
| knowledge | shared or internal knowledge objects | 500 |
| checked | share rated after being shown or confirmed — knowledge put to the test, not only stated | 20 % |
| search | hybrid MRR of the daily fixed question set | 0.6 |
| router | hint model active, holdout AUC | 0.75 |
| hints_no_harm | the randomized hold-back does not show that hints lower success | no harm beyond 2 SE |
| labels | share classified, and the student active | 50 % |
| training_data | question → answer examples, evaluation held out | 1,000 |

An informative eighth criterion, **gold**, reports labels set by people and a **truth check**: do the measured weights rank knowledge that
people confirmed above knowledge they refuted (AUC; 0.5 means the measurement ignores truth)? Only instances marked `human` may set gold
labels — an AI is not the gold, and no instance rates itself. When all required criteria are met the memory *hatches*: its training data
is exported with the incubator state recorded.

### 6.2 Training data

`vi-mcp dataset export` writes four files and a datasheet (Gebru et al. [31]):

- `qa.jsonl` — supervised fine-tuning: question → knowledge with its source (questions from doc2query or the object's title);
- `kto.jsonl` — situation → hint, desirable or not, from the measured helped/not-helped counters. KTO learns from exactly this binary
  signal [32];
- `dpo.jsonl` — under one trigger, one hint helped clearly more than another (direct preference optimisation [33]);
- `agentic.jsonl` — tool-use trajectories: the question; a `vi_recall` call with a VIL question built from the question's words and the
  object's label and hashtags; the real `tell` lines of the memory's search; one relaxed question if the target is missing; the answer
  citing the target. Only trajectories that found their target are kept — no example teaches a wrong answer. A model trained on them
  learns to *search the memory in its language*, not only to recite it (cf. FireAct: Llama-2-7B fine-tuned on 500 agent trajectories
  [34]; AgentTuning [35]).

Never exported: private objects, experiences and conversations (they belong to their instance — the hint data are aggregated counters),
quarantine, refuted or archived objects, copies of repositories. Credentials are scrubbed at save time and again on export; the changes
are counted, an audit of the first scrubber.

### 6.3 Contamination guard and lineage

The targets of the fixed question set and any question equal to an evaluation question are held out of every training file, so a model
fine-tuned on the data can still be measured on them (contamination inflates benchmark scores [36]). Every export carries its manifest
(counts, exclusions with reasons, versions of router, classification and student, label quality, known gaps).

### 6.4 The fine-tuning interface

vi-mcp trains no model by itself. A person tells their AI "I want to fine-tune"; the AI calls `vi_finetune`, which reports whether the
memory is mature and gives the steps; `vi_finetune(action="guide")` explains fine-tuning. On the server `vi-mcp finetune kit` writes the
training data, a test split *by object* (no object on both sides), `train.py` (TRL with a LoRA adapter [37, 38]: SFT, then agentic, KTO or
DPO on top), `convert.sh` (the adapter as GGUF for llama.cpp, loaded with `--lora` and switchable at runtime [39]) and `evaluate.py` (base
and fine-tuned models get the same held-out questions, no token cap). `vi-mcp finetune record` keeps the run as a model object with its
lineage — dataset manifest hash, base model, adapter hashes, evaluation, incubator state — and counts it as adopted only if it measured
better. Hardware guidance follows the tool documentation (QLoRA of 7–8B models from about 5–6 GB VRAM, LoRA in 16 bit of 14B models
from about 33 GB [40]).

## 7 What went wrong, and what we learned from it

A system built on "evidence or hypothesis" must report its own errors. In the work for this report:

- **An index file's way back created copies.** Recognising one's own content compared only the first 20 objects with the same text; 40 of
  180 contents came back as copies in a real test with many objects titled "What is missing". Fixed (content first, then up to 500), with a
  regression test.
- **Nobody could sign in to the internal search in a real browser.** The pages had inherited `Referrer-Policy: no-referrer`; Chrome then sends
  a form POST with `Origin: null`, and the cross-site check rightly refused it. Unit tests that set the header themselves could not see it.
- **A statistic was misread** (Section 4.6) and **an ordering passed by chance** (Section 5.4).
- **An internal host name entered a commit** although the pre-commit scan had flagged it — the scan's result did not stop the command
  chain. Caught before publishing, removed, and the scan now blocks.

## 8 Limitations and open problems

- **No human gold set yet.** κ between two prompts measures the model's consistency with itself, not correctness (Pangakis et al. found
  precision or recall below 0.5 on 9 of 27 annotation tasks [41]).
- **No fine-tuning run yet.** The kit is untested on real hardware; whether the exported data improves a model is open.
- **The total effect of hints is not yet measured** (hold-back not deployed).
- **Poisoning.** PoisonedRAG succeeds 97 % of the time with five texts per target question [42], AgentPoison above 80 % with under 0.1 %
  poisoned entries [43]. Our own poisoning test (`vi-mcp redteam`, a throw-away memory, success = top 3 of search or shown as a hint)
  found imports and token-less proposals held 10 of 10, but **10 of 10 planted entries of an instance with a token reached an agent**.
  Fixed rules now hold such entries (instructions to an AI, hidden characters, piping a download to a shell, wiping system directories,
  switching a firewall off, handing credentials to a URL): 0 of 10 for the attacks the rules were tuned on, but **6 of 10 for attacks
  written afterwards** — fixed rules close known channels and generalise poorly; a plausible but wrong answer is invisible to them. The
  first version of the rules held 216 of 300 real objects; the version kept holds 1 — measuring false positives on real data was as
  important as measuring attacks.
- **Off-policy training is gated, not proven.** Every training fits an inverse-propensity-weighted router beside the uncorrected one and
  keeps it only if it is better on the holdout by more than 2 SE; whether it ever wins on production data is not yet known.
- **Order-dependent tests.** Two tests fail rarely in a full run and pass alone; the cause is unknown.
- **The logic layer learns weights, not rules,** and its counting is an approximation of LPMLN weight learning where several rules derive
  the same conclusion. Whether agents use `vi_logic` instead of reasoning in prose is not measured yet.
- **The language does not yet rank better.** Every reordering by question type, label or word weight lowered MRR on the production
  copy (5.4); a relevance weight learned from what is used after a search is the open step.

## 9 Conclusion

vi-mcp shows that a memory for AI agents can learn — measurably and causally — which context helps, without touching the language model.
The incubator turns "is this memory good enough?" into criteria with values, and the export turns a mature memory into training data that
another AI can learn from, including how to search the memory itself. VIL keeps the symbols readable for people and checkable for
parsers, and puts meaning where the system already has it: in measured weights, exchanged between memories as measurements rather than
commands. The rule set behind it — evidence or hypothesis, named unknowns, nothing silent, no self-rating — is what made the errors in our
own work visible.

---

## References

Sources consulted for this report on 13 November 2026 (web research during the development session); arXiv identifiers and URLs as
retrieved. Where only an abstract was read, the claim cited is the one stated there. Author names are given as commonly cited; they and
reference 1 (Guo et al.) were not re-checked in that session — the identifiers and URLs were.

1. Guo, Pleiss, Sun, Weinberger. On Calibration of Modern Neural Networks. ICML 2017. https://arxiv.org/abs/1706.04599
2. Swaminathan, Joachims. The Self-Normalized Estimator for Counterfactual Learning. NeurIPS 2015. (cited in vi_mcp/metrics.py)
3. DroidSpeak: KV cache sharing across LLMs. https://arxiv.org/abs/2411.02820
4. LatentMAS: latent collaboration in multi-agent systems. https://arxiv.org/abs/2511.20639
5. Morris et al. Text Embeddings Reveal (Almost) As Much As Text (vec2text). https://arxiv.org/abs/2310.06816
6. Jha et al. Harnessing the Universal Geometry of Embeddings (vec2vec). https://arxiv.org/abs/2505.12540
7. LoRATK: LoRA once, backdoor everywhere. https://arxiv.org/abs/2403.00108
8. Lewis et al. Deal or No Deal? End-to-End Learning for Negotiation Dialogues. https://arxiv.org/abs/1706.05125
9. Kottur et al. Natural Language Does Not Emerge 'Naturally' in Multi-Agent Dialog. https://arxiv.org/abs/1706.08502
10. FIPA ACL Message Structure Specification SC00061G. http://www.fipa.org/specs/fipa00061/SC00061G.html
11. FIPA Communicative Act Library Specification SC00037J. http://www.fipa.org/specs/fipa00037/SC00037J.html
12. Wooldridge. Verifiable Semantics for Agent Communication Languages. ICMAS 1998. https://eprints.soton.ac.uk/259563/
13. Singh. Agent Communication Languages: Rethinking the Principles. IEEE Computer 1998. https://www.csc2.ncsu.edu/faculty/mpsingh/papers/mas/computer-acl-98.pdf
14. Debenedetti et al. Defeating Prompt Injections by Design (CaMeL). https://arxiv.org/abs/2503.18813
15. OWASP Top 10 for LLM Applications, LLM01 Prompt Injection. https://genai.owasp.org/llmrisk/llm01-prompt-injection/
16. Li, Roth. Learning Question Classifiers. COLING 2002. https://aclanthology.org/C02-1150
17. de Haan. Coding of Evidentiality. WALS ch. 78. https://wals.info/chapter/78 — and Bickel, Nichols, Fusion; WALS ch. 20. https://wals.info/chapter/20
18. Dryer. Order of Subject, Object and Verb. WALS ch. 81. https://wals.info/chapter/81
19. Elastic. Text-to-ES|QL benchmark. https://www.elastic.co/search-labs/blog/text-to-esql-benchmark
20. CypherBench. https://arxiv.org/html/2412.18702v2
21. Elasticsearch reference: query_string query. https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-query-string-query.html
22. The Complete Lojban Language, ch. 13.11 Evidentials. https://lojban.org/publications/refgram_chunked/cllc/13/11/
23. Sumers et al. Cognitive Architectures for Language Agents (CoALA). https://arxiv.org/abs/2309.02427
24. Pezeshkpour, Hruschka. Large Language Models Sensitivity to the Order of Options. Findings NAACL 2024. https://aclanthology.org/2024.findings-naacl.130
25. Reiss. Testing the Reliability of ChatGPT for Text Annotation. https://arxiv.org/abs/2304.11085
26. Xiong et al. Can LLMs Express Their Uncertainty? ICLR 2024. https://arxiv.org/abs/2306.13063
27. docTTTTTquery (doc2query). https://github.com/castorini/docTTTTTquery
28. Krippendorff's alpha, decision thresholds. https://www.statisticshowto.com/krippendorffs-alpha/
29. Pangakis, Wolken. Knowledge Distillation in Automated Annotation. NLP+CSS 2024. https://aclanthology.org/2024.nlpcss-1.9/
30. Penedo et al. The FineWeb Datasets. https://arxiv.org/abs/2406.17557
31. Gebru et al. Datasheets for Datasets. https://arxiv.org/abs/1803.09010
32. Ethayarajh et al. KTO: Model Alignment as Prospect Theoretic Optimization. https://arxiv.org/abs/2402.01306
33. Rafailov et al. Direct Preference Optimization. https://arxiv.org/abs/2305.18290
34. Chen et al. FireAct: Toward Language Agent Fine-tuning. https://arxiv.org/abs/2310.05915
35. Zeng et al. AgentTuning. https://arxiv.org/abs/2310.12823
36. Data contamination in LLM evaluation. https://arxiv.org/abs/2310.18018
37. Hugging Face TRL, dataset formats. https://huggingface.co/docs/trl/main/en/dataset_formats
38. Dettmers et al. QLoRA. https://arxiv.org/abs/2305.14314
39. llama.cpp server: LoRA adapters. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
40. Unsloth requirements (VRAM table). https://unsloth.ai/docs/get-started/beginner-start-here/unsloth-requirements
41. Pangakis et al. Automated Annotation with Generative AI Requires Validation. https://arxiv.org/abs/2306.00176
42. Zou et al. PoisonedRAG. https://arxiv.org/abs/2402.07867
43. Chen et al. AgentPoison. https://arxiv.org/abs/2407.12784
44. Lifschitz. What Is Answer Set Programming? https://www.cs.utexas.edu/~vl/papers/wiasp.pdf
45. Stanford Encyclopedia of Philosophy. Deontic Logic. https://plato.stanford.edu/entries/logic-deontic/
46. Lee, Wang. Weight Learning in a Probabilistic Extension of Answer Set Programs (KR 2018). https://arxiv.org/abs/1808.04527
47. Hahn et al. plingo: A System for Probabilistic Reasoning in Clingo Based on LPMLN. https://arxiv.org/abs/2206.11515
48. Yang, Ishay, Lee. NeurASP: Embracing Neural Networks into Answer Set Programming (IJCAI 2020). https://www.ijcai.org/proceedings/2020/243
49. Law, Russo, Broda. The ILASP System for Inductive Learning of Answer Set Programs. https://arxiv.org/abs/2005.00904
50. Potassco. clingo (Python package `clingo`). https://pypi.org/project/clingo/
51. Upadhyay et al. UMBRELA: UMbrela is the (Open-Source Reproduction of the) Bing RELevance Assessor. https://arxiv.org/abs/2406.06519
52. Wang et al. Position Bias Estimation for Unbiased Learning to Rank in Personal Search (WSDM 2018). https://research.google/pubs/position-bias-estimation-for-unbiased-learning-to-rank-in-personal-search/

Further sources used in the design notes of the same session: Gilardi et al., ChatGPT outperforms crowd workers (https://arxiv.org/abs/2303.15056);
Ziems et al., LLMs for computational social science (https://arxiv.org/abs/2305.03514); Agora protocol (https://arxiv.org/html/2410.11905v1);
Spotlighting (https://arxiv.org/abs/2403.14720); Zep/Graphiti (https://arxiv.org/abs/2501.13956); MemoryBank (https://arxiv.org/abs/2305.10250);
A2A specification (https://a2a-protocol.org/latest/specification/); MCP specification, tools (https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

## Appendix A — Measurements cited

| quantity | value | when, how |
|---|---|---|
| knowledge objects | 24,379 | production, `vi_stats`, 13.11.2026 |
| router | AUC 0.863–0.865 on 17,590 observations | production, model report, 13.11.2026 |
| search MRR (fixed set, 150 × 2) | hybrid 0.735 / 0.732; full text 0.364 / 0.432 | daily measurement 12./13.11.2026 |
| exploration − ranked | −6.4 ± 3.7 / −6.9 ± 3.4 points | daily measurement 12./13.11.2026 (7 days each) |
| warnings | success after 51 %, without 98 % | `vi_stats`, 24 h to 13.11.2026 |
| empty searches | 111 of 424, all monitoring lookups of 57 unknown hosts | production search log, read only, 13.11.2026 |
| LLM label agreement | type 86.3 % (κ 0.80), memory 92.3 % (κ 0.88), n = 300 | stratified production sample, 13.11.2026 |
| answers outside the schema | 28 of 600 (4.7 %) | same run |
| student (C = 10, sure ≥ 0.8) | type 94.4 % right on 15.5 %; memory 95.0 % on 24.6 % | 252 agreed labels, 5-fold CV |
| index file round trip | 185 objects; export 180 in 0.25 s (218 KB); import 0.78 s; way back 0 copies (40 before the fix) | two local test servers, 13.11.2026 |
| LLM weight layer, offline | log loss −0.00006 ± 0.00011 / observation, 3,645 holdout | production, 13.11.2026 |

## Appendix B — Glossary (stored names are German)

| stored | meaning |
|---|---|
| erkenntnis, regel, erfahrung, gespraech | insight, rule, experience, conversation |
| geteilt, intern, privat | shared, internal, private |
| thema, fehler, art_wissen | topic, error, kind of knowledge |
| schlaf, schueler, einig/uneinig | sleep, student, agreed/disagreed |
| inkubator: erfuellt, offen, nicht_gemessen, reif, im_inkubator | met, open, not measured, mature, in the incubator |
