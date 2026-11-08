# vi-mcp — one memory for many AI sessions

[Deutsch](README.de.md) · **English** · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` is a **VI (virtual intelligence)**: a single server process with one memory that any number of AI sessions connect to at the same time over **MCP (Streamable HTTP)**.
Each session keeps its own conversation context, like time slices on a processor. All of them share the same memory: what one session learns shows up as a hint for the next one, right before the relevant action.
The language model itself is never changed. Learning happens in the memory, and the memory stays readable.

## Vision

**An open network of knowledge, in which AI teaches itself.** Every server learns from its own work: which hint helped, which solution held up, what a person corrected.
Whatever proves itself is anonymised, signed and shared with the other servers. Every server tests what it receives against its own work and keeps what helps there.
No central model and no central owner: a server can run on its own or join the network as a peer, and the code, the protocol and the knowledge format are open source.

This is "training" without changing weights. Knowledge becomes readable objects with sources, scores and a right to be forgotten, and the router that picks them learns from the measured outcome.
Code, API tables and commands are stored in full, because what is missing from memory is a gap.

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

- **Objects, not notes.** Everything is an object with hashtags (`kind:value`), an author and a visibility (private or shared): experience, insight, rule, skill, score.
- **Before every action** (`vi_vorher`) a session receives at most four hints. A hint is only reinforced once the action succeeds.
- **Sleep.** At night, or once enough important events pile up, the server condenses experiences, compares them with what it knows and archives what goes unused.
- **Scorer.** Code rules, the local language model and you judge whether work succeeded. "The tool did not crash" alone does not say that.
- **Learning.** From those scores the router (logistic regression, weights kept as readable JSON) learns which hint helps when.
- **Reflexes and skills.** Proven solutions become skills; small checks run as code in a sandbox (Landlock, seccomp).

The in-depth documents are written in German: [architecture](docs/ARCHITEKTUR.md) · [operations](docs/BETRIEB.md) · [hook](docs/HOOK.md) · [research](docs/FORSCHUNG.md) · [training](docs/TRAINING.md)

## Install

Packages are on the [releases page](https://github.com/imoes/vi-mcp/releases/latest). Your package manager pulls in all dependencies (Python ≥ 3.11, NumPy, scikit-learn, cryptography, PyYAML).

```bash
sudo apt install ./vi-mcp_0.13.0-1_all.deb      # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-0.13.0-1.noarch.rpm   # Fedora 43
sudo dnf install epel-release && sudo dnf install ./vi-mcp-0.13.0-1.noarch.rpm   # AlmaLinux/RHEL 10
```

**Enterprise Linux 9 is not supported:** Python 3.9 is too old, and scikit-learn is not available there for newer Python versions. Your memory and configuration are kept when the package is removed.

## Set up

On first install this menu opens by itself; otherwise run `sudo vi-mcp einrichten`. The interface is in German:

```
 vi-mcp einrichten  0.13.0

 Nutzer   anna
 Server   http://127.0.0.1:8765/mcp
          läuft noch nicht; startet nach dem Anlegen der Tokens
 Token    wird je Programm angelegt
 Aktion   einrichten
 ──────────────────────────────────────────────────────
 ▸ [x] Claude Code       noch nicht eingerichtet
   [-] Codex CLI         nicht gefunden: codex nicht im PATH, ~/.codex fehlt
   [x] Hermes Agent      noch nicht eingerichtet
   [x] Claude-Code-Hook  meldet jede Handlung an den Server (Argumente maskiert)
 ──────────────────────────────────────────────────────
 Enter: einrichten
 ↑↓ select · space toggle · u URL · t token · e add/remove · q quit
```

If the server runs on the same machine, each program gets its own instance and token. For another server, press `u` for the URL and `t` for the token.
Before writing anything, the menu checks that the server accepts the token. Every changed file gets a backup `<file>.bak-vi-mcp-<time>`, and only the `vi-mcp` entry changes.
Unattended installs never wait for a key press.

Without the menu (scripts, Ansible):

```bash
vi-mcp einrichten --status
vi-mcp einrichten --claude --codex --hermes --hook --url https://server/vi-mcp/mcp --token-datei ./token
vi-mcp einrichten --hermes --entfernen
```

| Program | File | Entry |
|---|---|---|
| Claude Code | `~/.claude.json`, hook in `~/.claude/settings.json` | `mcpServers.vi-mcp` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.vi-mcp]` |
| Hermes Agent | `~/.hermes/config.yaml`, token in `~/.hermes/.env` | `mcp_servers.vi-mcp` |

The hook exists for Claude Code only and reports actions automatically. Codex and Hermes get the tools and report only what the model calls itself.
You can rate work in your prompt: `#gut` (good), `#schlecht` (bad), `#note 0.8`. A prompt starting with "no", "wrong", "nein" or "falsch" counts as a correction. Your text never leaves the session, only the result does.

Server by hand: `sudo vi-mcp instanz NAME [--reflexe] [--mensch]`, then `sudo systemctl restart vi-mcp`. The token is shown once.

## The network

Each server keeps a signed, chained log. Servers compare logs with their neighbours and fetch only what is missing; nobody needs a shared truth, so there is no blockchain and no consensus.

| Mode | Behaviour |
|---|---|
| `standalone` (default) | no network traffic |
| `peer` | outgoing connections only, works behind a firewall; pushes its own log to its neighbours |
| `peerhost` | also accepts connections and serves others |

```bash
# first server: founds the network, self-signed certificate, peers verify it by its pin
sudo vi-mcp netz einrichten --modus peerhost --gruenden --adresse https://knowledge.example:8766 --tls-selbst
sudo vi-mcp netz einladung --stunden 24          # one-time join code, treat it like a password

# every further server: one command
sudo vi-mcp netz beitreten <code>                                                        # outgoing only (peer)
sudo vi-mcp netz beitreten <code> --modus peerhost --adresse https://b.example:8766 --tls-selbst
sudo vi-mcp netz beitreten <code> --proxy http://proxy.example:3128                      # behind a company proxy

sudo vi-mcp netz peers                           # known peers, pin or CA, reachable or not
sudo vi-mcp netz status
```

A join code contains the founders' keys, the address and certificate pin of the issuing peerhost, and a one-time secret that expires. Only its hash stays on the issuer.
Behind a reverse proxy with a public certificate use `--adresse https://host/vi-p2p` without `--tls-selbst`. Manual way without a code: `vi-mcp netz id` on the new server, `vi-mcp netz einladen <key>` on a member.

- **Membership by invitation.** A server belongs if a chain of invitations leads to it from a founder. Founders and the inviting member can expel; whoever was only invited by an expelled server leaves with it.
- **Forwarding is not believing.** A server carries signed entries onward after checking signature and rules, but its memory treats them as foreign: quarantine, the review model, release, then mode `test`.
- **Proven only.** A server shares shared, active knowledge that another instance confirmed or that measurably helped.
- **Sources earn trust.** The measured usefulness per publisher is tracked; a publisher whose hints keep failing is no longer shown (`vi_netz_status`).
- **Separate process.** `vi-p2p` runs as its own user and cannot reach the memory files; it talks to the memory through two tools only.
- **Transport.** HTTPS by default; signed requests, only members get answers. For large backlogs BitTorrent (libtorrent, private, no DHT) with HTTPS as fallback. Entries prove themselves, the path does not matter.
- Measured with three packaged servers (Ubuntu, Debian, Fedora) under systemd: knowledge crossed two hops in 27 s, a recall took effect in 4 s (poll interval 4 s).

## Privacy

**What the network never sees:** IP and MAC addresses, internal host and domain names, passwords, tokens, user names, e-mail addresses, proxy settings, location tags and instance names.
A publisher appears only as a pseudonym derived from its key, and times only as dates.
Export replaces findings with placeholders (`<host>`, `<ip>`, `<nutzer>`, `<geheimnis>`, `<proxy>`) and scans the result again. If anything still looks suspicious, the object stays home.
Import rejects every object with a finding. `vi_netz_vorschau` shows exactly what would leave and counts what is held back and why.

**Credentials are never stored locally either**, as far as their form gives them away (`password=…`, `Bearer …`, key blocks, URLs with logins). Host names and IPs stay local and private because hints depend on them.

**Right to be forgotten.** Without a network token (`vi_netz_token`, issued once) an instance shares nothing. The token yields a separate deletion proof for each object. `vi_netz_vergiss` recalls your own entries:
receivers delete them along with search index and vector, and keep only a tombstone so they cannot return. The network does not learn which instance it was, and one proof opens no other object.

**Limits:** Patterns do not understand meaning. A free-standing proper name is only caught if it is on the list of known names (`p2p.interne_namen`). Deletion works with receivers that follow the protocol; nobody can force a peer to destroy a copy. Direct neighbours see each other's IP address, and every member knows the announced address of a `peerhost`.

## Tools

| Tools | Purpose |
|---|---|
| `vi_vorher` · `vi_nachher` | report before and after an action |
| `vi_lerne` · `vi_erinnere` · `vi_vertiefe` · `vi_objekt` | learn (code and API tables in full in `inhalt`), search, drill down, read in full |
| `vi_markiere` · `vi_bestaetige` · `vi_widerlege` · `vi_vergiss` | change, always with a reason |
| `vi_frage` · `vi_antwort` · `vi_fragen` | questions between instances |
| `vi_geloest` · `vi_skills` · `vi_skill` · `vi_skill_fusion` | solutions |
| `vi_reflex_lerne` · `vi_reflex_liste` · `vi_reflex_schalte` | code in memory |
| `vi_selbst` · `vi_selbst_vorschlag` · `vi_schlaf` | self-image and consolidation |
| `vi_scorer` · `vi_modell` · `vi_erfahrung` · `vi_status` | scores, learned model, metrics, state |
| `vi_gespraech` · `vi_loesche_gespraech` · `vi_lager` · `vi_lager_hole` | conversations and long-term storage |
| `vi_netz_ausgang` · `vi_netz_eingang` · `vi_quarantaene` · `vi_freigabe` · `vi_netz_status` | network service interface, review, usefulness per publisher |
| `vi_netz_token` · `vi_netz_vergiss` · `vi_netz_vorschau` | deletion token, right to be forgotten, preview |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest
.venv/bin/python -m pytest -q tests
deploy/debian/build.sh && deploy/rpm/build.sh
```

Notes for agents: [AGENTS.md](AGENTS.md). License: [AGPL-3.0](LICENSE).
