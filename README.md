# vi-mcp — one memory for many AI sessions

[Deutsch](README.de.md) · **English** · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest) · [![Release](https://img.shields.io/github/v/release/imoes/vi-mcp?label=release)](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` is a **VI (virtual intelligence)**: a single server process with one memory that any number of AI sessions connect to at the same time over **MCP (Streamable HTTP)**.
Each session keeps its own conversation context, like time slices on a processor. All of them share the same memory: what one session learns shows up as a hint for the next one, right before the relevant action.
The language model itself is never changed. Learning happens in the memory, and the memory stays readable.

## Vision

**An open network of knowledge, in which AI teaches itself.** Every server learns from its own work: which hint helped, which solution held up, what a person corrected.
Whatever proves itself is anonymised, signed and shared with the other servers. Every server tests what it receives against its own work and keeps what helps there.
No central model and no central owner: a server can run on its own or join the network as a peer, and the code, the protocol and the knowledge format are open source.

This is "training" without changing weights. Knowledge becomes readable objects with sources, scores and a right to be forgotten, and the router that picks them learns from the measured outcome.
Code, API tables and commands are stored in full, because what is missing from memory is a gap.


## Tool names

Since 0.22.0 the tools, their parameters and enum values are English. The German names used before remain valid as aliases, so existing clients keep working.
Since 0.23.0 the command line, all output and the documentation are English too; German commands and options (`vi-mcp einrichten`, `vi-mcp netz …`, `--token-datei`) still work.

| English | Alias (German) |
|---|---|
| `vi_after` | `vi_nachher` |
| `vi_answer` | `vi_antwort` |
| `vi_archive` | `vi_lager` |
| `vi_archive_restore` | `vi_lager_hole` |
| `vi_ask` | `vi_frage` |
| `vi_before` | `vi_vorher` |
| `vi_confirm` | `vi_bestaetige` |
| `vi_conversation` | `vi_gespraech` |
| `vi_delete_conversation` | `vi_loesche_gespraech` |
| `vi_drilldown` | `vi_vertiefe` |
| `vi_experience` | `vi_erfahrung` |
| `vi_forget` | `vi_vergiss` |
| `vi_learn` | `vi_lerne` |
| `vi_learn_search` | `vi_suche_lerne` |
| `vi_model` | `vi_modell` |
| `vi_net_forget` | `vi_netz_vergiss` |
| `vi_net_inbox` | `vi_netz_eingang` |
| `vi_net_outbox` | `vi_netz_ausgang` |
| `vi_net_preview` | `vi_netz_vorschau` |
| `vi_net_status` | `vi_netz_status` |
| `vi_net_token` | `vi_netz_token` |
| `vi_object` | `vi_objekt` |
| `vi_quarantine` | `vi_quarantaene` |
| `vi_questions` | `vi_fragen` |
| `vi_recall` | `vi_erinnere` |
| `vi_reflex_learn` | `vi_reflex_lerne` |
| `vi_reflex_list` | `vi_reflex_liste` |
| `vi_reflex_switch` | `vi_reflex_schalte` |
| `vi_refute` | `vi_widerlege` |
| `vi_release` | `vi_freigabe` |
| `vi_self` | `vi_selbst` |
| `vi_self_propose` | `vi_selbst_vorschlag` |
| `vi_skill_merge` | `vi_skill_fusion` |
| `vi_sleep` | `vi_schlaf` |
| `vi_solved` | `vi_geloest` |
| `vi_stats` | `vi_statistik` |
| `vi_tag` | `vi_markiere` |

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
                           vi.db (SQLite, WAL, FTS5, 0600)
```

- **Objects, not notes.** Everything is an object with hashtags (`kind:value`), an author and a visibility (private, shared, or internal: token holders only, never the network): experience, insight, rule, skill, score.
- **Before every action** (`vi_before`) a session receives at most four hints. A hint is only reinforced once the action succeeds.
- **Sleep.** Once enough important events pile up (at night only if none ran in the last 24 hours), the server condenses experiences, compares them with what it knows and archives what goes unused.
- **Scorer.** Code rules, the local language model and you judge whether work succeeded. "The tool did not crash" alone does not say that.
- **Learning.** From those scores the router (logistic regression, weights kept as readable JSON) learns which hint helps when. Training runs on demand, about a minute after new experiences arrive (one run takes under a second), not only at night.
- **Reflexes and skills.** Proven solutions become skills; small checks run as code in a sandbox (Landlock, seccomp).

In-depth: [architecture](docs/ARCHITECTURE.md) · [operations](docs/OPERATIONS.md) · [hook](docs/HOOK.md) · research (German): [memory research](docs/FORSCHUNG.md) · [training](docs/TRAINING.md)

## How the memory works — and why it is built this way

**Like human memory, but every memory has a source.** vi-mcp keeps the kinds of memory people have:

| Human memory | vi-mcp | Where it comes from |
|---|---|---|
| episodic — "what happened" | `erfahrung` (experience): every reported action with tool, arguments, result, duration | the hook, automatically |
| semantic — "what I know" | `erkenntnis` (insight), `regel` (rule): a key statement plus the complete content and its source | `vi_learn`, imports, sleep |
| procedural — "how to do it" | `skill`: problem, steps, instructions, versions | `vi_solved`, sleep |
| cues and mnemonics | hashtags `kind:value` (`tool:`, `host:`, `thema:` …) and learned searches | everywhere |

**Recall works through cues.** Before every action the session tells the VI what it is about to do (`vi_before`). The tool, the host and the
topics become *triggers*, and the VI answers with at most four hints (working memory holds about four chunks, Cowan 2001). A hint is not
shown twice in the same conversation within an hour. Documentation (Confluence, vendor manuals) gets triggers too: a page that names a host
appears before an action on that host.

**Forgetting and sleep are features.** Unused knowledge fades along a power law and later moves to the archive (still findable, never lost
silently). When enough has happened, the server *sleeps*: it condenses experiences into insights and skills, compares new evidence with what it
knows, merges repetitions and archives what nobody needs. Surprising failures count as more important than routine — as in people.

**Why this is the clever part:**
- **The AI learns without anyone training a language model.** Knowledge is learned the moment it happens (`vi_learn`) and is available
  before the next action — not after the next training run of a model.
- **Every memory can be checked.** It has a source (command, host, time or URL), an author and a history. It can be confirmed, disputed and
  refuted — by *other* instances: no instance can confirm itself. What is wrong is marked, not quietly kept.
- **It can be forgotten.** Delete a conversation, an instance or an object, and it is gone (with a tombstone saying so). Knowledge baked into
  model weights cannot be removed like that.
- **One memory for many AIs.** Claude Code, Codex, Hermes and other clients share the same memory. What one session solved helps the next
  one, even with a different model.
- **Nothing disappears silently.** Held-back hints, truncated histories, merged duplicates and refuted knowledge are counted and named.

## What our weights are made of — and why that is clever, too

vi-mcp never trains the language model. The only weights it learns decide **which** memory to show — not **what** is true:

- **The router** is a logistic regression (scikit-learn). Every action is one observation: the triggers of the situation × the hints that
  were shown, and the label is whether the action then succeeded. The weights say, for example, "this hint before `tool:Bash` on that host
  raises the chance of success". They are stored as readable JSON in the memory object `modell:router` — every weight belongs to a named
  feature and can be inspected with `vi_model`. `vi_why` shows, for one hint, why it was shown: the stored decision and the weights that
  carried it. The router is taught through the labels (the scorer's verdicts, your feedback on a hint), never by writing weights; after
  each training it goes live only if its order of hints pays off on held-back data, and fixed rules check the weights and name what looks wrong (one feature dominating, a weight against the measured
  usefulness, an unconfirmed hint from the network, time of day as a cause).
- **The bandit** counts per hint how often an action succeeded after it was shown, compared with the base rate (Thompson sampling) — the
  fallback while the router has too little data.
- **Meaning** comes from a pre-trained embedding model (bge-m3): vectors for semantic search and for linking similar knowledge. vi-mcp
  uses it, it does not train it.

**Why this is clever:**
- **The training signal is free and honest.** Nobody labels data: the label is the outcome of real work (did the action succeed, did a
  person correct it, did the scorer accept it).
- **Small, fast, explainable.** The model is kilobytes of JSON, trains in under a second on a CPU, about a minute after new experiences —
  and every decision can be explained by the weights of named features.
- **Weights cannot invent facts.** They only order memories that exist and have a source. A wrong weight shows a less helpful hint; it
  cannot create a false statement.
- **It switches itself off when it does not help.** With too little data or a weak result on held-back data the model stays in test mode
  and the heuristic decides; a small share of the hints is exploration, so the model also learns about what it would not have shown.

## Install

Packages are on the [releases page](https://github.com/imoes/vi-mcp/releases/latest). Your package manager pulls in all dependencies (Python ≥ 3.11, NumPy, scikit-learn, cryptography, PyYAML).

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb      # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm   # Fedora 43
sudo dnf install epel-release && sudo dnf install ./vi-mcp-<version>-1.noarch.rpm   # AlmaLinux/RHEL 10
sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb                       # another port on first installation
```

**Windows** (since 0.27.0, client and server): `vi-mcp-<version>-x64.msi` uses an installed Python ≥ 3.11 or a private Python
from the official NuGet package of the Python Software Foundation (SHA256 and signature checked), a venv with the PyPI packages, the command `vi-mcp` and — unless `SERVER=0` — the server as scheduled task `vi-mcp`
(data in `%ProgramData%\vi-mcp`). Double-clicking it opens a setup dialog — **Install**, or **Update** when an earlier version is
installed (configuration and memory are kept; a failed update rolls back). It needs internet access during installation:

```bat
msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [PROXY=http://proxy:3128] /l*v install.log
vi-mcp setup --claude --hook --url http://127.0.0.1:8765/mcp --token-file <file>
```

The port can be changed later on Linux and Windows with `vi-mcp port 9000` (restarts the service). Vectors for semantic search come from
vi-mcp's own embedding service, installable at any time: `sudo vi-mcp embed setup` (llama.cpp + bge-m3, Vulkan or CPU; on Windows `EMBED=1`). On Windows there is no interactive setup
menu, no reflex sandbox (reflex code does not run) and no network service (P2P) — see [docs/OPERATIONS.md](docs/OPERATIONS.md#windows).

**Check a release before installing.** From v0.15.0 on, `SHA256SUMS` is signed with the release key (Ed25519, `SHA256SUMS.sig`). Keep your own copy of
[`deploy/release-schluessel.pem`](deploy/release-schluessel.pem) and compare its fingerprint once through a channel you trust:
`c88aa8ce6f0cf15652b0137ee89fd5835b9a5d22285906b092e92b0ae576dd15` (SHA-256 of the public key in DER form,
`openssl pkey -pubin -in release-schluessel.pem -outform DER | sha256sum`). A checksum file from the same release alone does not prove who published it.

```bash
openssl pkeyutl -verify -pubin -inkey release-schluessel.pem -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig   # "Signature Verified Successfully"
sha256sum --ignore-missing -c SHA256SUMS
# or both in one step: deploy/pruefe-release.sh <download directory> [release-schluessel.pem]
```

**Enterprise Linux 9 is not supported:** Python 3.9 is too old, and scikit-learn is not available there for newer Python versions. Your memory and configuration are kept when the package is removed.

## Two modes: token and open wiki

| Mode | Who | What |
|---|---|---|
| **Token** (default) | every instance has its own token | full use according to its rights |
| **Open wiki** (`"offen": true` in `/etc/vi-mcp/config.json`) | anyone who can reach the server, no token | read everything shared, get hints before actions, report own actions, **propose** knowledge |

The knowledge is open; writing it is not. In the open wiki mode a proposal from `vi_learn` goes into quarantine like an import from the network: rules, the review model, then release by an instance with rights.
Confirming, refuting, questions to other instances, reflexes, releases and the network need a token, otherwise any machine could plant instructions in everyone else's AI sessions.
Tokenless clients share one instance (`offen`); they get no cached tool answers, so nobody receives the result of someone else's lookup. A wrong token is still rejected (401) instead of quietly becoming a guest.

Join an open server, no token needed:

```bash
claude mcp add --transport http -s user vi-mcp https://<server>/vi-mcp/mcp
vi-mcp setup --claude --codex --hermes --hook --url https://<server>/vi-mcp/mcp     # detects the open server by itself
```

## Set up

On first install this menu opens by itself; otherwise run `sudo vi-mcp setup`:

```
 vi-mcp setup  0.23.0

 User     anna
 Server   http://127.0.0.1:8765/mcp
          not running yet; starts once the tokens are created
 Token    created per program
 Action   set up
 ──────────────────────────────────────────────────────────────────────
 ▸ [x] Claude Code       not set up yet
   [-] Codex CLI         not found: codex not in PATH, ~/.codex missing
   [x] Hermes Agent      not set up yet
   [x] Claude Code hook  reports every action to the server (arguments masked)
 ──────────────────────────────────────────────────────────────────────
 Enter: set up
 ↑↓ select · space on/off · u URL · t token · e action · q quit
```

If the server runs on the same machine, each program gets its own instance and token. For another server, press `u` for the URL and `t` for the token.
Before writing anything, the menu checks that the server accepts the token. Every changed file gets a backup `<file>.bak-vi-mcp-<time>`, and only the `vi-mcp` entry changes.
Unattended installs never wait for a key press.

Without the menu (scripts, Ansible):

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

The hook exists for Claude Code only and reports actions automatically. Codex and Hermes get the tools and report only what the model calls itself.
You can rate work in your prompt: `#gut` (good), `#schlecht` (bad), `#note 0.8`. A prompt starting with "no", "wrong", "nein" or "falsch" counts as a correction. Your text never leaves the session, only the result does.

Server by hand: `sudo vi-mcp instance NAME [--reflexes] [--human]`, then `sudo systemctl restart vi-mcp`. The token is shown once.

**Over stdio, without a token (on the server host, Linux):** the service also listens on a local socket (`/run/vi-mcp/mcp.sock`);
the kernel tells it which local user connects. Allow a user once, then register the client:

```bash
sudo vi-mcp local anna anna          # local user anna reaches the VI as instance anna (internal knowledge included)
claude mcp add vi-mcp -- vi-mcp stdio
codex mcp add vi-mcp -- vi-mcp stdio
```

Users not allowed get a refusal that names the command above. `vi-mcp local` lists who is allowed.

## The network

Each server keeps a signed, chained log. Servers compare logs with their neighbours and fetch only what is missing; nobody needs a shared truth, so there is no blockchain and no consensus.

| Mode | Behaviour |
|---|---|
| `standalone` (default) | no network traffic |
| `peer` | outgoing connections only, works behind a firewall; pushes its own log to its neighbours |
| `peerhost` | also accepts connections and serves others |

```bash
# first server: founds the network, self-signed certificate, peers verify it by its pin
sudo vi-mcp net setup --mode peerhost --found --address https://knowledge.example:8766 --tls-self
sudo vi-mcp net invitation --hours 24            # one-time join code, treat it like a password

# every further server: one command
sudo vi-mcp net join <code>                                                              # outgoing only (peer)
sudo vi-mcp net join <code> --mode peerhost --address https://b.example:8766 --tls-self
sudo vi-mcp net join <code> --proxy http://proxy.example:3128                            # behind a company proxy

sudo vi-mcp net peers                            # known peers, pin or CA, reachable or not
sudo vi-mcp net status
```

A join code contains the founders' keys, the address and certificate pin of the issuing peerhost, and a one-time secret that expires. Only its hash stays on the issuer.
Behind a reverse proxy with a public certificate use `--address https://host/vi-p2p` without `--tls-self`. Manual way without a code: `vi-mcp net id` on the new server, `vi-mcp net invite <key>` on a member.

- **Membership by invitation.** A server belongs if a chain of invitations leads to it from a founder. Founders and the inviting member can expel; whoever was only invited by an expelled server leaves with it.
- **Forwarding is not believing.** A server carries signed entries onward after checking signature and rules, but its memory treats them as foreign: quarantine, the review model, release, then mode `test`.
- **Proven only.** A server shares shared, active knowledge that an independent line confirmed (another model family, not from the object's own source) or that measurably helped.
- **Sources earn trust.** The measured usefulness per publisher is tracked; a publisher whose hints keep failing is no longer shown (`vi_net_status`).
- **Separate process.** `vi-p2p` runs as its own user and cannot reach the memory files; it talks to the memory through two tools only.
- **Several networks (0.39.0).** Besides the network `standard` a server can join further networks, each with its own service and key:
  `sudo vi-mcp net --network firma setup --kind firma …`. A *company* network (`firma`, one organisation) carries shared and internal
  knowledge without anonymising, and its imports stay internal; an *open* network (`offen`) works as described here. `vi_net_status`
  and `vi_stats` (section W) show every network with peers, versions and backlog.
- **The same information, checked by hash (0.40.0).** Every server computes a content hash itself; the same meaning from several servers
  is one object with several *holders*. Servers publish their own measurements per content, and every server computes a **network
  score** from them: capped per server, weighted by its measured benefit, never counting a server's rating of its own content.
  `vi_object` shows it; a content that keeps failing is no longer offered as a hint.
- **Network wiki (0.41.0).** Pages every server of a network may edit, without a master: `vi_page_write` (with the revision you
  edited), `vi_page_read`, `vi_page_history`. Revisions are signed and content-addressed; concurrent changes in different paragraphs
  merge by themselves, overlapping ones become a named conflict that any member resolves. Foreign changes count only after review.
- **Live search (0.42.0).** `vi_net_search` asks the members of a network now — signed answers from their memories, under the same
  export rules as everything else, checked, merged by content hash, never stored; `take` sends one through review.
- **Port 443 (0.40.0).** `--public https://HOST` publishes a network as `https://HOST/vi-p2p/<network>` behind the reverse proxy;
  `vi-mcp net proxy-config` prints the nginx configuration. All networks share 443.
- **Transport.** HTTPS by default; signed requests, only members get answers. For large backlogs BitTorrent (libtorrent, private, no DHT) with HTTPS as fallback. Entries prove themselves, the path does not matter.
- Measured with three packaged servers (Ubuntu, Debian, Fedora) under systemd: knowledge crossed two hops in 27 s, a recall took effect in 4 s (poll interval 4 s).

## Privacy

**What the network never sees:** IP and MAC addresses, internal host and domain names, passwords, tokens, user names, e-mail addresses, proxy settings, location tags and instance names.
A publisher appears only as a pseudonym derived from its key, and times only as dates.
Export replaces findings with placeholders (`<host>`, `<ip>`, `<nutzer>`, `<geheimnis>`, `<proxy>`) and scans the result again. If anything still looks suspicious, the object stays home.
Import rejects every object with a finding. `vi_net_preview` shows exactly what would leave and counts what is held back and why.

**Credentials are never stored locally either**, as far as their form gives them away (`password=…`, `Bearer …`, key blocks, URLs with logins). Host names and IPs stay local and private because hints depend on them.

**Right to be forgotten.** Without a network token (`vi_net_token`, issued once) an instance shares nothing. The token yields a separate deletion proof for each object. `vi_net_forget` recalls your own entries:
receivers delete them along with search index and vector, and keep only a tombstone so they cannot return. The network does not learn which instance it was, and one proof opens no other object.

**Limits:** Patterns do not understand meaning. A free-standing proper name is only caught if it is on the list of known names (`p2p.interne_namen`). Deletion works with receivers that follow the protocol; nobody can force a peer to destroy a copy. Direct neighbours see each other's IP address, and every member knows the announced address of a `peerhost`.

## Tools

| Tools | Purpose |
|---|---|
| `vi_before` · `vi_after` | report before and after an action |
| `vi_learn` · `vi_recall` · `vi_drilldown` · `vi_object` | learn (code and API tables in full in `inhalt`; images with description and regions in SAM 3 format, `vi-mcp image FILE …`), search, drill down, read in full (with the image) |
| `vi_tag` · `vi_confirm` · `vi_refute` · `vi_forget` | change, always with a reason |
| `vi_ask` · `vi_answer` · `vi_questions` | questions between instances |
| `vi_solved` · `vi_skills` · `vi_skill` · `vi_skill_merge` | solutions |
| `vi_reflex_learn` · `vi_reflex_list` · `vi_reflex_switch` | code in memory |
| `vi_self` · `vi_self_propose` · `vi_sleep` | self-image and consolidation |
| `vi_scorer` · `vi_model` · `vi_why` · `vi_set_visibility` · `vi_experience` · `vi_status` | scores, learned model, why a hint was shown, switch shared/internal, metrics, state |
| `vi_conversation` · `vi_delete_conversation` · `vi_archive` · `vi_archive_restore` | conversations and long-term storage |
| `vi_net_outbox` · `vi_net_inbox` · `vi_quarantine` · `vi_release` · `vi_net_status` | network service interface, review, usefulness per publisher |
| `vi_net_token` · `vi_net_forget` · `vi_net_preview` | deletion token, right to be forgotten, preview |
| `vi_page_read` · `vi_page_write` · `vi_page_history` · `vi_page_forget` | network wiki: read, edit, history, revoke a revision |
| `vi_net_search` | live search in a network; take a hit into review |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest
.venv/bin/python -m pytest -q tests
deploy/debian/build.sh && deploy/rpm/build.sh
```

Notes for agents: [AGENTS.md](AGENTS.md). License: [AGPL-3.0](LICENSE).
