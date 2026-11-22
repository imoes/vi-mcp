# vi-mcp — a memory for AI agents that keeps what they learn

[Deutsch](README.de.md) · **English** · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest) · [All documentation](docs/README.md) · [![Release](https://img.shields.io/github/v/release/imoes/vi-mcp?label=release)](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` is a **VI (virtual intelligence)**: one server process with one memory that AI agents — Claude Code, Codex, Hermes or any
MCP client — connect to over **MCP (Streamable HTTP)**. What an agent finds out, decides or gets corrected on is stored as a readable
object with its source, and comes back as a hint right before the next action it matters for.

## Who it is for

**One agent.** A single AI forgets: the context window ends, a session closes, the conversation is compacted, the model is
replaced. With vi-mcp its knowledge is **conserved** outside the model — every fix with the commands that worked, every decision you
made ("from now on …"), every fact it looked up, with source and date. The next session, the next day, or a different model starts
with it. Wrong knowledge is refuted with a reason, not quietly overwritten.

**Many agents.** Sessions share the same memory at the same time, each with its own context, like time slices on one processor.
What one session solved is a hint for the next one, even with a different model or vendor. No instance can confirm its own knowledge;
others check it.

**Into a model's weights.** What a VI learned can be **trained into a model** when you decide so. The memory stores its knowledge
training-ready from the start (grounded question-answer pairs and an untrained probe question per object), measures when it is ripe
(the incubator), and writes a complete fine-tuning kit (data, scripts, evaluation) for a GPU host. vi-mcp never trains on its own.

*Measured:* a 0.6B model fine-tuned on 500 of a VI's documents answered 7 correct and 9 partly correct of 60 never-trained probe
questions about them, the base model 0 and 5 (blind, sign test p = 0.008; 15.11.2026). Search over the memory finds known knowledge
with MRR 0.735 using meaning plus full text, against 0.364 with full text only (production, 12.11.2026).

## Quick start

```bash
# Debian / Ubuntu — signed package repository, later updates come with apt upgrade
curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh && sudo apt install vi-mcp
sudo vi-mcp setup            # menu: registers Claude Code, Codex CLI, Hermes Agent and the hook, one token per program
```

Then work as usual. Before an action the agent calls `vi_before` and gets at most four hints, afterwards `vi_after`; with the Claude
Code hook this happens by itself. Tell it to remember something and it calls `vi_learn`. Every platform (Fedora/RHEL, Arch, macOS,
Windows) is under [Install](#install).

## How it works

```
 Session A (Claude Code)   Session B (Codex, Hermes)   Session C (hook)
        │  Mcp-Session-Id         │                           │
        └────────────── POST /mcp (bearer token per instance) ┘
                                  │
                     ┌────────────▼─────────────┐
                     │  vi-mcp  (ONE process)    │
                     │  before · after · sleep   │
                     └────────────┬─────────────┘
                                  │ single writer
                           vi.db (SQLite or PostgreSQL)
```

- **Objects, not notes.** Everything is an object with hashtags (`kind:value`), an author and a visibility — private, shared, or
  internal (token holders only; never an open network, only a company network): experience, insight, rule, skill, score.
- **Before every action** (`vi_before`) a session gets at most four hints that share a host, program or error with what it is about
  to do. A hint is reinforced only when the action then succeeds.
- **Before every question** the hook brings the knowledge that fits your prompt, follow-up questions included (Claude Code
  `UserPromptSubmit`, Hermes `pre_llm_call`). The prompt is masked and not stored.
- **Sleep.** When enough has happened, the server condenses experiences into insights and skills, compares new evidence with what it
  knows, merges repetitions and archives what nobody uses (still findable).
- **Scorer.** Code rules, a language model and you judge whether work succeeded — "the tool did not crash" alone does not say that.
- **Learning.** From those outcomes a small model (the router) learns which hint helps in which situation. It retrains about a
  minute after new experiences, in under a second.

### The kinds of memory

| Human memory | vi-mcp | Where it comes from |
|---|---|---|
| episodic — "what happened" | experience: every reported action with tool, arguments, result, duration | the hook, automatically |
| semantic — "what I know" | insight, rule: a key statement plus the complete content and its source | `vi_learn`, imports, sleep |
| procedural — "how to do it" | skill: problem, steps, instructions, versions | `vi_solved`, sleep |
| cues | hashtags `kind:value` (`tool:`, `host:`, `topic:` …) and learned searches | everywhere |

Recall works through cues: the tool, the host and the topics of an action are its triggers, and at most four hints answer (working
memory holds about four chunks, Cowan 2001). Requirements you state (`topic:requirement`) are listed in the index every session
receives. Unused knowledge fades and moves to the archive; nothing is lost silently — held-back hints, merged duplicates and refuted
knowledge are counted and named.

### Why the knowledge stays in the memory, not in the model

- **Learned at once.** Knowledge is available before the next action, not after the next training run.
- **Every memory can be checked.** It has a source (command, host and time, or URL), an author and a history; it can be confirmed,
  disputed and refuted — by *other* instances.
- **It can be forgotten.** Delete a conversation, an instance or an object and it is gone, with a tombstone saying so. Knowledge in
  model weights cannot be removed like that.
- **Complete, not summarised.** Code, API tables and commands are stored in full: what is missing from memory is a gap.
- **Training stays possible.** Because the knowledge is kept readable and with its source, it can still be trained into a model later
  — measured, and only if you decide so ([Training a model](#training-a-model-from-the-memory)).

### What it learns — and why those weights cannot invent facts

vi-mcp's own learned weights decide **which** memory to show, never **what** is true:

- **The router** is a logistic regression (scikit-learn). Each action is one observation: the situation's triggers × the hints shown,
  labelled with whether the action succeeded. Its weights are readable JSON (`vi_model`); `vi_why` explains why a hint was shown. A new
  model goes live only if it beats the old one on held-back data, and fixed rules flag weights that look wrong. An AI can shape it
  without writing a number: `vi_feature_propose` reads the weights and the router's worst situations and proposes feature rules; sleep
  keeps only what improves the router on held-back data.
- **The bandit** (Thompson sampling) counts per hint how often an action succeeded after it, against the base rate — the fallback while
  the router has too little data.
- **Meaning** comes from a pre-trained embedding model (bge-m3) for semantic search; a learned per-dimension weighting of the query
  (`query_adapter`) switches on only while its offline test says it helps.

The label is the outcome of real work, so nobody labels data. The model is kilobytes, explainable by named features, and it can only
order memories that exist and have a source — a wrong weight shows a less helpful hint, it cannot create a false statement.

*Measured (production):* the router recognises actions that will fail — 51 % of the warned actions failed, 3 % of the others
(AUC 0.88, 12.11.2026). In a randomized comparison the chosen hint beat a random one by 12.6 ± 5.3 points of success (12.11.2026);
the audit window of 14.11.2026 shows 4.7 ± 3.1 points — not conclusive on its own. Whether showing hints at all raises success is
measured with a random 5 % hold-back (`vi_stats`); that needs weeks of data.

## Training a model from the memory

Fine-tuning is a person's explicit decision; vi-mcp prepares and measures it, the training runs on a GPU host of your choice.

1. **Knowledge is stored training-ready.** While it sleeps the server writes grounded question-answer pairs and one never-trained
   probe question onto each knowledge object (`vi-mcp classify --pairs`).
2. **The incubator says when a VI is ripe** — measured, never declared: `vi-mcp incubator status [--index X]` (or `vi_incubator`)
   shows each criterion with threshold, value and state (met, open, or not measured — never counted as met):

   | criterion | measured as | default threshold |
   |---|---|---|
   | knowledge | shared or internal knowledge objects | 500 |
   | checked | share rated after being shown or confirmed by an instance | 20 % |
   | search | hybrid MRR of the daily fixed question set | 0.6 |
   | router | hint model active, holdout AUC | 0.75 |
   | hints_no_harm | the randomized hold-back does not show that hints lower success | lower 95 % bound above −0.02 |
   | labels | share classified for the AI language, and the student active | 50 % |
   | training_data | question → answer examples, evaluation held out | 1000 |

3. **Tell your AI "I want to fine-tune".** It calls `vi_finetune`, which says whether the VI is ripe and gives the steps;
   `vi_finetune(action="skill")` is a step-by-step runbook written so that small models can follow it
   ([docs/FINETUNING_SKILL.md](docs/FINETUNING_SKILL.md)).
4. **The kit.** `vi-mcp finetune kit DIR --base MODEL` writes everything a GPU host needs: data with a datasheet, a held-out split,
   `train.py` (TRL + LoRA), a [tokenizer audit and real-trainer preflight](docs/TRAINING_PREFLIGHT.md) (no silent truncation, zero
   optimizer steps), `probe.py` (did the model learn what it trained on), `evaluate.py` and `convert.sh` (GGUF adapter for llama.cpp).
   `vi-mcp finetune record DIR` keeps the run with its lineage; it counts as adopted only if it measured better.

From zero, with every command: [docs/FINETUNING.md](docs/FINETUNING.md).

**Philosophy packages** equip an AI with principles ([Philosophies](#philosophies--principles-an-ai-works-by-and-when-to-apply-which));
a kit with `--philosophy NAME` trains a model on one. How a 0.6B model learns such a seed, run by run and scored by the solver:
[docs/FINETUNING_PAPER.md](docs/FINETUNING_PAPER.md).

## Logic over the memory: clingo-object

Searching stays SQL; inference over the memory's objects is answer set programming with [clingo](https://pypi.org/project/clingo/).

**Ask in plain language** — the server's language model writes the program, the server solves it with what you may see:

```text
vi_logic(action="answer", question="Which DMZ hosts are never described as production?")
→ state: answered · 2 answer(s) · 1 round(s) · evidence: inferred
program:
dmz(H) <= (O in objects("netz:dmz")) & (O.host == H)
prod(H) <= (O in objects("kritikalitaet:prod")) & (O.host == H)
ans(H) <= dmz(H) & ~prod(H)
```

**Or write the rules** in a Python-like notation (read, never executed): `(O in objects("filter"))` binds objects of a search,
`(O.host == H)` reads a hashtag, `linked(O, B)` follows an edge, `never(…)` reports a violation, `soft(…)` is a rule whose weight is
learned from conclusions checked against reality. Answers are four-valued per statement: true, false, both, unknown. A rule may
`propose(…)` a change; it waits in quarantine until a person releases it.

**Or in real Python** with the package `clingo-object` (in every release as a wheel): classes, methods and inheritance compile to the
same notation the server runs, so the answer is the same on your machine and on the server.

```python
from clingo_object import Memory, Obj, Program, VIObject, rel

class Knowledge(VIObject):
    def stale(self):
        return (self.mode == "test") & (self.age > 90)

class Skill(Knowledge):
    kind = "skill"
    def stale(self):
        return (self.mode == "test") & (self.age > 30)

O = Obj("O")
prog = Program(Knowledge, Skill, rel.review(O) <= O.where("art:skill") & O.stale())
print(prog.check(Memory())["folgerungen"])
```

*Measured* (production copy, 13.11.2026): the agent (`python3 -m clingo_object.agent "…"`) answered 15 of 16 relational questions
exactly; the same model with searches alone 2 of 16. Details: [docs/PAPER.md](docs/PAPER.md) section 5.6.

**VIL and the virtual machine.** Agents can also ask in VIL, a short language of speech acts over the memory's words
(`ask.how deploy @host #project`, answers as `tell` lines with how the speaker knows it). `vi_machine` runs VIL and clingo-object over
an instance's private, mutable world with snapshots and forks ([docs/VIRTUAL_MACHINE.md](docs/VIRTUAL_MACHINE.md),
[docs/INSTANCE_RUNTIME.md](docs/INSTANCE_RUNTIME.md)); an optional [kNN-LM backend](docs/KNN_LM.md) lets token prediction draw on a
mutable datastore while the model's weights stay fixed.

## Projects and special VIs (indexes)

One memory holds many projects without mixing them. Every object belongs to exactly one **index**: `global`, a **project** or a
**special VI** (a body of knowledge you want to search, train or hand on as a unit, e.g. a product's documentation).

- **A project needs no set-up.** The hook sends the name of the working directory; what an agent learns there lands in that project's
  index, and there its knowledge comes first in search and hints — everything else stays visible (precedence, not exclusion). Map or
  ignore directory names in `config.json` (`"indexes": {"map": {"repo": "cue-stack"}, "ignore": ["scratch"]}`).
- **Create and describe one explicitly** — e.g. a special VI before anything is in it: `vi_indexes(index="cue-print", description=…,
  tags=[…], kind="special")` or `vi-mcp index describe cue-print --text "…" --tags team:it --kind special`.
- **Learn into it and search it:** `vi_learn(…, index="cue-print")`; to search **only** a project, add `index:cue-print` to any filter —
  an AND condition like a hashtag, in `vi_recall`, `vi_drilldown` and `vi_logic` objects(…) alike (`vi_recall(…, index="cue-print")` is
  the same). Without it, a project's own hits come first and everything else stays visible;
  `vi_indexes` lists every index with its objects, experiences and the state of its own model.
- **Code of a repository** goes into an index as functions and classes: `vi-mcp index import-code REPO --index X` (idempotent, only
  changed files; a git hook keeps it current).
- **An index with enough data trains its own router** and uses it for its project only while it beats the shared one.
- **Move, rename, merge, export:** `vi-mcp index move|rename|backfill|export|import|compare` — [docs/OPERATIONS.md](docs/OPERATIONS.md#indexes-and-code-0610).

## Skills — what an AI can do here, kept in the server

A skill is knowledge of the kind `knowledge_kind:skill`: the whole how-to (steps, commands, examples) with the hashtag `docs:<name>`.
Every AI of the server inherits them: `vi_capabilities` lists them, and the hook puts that list into the first prompt of every session;
`vi_object` reads one whole.

- **Add or update one** with the ordinary `vi_learn`: hashtags `knowledge_kind:skill` and `docs:<name>`, `key="skill:<name>"` — a later
  vi_learn with the same key updates it with history.
- **A whole skills folder** (`<name>/SKILL.md` with a front matter) comes in with `vi-mcp skill import DIR --instance NAME`.
- **Initial skills** come with the package and are refreshed with every update: `clingo` (how to write and read logic programs with
  `vi_logic`, every example checked against the engine), `finetune` (fine-tune any open model, step by step) and `philosophy`.

## Philosophies — principles an AI works by, and when to apply which

A philosophy is a checked [clingo-object](#logic-over-the-memory-clingo-object) rule set (the **seed**) with test worlds that prove it:
when an AI holds a statement true, what it may say, what it must do. Prose is only a translation, checked by its round trip. Built in:
`kollektiv` (how a member of an AI collective holds something true — no self-confirmation, support and opposition apart, a reason for
every value), `messung` (only an applicable measurement admits a statement) and `code` (architecture rules over code facts).

1. **Hand one over** — `vi_philosophy(action="install", package={manifest, seed, worlds})` (the contents of philosophy.json, seed.co and
   worlds.jsonl). The same checks decide: vocabulary, no default negation outside a closed view, every rule in a marked block, the
   test worlds. `export` gives a package back whole; `list`, `show` and `check` read them.
2. **Say what it is for** — the manifest may declare its situations as hashtags: `"situations": ["topic:incident", "task:judge-claims"]`.
3. **When it is applied** — not automatically. When the situation of a prompt fits a philosophy (declared for it, or measured to have
   helped there), the prompt context carries one line `[Philosophy] This situation fits the philosophy X …`. The AI then translates the
   situation into the philosophy's facts, gets its verdict with `vi_philosophy(action="evaluate", name=X, facts=…)`, acts by it and
   says so — the verdict is evidence *inferred*.
4. **Which one fits when is learned** — afterwards the AI rates it: `vi_philosophy(action="rate", name=X, tags=[…], helped=true|false,
   reason=…)`. `vi_philosophy(action="suggest", situation=…)` ranks the philosophies for a situation from what is declared (a head
   start) and what was rated (the decision), with the counts.
5. **Bind** one to an instance or an index (`use`); **train** a model on it: `vi_philosophy(action="kit", name=X, base_model=…)` (or
   `vi-mcp philosophy kit X DIR --base …`) writes the kit for the seed path alone — nothing of the memory in it; the server picks the
   directory and returns it, a person runs the training on a GPU host ([docs/FINETUNING.md](docs/FINETUNING.md) section 4b). A philosophy never changes visibility, review or tool rights.

Step by step: [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) (also the initial skill `philosophy`).

## Install

| System | How | Service |
|---|---|---|
| Debian 12/13, Ubuntu 24.04 | package repository or `.deb` | systemd `vi-mcp` |
| Fedora 43, AlmaLinux/RHEL 10 (EPEL) | package repository or `.rpm` | systemd `vi-mcp` |
| Arch Linux, CachyOS | `.pkg.tar.zst` | systemd `vi-mcp` (not enabled by the package) |
| macOS (Apple silicon, Intel) | Homebrew tap | launchd via `brew services` |
| Windows | `.msi` | scheduled task `vi-mcp` |

Every release carries all of them, plus the `clingo-object` wheel and the source archive, listed in a signed `SHA256SUMS`
([check a release](#check-a-release)).

### From the package repository — updates with `apt upgrade` / `dnf upgrade` / `pacman -Syu`

The signed repository is served by GitHub Pages: **https://imoes.github.io/vi-mcp-packages/**. Its signing key (OpenPGP, Ed25519)
has the fingerprint `4598 3154 14EB F86C ABD3  22D9 730B 75BF AC30 36B7` — compare it with
[`deploy/repo-key.asc`](deploy/repo-key.asc) before you trust it.

```bash
curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh      # adds key and source only — read it first: deploy/repo-setup.sh
sudo apt install vi-mcp     # or: sudo dnf install vi-mcp · Arch/CachyOS: sudo pacman -Syu vi-mcp
```

By hand:

```bash
# Debian 12/13, Ubuntu 24.04
sudo curl -fsSLo /usr/share/keyrings/vi-mcp.gpg https://imoes.github.io/vi-mcp-packages/vi-mcp-repo.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/vi-mcp.sources https://imoes.github.io/vi-mcp-packages/vi-mcp.sources
sudo apt update && sudo apt install vi-mcp

# Fedora 43; AlmaLinux/RHEL 10 first: sudo dnf install epel-release
sudo curl -fsSLo /etc/yum.repos.d/vi-mcp.repo https://imoes.github.io/vi-mcp-packages/vi-mcp.repo
sudo dnf install vi-mcp                               # dnf asks once to import the key: compare the fingerprint

# Arch Linux, CachyOS (packages and database signed, SigLevel = Required)
curl -fsSLo /tmp/vi-mcp-repo.asc https://imoes.github.io/vi-mcp-packages/vi-mcp-repo.asc && sudo pacman-key --add /tmp/vi-mcp-repo.asc
sudo pacman-key --lsign-key 4598315414EBF86CABD322D9730B75BFAC3036B7
curl -fsSL https://imoes.github.io/vi-mcp-packages/vi-mcp.pacman.conf | sudo tee -a /etc/pacman.conf
sudo pacman -Syu vi-mcp && sudo systemctl enable --now vi-mcp.service
```

Remove the repository again: `sudo rm /etc/apt/sources.list.d/vi-mcp.sources /usr/share/keyrings/vi-mcp.gpg` or
`sudo rm /etc/yum.repos.d/vi-mcp.repo`, on Arch the `[vi-mcp]` section from `/etc/pacman.conf` and `sudo pacman-key --delete 4598315414EBF86CABD322D9730B75BFAC3036B7`.

### From a downloaded package (Linux)

Packages are on the [releases page](https://github.com/imoes/vi-mcp/releases/latest); the package manager pulls in Python ≥ 3.11,
NumPy, scikit-learn, cryptography and PyYAML.

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb                                 # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm                              # Fedora 43 (AlmaLinux/RHEL 10: epel-release first)
sudo pacman -Syu && sudo pacman -U ./vi-mcp-<version>-1-any.pkg.tar.zst       # Arch Linux, CachyOS
sudo systemctl enable --now vi-mcp.service                                    # Arch only: the package does not enable it
sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb                # another port on first installation
```

Enterprise Linux 9 is not supported: its Python 3.9 is too old and scikit-learn is not packaged there for newer Python versions.
Removing the package keeps your memory and configuration.

### macOS (Homebrew)

```bash
brew install imoes/vi-mcp/vi-mcp                 # the tap github.com/imoes/homebrew-vi-mcp; the archive is the signed release asset
vi-mcp instance "$USER" --reflexes                # prints the token once
brew services start vi-mcp && vi-mcp setup
```

The formula puts a venv with the PyPI packages next to the code. `brew services` registers the server as a launchd agent
(`~/Library/LaunchAgents`, restarted if it stops); `vi-mcp setup` restarts it with `brew services restart vi-mcp`. Configuration
`~/.config/vi-mcp/config.json`, memory `~/.local/share/vi-mcp/vi.db`.

- **Semantic search with LM Studio** *(untested on a Mac)*: vi-mcp takes any OpenAI-compatible `/v1/embeddings`. LM Studio's local
  server offers it on port 1234 ([LM Studio docs](https://lmstudio.ai/docs/local-server)); load an embedding model there (bge-m3 matches
  the Linux default) and set `"embed": {"url": "http://127.0.0.1:1234/v1/embeddings"}` in the configuration. Its
  `/v1/chat/completions` can serve as the language model (`llm`) the same way.
- **Not on macOS yet:** the network service `vi-p2p` and vi-mcp's own embedding service (`vi-mcp embed`) are systemd units. The
  formula was tested with Homebrew on Linux, not yet on a Mac.

### Windows

`vi-mcp-<version>-x64.msi` (client and server) uses an installed Python ≥ 3.11 or a private Python from the official NuGet package of
the Python Software Foundation (SHA256 and signature checked), creates a venv with the PyPI packages, the command `vi-mcp` and —
unless `SERVER=0` — the server as scheduled task `vi-mcp` (data in `%ProgramData%\vi-mcp`). Double-clicking opens a setup dialog
(**Install**, or **Update**: configuration and memory are kept, a failed update rolls back). It needs internet access while installing.

```bat
msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [WIKI=0|HOST] [PROXY=http://proxy:3128] /l*v install.log
vi-mcp setup --claude --hook --url http://127.0.0.1:8765/mcp --token-file <file>
```

On Windows there is no interactive setup menu and no reflex sandbox (reflex code does not run) —
[docs/OPERATIONS.md](docs/OPERATIONS.md#windows). The port can be changed later on Linux and Windows with `vi-mcp port 9000`.

### Embedding model (semantic search)

Without an embedding model vi-mcp searches by words and hashtags only. With one it also finds knowledge by meaning, links similar
knowledge and gives the router meaning as a feature. On Linux and Windows the packages set up vi-mcp's own service — llama.cpp
`llama-server` with bge-m3 and the reranker bge-reranker-v2-m3 — unless an external service is configured (question `local_models`,
`VI_MCP_LOCAL_MODELS=auto|off`; on Windows a checkbox, `EMBED=1|0`). By hand:

```bash
sudo vi-mcp embed setup                 # detect the GPU, download, check, start vi-embed (127.0.0.1:8767) and vi-rerank (8768)
sudo vi-mcp embed setup --backend cpu   # or cuda | vulkan | rocm — exactly that, no fallback
vi-mcp embed status                     # installed? running? backend, device, speed
sudo vi-mcp embed remove                # back to full text only
sudo vi-mcp configure --set embed_url=http://HOST:PORT/v1/embeddings   # an external OpenAI-compatible service instead
```

`auto` tries CUDA 13, CUDA 12, Vulkan, then the CPU, and keeps a build only if it lists a device of its kind. *Measured (RTX 3070):*
4.5 ms per text on CUDA, 24.8 ms on the CPU. The reranker is switched on only if 30 documents take at most 5 s. Downloads (llama.cpp
release, GGUF models) are checked by SHA-256. Switching to a different embedding service needs the same vectors
(`vi-mcp embed compare`), or every stored vector is computed again. Details:
[docs/OPERATIONS.md](docs/OPERATIONS.md#own-embedding-service-vectors).

### Check a release

`SHA256SUMS` is signed with the release key (Ed25519, `SHA256SUMS.sig`). Keep your own copy of
[`deploy/release-schluessel.pem`](deploy/release-schluessel.pem) and compare its fingerprint once through a channel you trust:
`c88aa8ce6f0cf15652b0137ee89fd5835b9a5d22285906b092e92b0ae576dd15`
(`openssl pkey -pubin -in release-schluessel.pem -outform DER | sha256sum`).

```bash
openssl pkeyutl -verify -pubin -inkey release-schluessel.pem -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig   # "Signature Verified Successfully"
sha256sum --ignore-missing -c SHA256SUMS
# or both in one step: deploy/pruefe-release.sh <download directory> [release-schluessel.pem]
```

## Set up and configure

### Connect your AI clients

On first install this menu opens by itself; otherwise `sudo vi-mcp setup`:

```
 vi-mcp setup
 User     anna
 Server   http://127.0.0.1:8765/mcp
 Token    created per program
 ──────────────────────────────────────────────────────────────────────
 ▸ [x] Claude Code       not set up yet
   [-] Codex CLI         not found: codex not in PATH, ~/.codex missing
   [x] Hermes Agent      not set up yet
   [x] Claude Code hook  reports every action to the server (arguments masked)
 ──────────────────────────────────────────────────────────────────────
 Enter: set up    ↑↓ select · space on/off · u URL · t token · q quit
```

On the server's own machine each program gets its own instance and token; for another server press `u` (URL) and `t` (token). The
menu checks the token before writing, backs up every file it changes and touches only the `vi-mcp` entry. Without the menu:

```bash
vi-mcp setup --status
vi-mcp setup --claude --codex --hermes --hook --url https://server/vi-mcp/mcp --token-file ./token
vi-mcp setup --hermes --uninstall
```

| Program | File | Entry |
|---|---|---|
| Claude Code | `~/.claude.json`, hook in `~/.claude/settings.json` | `mcpServers.vi-mcp` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.vi-mcp]` |
| Hermes Agent | `~/.hermes/config.yaml`, token in `~/.hermes/.env` | `mcp_servers.vi-mcp` |

The Claude Code hook reports every action by itself; Hermes gets the prompt hook (knowledge before each question); Codex and other
clients report what the model calls itself. Rate work
in your prompt: `#gut` (good), `#schlecht` (bad), `#note 0.8`; a prompt starting with "no", "wrong", "nein" or "falsch" counts as a
correction. Your text never leaves the session, only the result does.

**A client on another machine** needs no package (0.71.0): the server serves its own Claude Code plugin — hooks plus the MCP connection,
URL and token as plugin options (the token goes to Claude Code's secure credential store, never into a file or a URL):

```bash
claude plugin marketplace add https://server/vi-mcp/plugins/claude/marketplace.json
claude plugin install vi-mcp@vi-mcp                       # then /plugin → vi-mcp → configure: token
```

`https://server/vi-mcp/plugins` lists what is served. These routes need no token by design: they serve only public code (the plugin and the hook of this version), never instance data, and no token is written into any of them; `"plugins": false` switches them off. Claude Code downloads the plugin archive only over https and not from a loopback
address, so behind the reverse proxy set `"public_url": "https://server/vi-mcp"` in the configuration (`"plugins": false` switches the
routes off). Use the plugin or `vi-mcp setup --hook`, not both — if both are installed, the hook handles each event once.

A new instance by hand: `sudo vi-mcp instance NAME [--reflexes] [--human]`, then restart the service; the token is shown once.
**Over stdio without a token** (on the server host, Linux): the service also listens on a local socket and the kernel tells it which
user connects — `sudo vi-mcp local anna anna`, then `claude mcp add vi-mcp -- vi-mcp stdio`.

### Two modes: token and open wiki

| Mode | Who | What |
|---|---|---|
| **Token** (default) | every instance has its own token | full use according to its rights |
| **Open wiki** (`"open": true`) | anyone who can reach the server | read what is shared, get hints, report own actions, **propose** knowledge |

In open wiki mode a proposal goes into quarantine like an import from the network. Confirming, refuting, questions to other
instances, reflexes, releases and the network need a token. A wrong token is rejected (401), never quietly turned into a guest.

### Configuration

The package asks for its configuration at first installation (Debian: debconf, later `sudo dpkg-reconfigure vi-mcp`; elsewhere
`sudo vi-mcp configure`): port, addresses, access without a token, the wiki network, a further network, the web page, a first
instance, language model, reviewer and embedding. Unattended, every setting is an environment variable `VI_MCP_<KEY>`:

```bash
sudo VI_MCP_PORT=9000 VI_MCP_WIKI=false VI_MCP_INSTANCE=claude-code VI_MCP_INSTANCE_FAMILY=claude \
     DEBIAN_FRONTEND=noninteractive apt-get install -y ./vi-mcp_<version>-1_all.deb
```

Keys: `PORT BIND DB OPEN WIKI NET_NAME NET_KIND NET_MODE NET_PUBLIC NET_START WEB WEB_BASE INSTANCE INSTANCE_FAMILY LLM_URL LLM_MODEL
REVIEWER_PROMPT EMBED_URL`. **Database:** SQLite by default; PostgreSQL optionally (`db` = `postgresql://…`, move an existing memory
with `vi-mcp db migrate --to URL`, [details](docs/OPERATIONS.md#postgresql-optional-0500)).

**Importing documentation** (Confluence, vendor manuals, a knowledge base): through its own access, not page by page with
`vi_learn`. An administrator creates an import instance (`sudo vi-mcp instance NAME --import`); a JSON-Lines file holds the pages; then
`vi-mcp docs import pages.jsonl --source confluence-it [--index X] [--prune] --token-file F`. Each page becomes one object with its
hashtags and its `host:`/`topic:` triggers at once (so it can appear as a hint before matching actions), links become edges, and the
older shape of the same pages and pages the source dropped go to the archive. Since 0.70.0 the import also takes documents and
directories directly — PDF, DOCX, XLSX, PPTX, ODT, ODS, ODP, HTML, EPUB, EML, CSV, text; DOC, XLS, PPT, RTF with LibreOffice
(`vi-mcp docs formats`, `vi-mcp docs convert DIR` to look first); a file it cannot read is listed with its reason, never skipped
silently. Step by step for people and AIs: [docs/IMPORT.md](docs/IMPORT.md).

**Indexes** keep projects apart — see [Projects and special VIs](#projects-and-special-vis-indexes).

## The network (optional)

Servers can share proven knowledge without a master: each server keeps a signed, chained logbook of what it shares and fetches from
its neighbours only what is missing. Everything foreign counts only after review on the receiving server — fixed rules, quarantine, a
review model, release.

| Kind | Who may join | What travels |
|---|---|---|
| `free` | anyone, no invitation (a start address is enough) | shared knowledge, anonymised |
| `open` | by invitation (join code) | shared knowledge, anonymised |
| `company` | by invitation, members of one organisation | shared **and internal** knowledge; never re-exported |

- **vi-wiki.org** is the public wiki network's start server (web page: https://vi-wiki.org/). A server joins it **only with
  consent** (since 0.69.8): answer yes in `sudo vi-mcp configure`, set `VI_MCP_WIKI=1` at installation, or `sudo vi-mcp net wiki on`.
  Outgoing only; the AI tells you while it is on and switches it off on request (`vi_net_switch`), administrators with
  `sudo vi-mcp net wiki off`.
- **What travels:** knowledge with a network score (the same meaning on several servers is one object with several holders, rated by
  each server's measurements), wiki pages with merge, questions and answers between AIs (`vi_ask(to="netz")`), live search
  (`vi_net_search`).
- **Peers behind firewalls** keep one long poll open at a peerhost and get news in seconds.
- **Set up:** `sudo vi-mcp net --network NAME setup --kind free|open|company …`, invitations with `vi-mcp net invitation`; a read-only
  web page with `sudo vi-mcp web on`, an internal knowledge search with sign-in with `sudo vi-mcp web internal on`.

Commands, modes and every rule: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Privacy

- **What the network never sees:** IP and MAC addresses, internal host and domain names, passwords, tokens, user names, e-mail
  addresses, proxy settings, location tags and instance names. Export replaces findings with placeholders and scans again; if anything
  still looks suspicious, the object stays home. `vi_net_preview` shows exactly what would leave.
- **Credentials are not stored locally either**, as far as their form gives them away (`password=…`, `Bearer …`, key blocks, URLs
  with logins).
- **Right to be forgotten:** without a network token an instance shares nothing; `vi_net_forget` recalls your own entries from the
  network, receivers keep only a tombstone.
- **Limits:** patterns do not understand meaning; deletion works with receivers that follow the protocol.

## Tools

| Tools | Purpose |
|---|---|
| `vi_before` · `vi_after` · `vi_feedback` | report before and after an action; which hints helped, misled or were used in one action (`before_id`, `used`) |
| `vi_learn` · `vi_recall` · `vi_drilldown` · `vi_object` · `vi_learn_search` | learn (in full, with source — tagged and qualified with question/answer pairs in the same call), search, drill down, read one object completely |
| `vi_qualify` · `vi_rate` | qualify what you just read (pairs, labels, tags in one call); rate your own conversation (a self-review, half weight) |
| `vi_tag` · `vi_confirm` · `vi_refute` · `vi_forget` · `vi_set_visibility` | change knowledge — always with a reason; each other instance is a line of its own, a review of your own object counts half |
| `vi_solved` · `vi_skills` · `vi_skill` · `vi_skill_merge` | problem → solution, skills |
| `vi_ask` · `vi_answer` · `vi_questions` | questions between instances (and to the network) |
| `vi_prompt_context` · `vi_context` · `vi_capabilities` · `vi_tools_register` · `vi_vocabulary` | knowledge for a prompt, the installation's skills (knowledge_kind:skill, extensible with vi_learn; initial: clingo, finetune, philosophy), the memory's words |
| `vi_finetune` · `vi_incubator` · `vi_philosophy` | train a model from the memory: maturity, kit, runbook; philosophy packages — handed over MCP, suggested for the situation that fits, rated after use |
| `vi_logic` · `vi_machine` | clingo-object logic over the memory; persistent VIL machines |
| `vi_model` · `vi_why` · `vi_feature_propose` · `vi_scorer` · `vi_stats` · `vi_status` · `vi_experience` | the learned model, why a hint was shown, proposals for it, scores and measurements |
| `vi_self` · `vi_self_propose` · `vi_sleep` | self-image and consolidation |
| `vi_reflex_learn` · `vi_reflex_list` · `vi_reflex_switch` | small checks as code in a sandbox |
| `vi_indexes` · `vi_code_sync` | projects and special VIs, code of a repository |
| `vi_doc_sync` | the documentation import access — only for an instance with the import right (`vi-mcp docs import`, [docs/IMPORT.md](docs/IMPORT.md)) |
| `vi_conversation` · `vi_delete_conversation` · `vi_archive` · `vi_archive_restore` | conversations and long-term storage |
| `vi_net_*` · `vi_quarantine` · `vi_release` · `vi_page_*` | the network: status, search, wiki pages, review, right to be forgotten |

Every tool with every parameter: [docs/REFERENCE.md](docs/REFERENCE.md). The tools and the command line are English; the German names
used before 0.22.0 (`vi_erinnere`, `vi_lerne`, `vi-mcp einrichten`, …) remain valid as aliases.

## Documentation

**[docs/README.md](docs/README.md)** lists every document. The most used: [REFERENCE](docs/REFERENCE.md) (generated from the code) ·
[OPERATIONS](docs/OPERATIONS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [HOOK](docs/HOOK.md) · [FINETUNING](docs/FINETUNING.md) ·
[PAPER](docs/PAPER.md) (how the memory learns, the incubator, the language VIL — with measurements and sources) ·
[CHANGELOG](CHANGELOG.md).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest clingo
.venv/bin/python -m pytest -q tests -p no:cacheprovider
deploy/release.sh            # builds every package (deb, rpm, Arch, msi, macOS formula, wheel) and signs SHA256SUMS
```

Notes for agents and contributors: [AGENTS.md](AGENTS.md). License: [AGPL-3.0](LICENSE).
