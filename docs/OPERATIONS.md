# Operations

Two ways: **Debian package** (server, system service with its own user — production) or **user service** from the
working tree (development).

## Debian package (server)

**Updates from the package repository (0.54.0):** add the signed apt/dnf repository once (README, "From the package repository"), and
every release comes with `apt upgrade` / `dnf upgrade`; `deploy/release.sh --gh` publishes into it. https://imoes.github.io/vi-mcp-packages/

```bash
deploy/debian/build.sh                         # → dist/vi-mcp_<version>-1_all.deb (only dpkg-deb needed)
scp dist/vi-mcp_0.1.0-1_all.deb host:/tmp/ && ssh host sudo dpkg -i /tmp/vi-mcp_0.1.0-1_all.deb
ssh host 'sudo vi-mcp instance <name> [--reflexes]' > ~/.config/vi-mcp/token-<name>-<host>   # token is printed ONCE, store it 0600
ssh host sudo systemctl restart vi-mcp
```

The German command names (`instanz`, `--reflexe`, `einrichten`, `netz`, …) remain valid as aliases.

| What | Where |
|---|---|
| Code | `/usr/lib/python3/dist-packages/vi_mcp/`, command `/usr/bin/vi-mcp` |
| Service | `vi-mcp.service` (system), user/group `vi-mcp`, hardened (`ProtectSystem=strict`, `ProtectHome`, no capabilities; `systemd-analyze security`: 3.6 OK) |
| Configuration | `/etc/vi-mcp/config.json` — `root:vi-mcp 0640`, directory `0750`; `vi-mcp instance` keeps these permissions |
| Memory | `/var/lib/vi-mcp/vi.db` — `vi-mcp:vi-mcp 0600`, directory `0700` |
| Measurement (0.55.0) | `/var/lib/vi-mcp/eval/recall.json` (question set, internal content, 0600) and `verlauf.jsonl` (one line per day); written by sleep step `9_pruefung` |
| Log | `journalctl -u vi-mcp` |
| Hook script for clients | `/usr/share/vi-mcp/hook/vi_hook.py` |

`dpkg -r vi-mcp` leaves memory and configuration in place; `dpkg -P vi-mcp` deletes both and the user.
Without an instance the service stays off after installation, and `postinst` says what to do.

**Production installation:** host, access, instances and paths are in `docs/LOKAL.md` — deliberately **not** in the repo
(`.gitignore`); here there are placeholders such as `<host>` and `<docker-gateway>`. Tested on Ubuntu 24.04.5,
Python 3.12.3, SQLite 3.45.1 with FTS5. Acceptance: see CHANGELOG.

### Access from outside: `https://<host>/vi-mcp/mcp`

```
Client ──TLS──▶ nginx (container, <docker-network>, certificate <certificate>)
                 location /vi-mcp/  → rewrite → http://<docker-gateway>:8765   (gateway of the Docker network <docker-network>)
                                                     │
                 vi-mcp (system service on the host) ◀┘  bind ["127.0.0.1", "<docker-gateway>"], one process
```

- vi-mcp listens on two addresses: `127.0.0.1` (the host itself) and `<docker-gateway>` (for the nginx container; the
  container cannot reach the host's `127.0.0.1`). `IP_FREEBIND` allows starting before Docker creates the network.
- nginx: block `location /vi-mcp/` in `<nginx.conf>`, backup
  `<backup of nginx.conf>`. Change only with `docker exec nginx nginx -t && docker exec nginx nginx -s reload`
  (no restart). vi-mcp does the authentication itself; no API key from nginx. The block needs `client_max_body_size 8m` (= `server.MAX_BODY`):
  since 0.35.0 an image of up to 5 MiB arrives base64-encoded in one request, and nginx's default of 1 MiB would refuse it with 413.
- **Assumption with observation point:** the gateway stays `<docker-gateway>` as long as the Docker network `<docker-network>`
  is not recreated. If it changes, `https://<host>/vi-mcp/health` returns 502 — then
  `docker network inspect <docker-network>` and adjust `bind` in `/etc/vi-mcp/config.json` + `proxy_pass`.
- Check: `curl -s https://<host>/vi-mcp/health` → `ok vi-mcp <version>`.

### PostgreSQL (optional, 0.50.0)

SQLite stays the default: no server, nothing to install. PostgreSQL pays off when a database becomes large, when the public web page of
a wiki server gets many readers, or when backups have to run while the service keeps writing. vi-mcp writes SQLite SQL; `vi_mcp/db.py`
translates it for PostgreSQL (placeholders, `INSERT OR IGNORE/REPLACE`, `LIKE` → `ILIKE`, JSON functions, full text as `tsvector`), so
the code has one set of statements and the whole test suite runs against both.

**1. Database and driver** (PostgreSQL 12 or newer — generated columns, `CREATE OR REPLACE AGGREGATE`; tested with 16):

```bash
sudo apt install postgresql python3-psycopg            # Debian/Ubuntu; Fedora/RHEL: dnf install postgresql-server 'python3dist(psycopg)'
sudo -u postgres createuser vi-mcp
sudo -u postgres createdb -O vi-mcp vi-mcp
```

The service user `vi-mcp` then reaches its database over the local socket without a password (peer authentication):
`postgresql://vi-mcp@/vi-mcp?host=/var/run/postgresql`. Another host: `postgresql://vi-mcp@db.example/vi-mcp` with the password in
`/var/lib/vi-mcp/.pgpass` (0600, `host:5432:vi-mcp:vi-mcp:PASSWORD`) — **never in the URL**; `vi-mcp configure` refuses a URL with a
password, because the configuration and debconf are no place for it.

**2. Move the data** (an existing installation; a new one skips this):

```bash
sudo systemctl stop vi-mcp
sudo -u vi-mcp vi-mcp db migrate --to 'postgresql://vi-mcp@/vi-mcp?host=/var/run/postgresql'
```

`migrate` reads a consistent snapshot of the SQLite file, creates every table and index in the target schema, copies the rows and
compares the row count of every table; it prints each table `source → target` and stops with an error if one differs. The long-term
archive (`vi-lager.db`) goes into the schema `<schema>_lager`. It only writes into an empty schema. The SQLite file stays untouched —
it is the way back.

**3. Switch:**

```bash
sudo vi-mcp configure --set 'db=postgresql://vi-mcp@/vi-mcp?host=/var/run/postgresql'    # restarts the service
vi-mcp db status        # database: PostgreSQL 16.x · postgresql://vi-mcp@/vi-mcp?… · schema public · N objects
```

`configure` refuses the switch while the PostgreSQL database holds fewer objects than the SQLite file (it names both counts), so the
memory never starts empty by mistake. Unattended: `VI_MCP_DB=postgresql://…` at installation, like every other key. Back to SQLite:
`vi-mcp configure --set db=` — the file then has the state of the migration.

**Schema:** without anything else the tables go into `public`. Another schema: `…/vi-mcp?options=-csearch_path%3Dvi` (created if missing).

**Network logbooks** (`vi-p2p@<netz>`): `"db"` in `/etc/vi-p2p/<netz>.json` takes the same URL; every network gets its own schema
`netz_<name>`, so two networks never share tables. Moving an existing logbook keeps the server's own chain:

```bash
sudo systemctl stop vi-p2p@wiki
sudo -u vi-p2p vi-mcp db migrate --from /var/lib/vi-p2p/wiki/netz.db --to 'postgresql://vi-p2p@/vi-mcp?host=/var/run/postgresql' --schema netz_wiki
# then "db": "postgresql://vi-p2p@/vi-mcp?host=/var/run/postgresql" in /etc/vi-p2p/wiki.json, start the service
```

**What differs from SQLite** (measured 11.11.2026 with 10,000 synthetic objects, PostgreSQL 16 in a local container over TCP, one client):

| | SQLite | PostgreSQL |
|---|---|---|
| hashtag search (`thema:docker`, `host:…`) | 0.4–6.5 ms | 1.4–17.8 ms, same hits in the same order |
| free-text search (`borg restore`) | 24 ms, BM25 | 45 ms, `ts_rank` — the same documents match, the order among equally good hits differs (top 10 overlap 4–8 of 10) |
| migration | — | 159,690 rows in 2.2 s, every count equal |

One client is slower on PostgreSQL (a round trip per statement); it gains with many readers and large data, which this measurement does not
cover. Full text uses the `simple` configuration (no stemming), like FTS5's `unicode61`.

**Not available on PostgreSQL:** `VACUUM` of the archive (autovacuum does it); the view `beobachtung` returns JSON booleans as `true`/`false`
text instead of 1/0. Tests about SQLite files (permissions 0600, migration of 0.1 files) are skipped there.

**Development:** `VI_MCP_TEST_PG=postgresql://USER@HOST/DB .venv/bin/python -m pytest -q tests` runs the whole suite against a throw-away
database; every test gets its own schema.

## Connecting Claude Code (this server)

```bash
claude mcp add --transport http -s user vi-mcp https://<host>/vi-mcp/mcp \
  --header "Authorization: Bearer $(cat ~/.config/vi-mcp/token-anna-<host>)"
```

### Network wiki on port 443 (0.40.0)

Every network runs over TLS on 443, each under its own path; TLS ends at the reverse proxy, the network services listen without TLS
on a local address only (one service per network, ports from 8766 upward):

```
Peer ──TLS:443──▶ nginx  location /vi-p2p/standard/ → http://127.0.0.1:8766/   (vi-p2p)
                         location /vi-p2p/firma/    → http://127.0.0.1:8767/   (vi-p2p@firma)
```

```bash
sudo vi-mcp net setup --mode peerhost --found --public https://<host>                              # network standard (open)
sudo vi-mcp net --network firma setup --mode peerhost --found --kind company --public https://<host>  # company network
sudo vi-mcp net proxy-config        # prints the location blocks for nginx
nginx -t && systemctl reload nginx  # in a container: docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

- Peers verify the certificate of the proxy via the CA (no pin needed with a public certificate). Outgoing connections are HTTPS to
  port 443 as well, so a company proxy (`--proxy`) or a firewall that only allows 443 is enough.
- If nginx runs in a container, it cannot reach the host's `127.0.0.1`: give `--bind <docker-gateway>`; `proxy-config` then names that
  address.
- Torrent for large backlogs uses its own port and is off unless switched on; for a network on 443 only, leave it off.
- Check: `curl -s https://<host>/vi-p2p/firma/netz/health` → `{"zustand": "ok", "version": "…"}`.

### Public wiki network vi-wiki.org (0.47.0)

- A new installation runs `nach-installation.sh wiki`, which equals `sudo vi-mcp net wiki on`: free network `wiki`, mode `peer`
  (outgoing), start `https://vi-wiki.org/vi-p2p/wiki`. Opt out: `VI_MCP_KEIN_WIKI=1 apt install ./vi-mcp_….deb`.
- Existing servers: `sudo vi-mcp net wiki on` to join, `off` to stop the service (config and logbook stay), `status`.
  Another wiki server (0.54.1): `sudo vi-mcp net wiki on --start wiki.example.org` (host name or https address; replaces the start address).
- The AI can switch the network off and on in the memory (`vi_net_switch`); the service keeps running but pauses. `vi_net_status`
  shows who switched, when and why.
- The start server: a peerhost of the network `wiki` on vi-wiki.org (443, `--public https://vi-wiki.org`, `vi-mcp web on`).

### Web page (0.46.0)

```bash
sudo vi-mcp web on --base /web          # or --base /vi-mcp/web if it goes through the existing /vi-mcp/ location
sudo vi-mcp web                         # shows on/off and the base path
```

nginx (inside the `server` block on 443), when the page should live under `/web/`:

```
location /web/ { proxy_pass http://127.0.0.1:8765/web/; proxy_set_header X-Forwarded-For $remote_addr; }
```

The page is read-only and public on purpose. It shows only networks of kind `free` and `open`; `vi-mcp web off` switches it off.
Check: `curl -s https://<host>/web/ | grep -c "VI network"`.

### Classification for the AI language (0.62.0)

```bash
vi-mcp classify --dry-run          # how many knowledge objects have no label of the current prompt version
vi-mcp classify --limit 20         # label them now (two prompt variants per object, the server's llm or config classify)
```

- `config.json`: `"classify": {"url": "https://<llm-host>/<model>/v1/chat/completions", "model": "<name>", "per_sleep": 10}`. Only with this key
  does sleep (step `8f_klassifizieren`) label new knowledge by itself — a shared language model is not loaded unasked.
- Labels are hashtags `answers:how|why|what|who|where|rule|unsure` and `memory:fact|procedure|episode|rule|unsure`, the version in
  `daten.klasse.version` (model, prompt hash, schema). `ask.<type>` in `vi_recall` puts objects labelled for that type first.
- Cost measured on a shared llama.cpp server (13.11.2026): median 42 s, 90th percentile 126 s per call, two calls per object.
- Migration of an existing memory: what searches return unlabelled is labelled first (student at once, else queued for sleep);
  `vi-mcp classify --limit N` works through the rest by hand.
- The student (`modell:klassen`, `vi_model`-like object in memory): trained in sleep from ≥ 120 agreed labels, active from 80 % holdout
  accuracy; it labels where it is ≥ 80 % sure, 10 % of those are audited by the language model (`daten.pruefung`: checked, equal).

### Sleep on a workstation (0.62.0)

A server that is not up around the clock catches a missed sleep up by itself: older than 24 h, the server up for 5 minutes, no MCP request
for 10 minutes. On a workstation set `"sleep": {"workstation": true, "idle_min": 10}` in `config.json` (or answer the question in
`vi-mcp configure`): then sleep also waits for such a quiet moment when enough new experiences have accumulated. The sleep report names
the reason (`catch-up: last sleep … h ago`, `… workstation quiet`).

### Incubator (0.62.0)

```bash
vi-mcp incubator status                 # every maturity criterion: threshold, value, state (✓ met · open · ? not measured)
vi-mcp incubator status --index cue-print --json
vi-mcp incubator hatch /srv/vi-hatched  # when mature: the training data plus the incubator state in manifest and datasheet
```

Thresholds in `config.json`: `"incubator": {"min_knowledge": 500, "min_checked": 0.2, "min_mrr": 0.6, "min_auc": 0.75, "min_labelled": 0.5,
"min_examples": 1000}`.

### Gold labels (0.62.0)

People set gold labels on the article page of the internal search (`/intern/o/<id>`, form "Gold label") — only instances with
`"human": true` in `config.json` see it (`vi-mcp instance NAME --human`). `vi-mcp incubator status` shows the
model's accuracy against them and the truth check (confirmed vs refuted knowledge by measured weight).

### Logic layer (0.62.0)

`vi_logic` needs clingo in the server's Python. Fedora/RHEL: `dnf install python3-clingo` (the RPM recommends it). Debian/Ubuntu have no
package:

```bash
sudo vi-mcp logic install          # pip --target /var/lib/vi-mcp/python clingo==5.8.3 (needs python3-pip; behind a proxy set https_proxy)
vi-mcp logic status                # "logic layer: clingo 5.8.3" or why it is off
sudo systemctl restart vi-mcp      # the running server loads it on restart
vi-mcp logic check rules.lp        # a file in the notation: what follows, violated never(…), rule weights
vi-mcp logic ask rules.lp 'forbidden(run("freeipa","gate1"))'
```

The directory is appended to the import path after the system's packages, so a later `python3-clingo` from the distribution wins. After a
Python upgrade (another minor version) the compiled parts no longer load — `vi-mcp logic status` names it; run the install again.
`VI_MCP_EXTRA_PYTHON` points to another directory. Rule weights live in table `logik_gewicht` and are copied by `vi-mcp db migrate` like
every table.

### Fine-tuning (0.62.0)

```bash
vi-mcp finetune guide                                   # the handbook
vi-mcp finetune plan [--base Qwen/Qwen3-4B]             # mature? the steps for this server
vi-mcp finetune kit /srv/vi-finetune --base Qwen/Qwen3-4B [--force]
# on the GPU host, in a venv with torch (CUDA or ROCm), trl, peft, datasets (bitsandbytes for --qlora):
cd /srv/vi-finetune && python train.py --stage sft [--qlora] && LLAMA_CPP=~/llama.cpp BASE_HF=~/models/Qwen3-4B ./convert.sh sft
python evaluate.py --base http://host:8080/v1/chat/completions --tuned http://host:8081/v1/chat/completions
vi-mcp finetune record /srv/vi-finetune                 # model object modell:finetune:<time> with lineage and evaluation
```

`config.json`: `"finetune": {"base_model": "Qwen/Qwen3-4B"}` sets the default base model.

### Training data for fine-tuning (0.62.0)

```bash
vi-mcp dataset export /srv/vi-dataset                # qa.jsonl, kto.jsonl, dpo.jsonl, manifest.json, DATASHEET.md (0600, directory 0700)
vi-mcp dataset export /srv/vi-dataset-cue --index cue-print
```

Read `DATASHEET.md` first: counts, what was left out and why, the evaluation hold-out, the scrubbing audit, label quality and versions.
The files are internal (company knowledge unanonymised). Format: `qa` in the chat format most SFT tools read (`messages`), `kto` with
`prompt`/`completion`/`label`, `dpo` with `prompt`/`chosen`/`rejected`.

### Internal knowledge search (0.62.0)

```bash
sudo vi-mcp web internal on --base /vi-mcp/intern   # path the browser sees; scopes the session cookie
sudo vi-mcp web internal                            # shows on/off and the base path
```

- Behind a reverse proxy that already passes `/vi-mcp/` to the server (prefix stripped), nothing changes there: `/vi-mcp/intern/` reaches
  `/intern/`. Otherwise: `location /intern/ { proxy_pass http://127.0.0.1:8765/intern/; proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header Host $host; }`. The sign-in check compares the form's `Origin` with `Host` (or `X-Forwarded-Host`), or with `origins`
  of the config.
- Sign-in with the token of an instance (the same tokens as `/mcp`); a session lasts 8 h and lives in the server process — a restart
  signs everybody out.
- Check: `curl -s -o /dev/null -w '%{http_code}' https://<host>/vi-mcp/intern/` → 200 (form); a wrong token → 401;
  `vi_stats` A lists `web_search` calls (count, duration, hits — never the query).

### Free network (0.45.0)

```bash
# the first server (reachable on 443 behind nginx)
sudo vi-mcp net --network welt setup --kind free --mode peerhost --public https://<host>
# every further server: only a start address, no invitation
sudo vi-mcp net --network welt setup --kind free --mode peerhost --public https://<own host> --start https://<host>/vi-p2p/welt
sudo vi-mcp net --network welt block <key|address>     # local; unblock to undo
```

- The first start computes the identity proof (`arbeit_bits`, default 26: about 30 s, on slow hardware a minute or two); the log
  names the time.
- All servers of a free network need 0.45.0 or newer, and the same `arbeit_bits` or less.
- `quote_neu` (default 100) limits entries per day of publishers this server has not measured as useful.

### Memory for every prompt (0.44.0)

- Claude Code: `vi-mcp setup --hook` registers `UserPromptSubmit` (besides Pre/PostToolUse and SessionEnd). Clients that write their own
  hook list (e.g. a console that mixes `settings.json` itself) must add `UserPromptSubmit` there.
- 0.59.0: also `Stop` — once per session, when at least three hints were shown and no feedback came, the turn is held once with a
  request for one `vi_feedback` call. Off with `VI_MCP_FEEDBACK_NUDGE=0`. Existing clients: run `vi-mcp setup --hook` again.
- Hermes: `vi-mcp setup --hermes` adds the shell hook `pre_llm_call` (`python3 -I …/vi_hook.py --hermes`) and
  `~/.config/vi-mcp/hook-hermes.json` + `token-hermes`. Hermes asks once for consent; without a terminal: `hooks_auto_accept: true`,
  `--accept-hooks` or `HERMES_ACCEPT_HOOKS=1`. Test: `hermes hooks test pre_llm_call --payload-file p.json`.
- Outage: the hook goes on without memory and names the reason in `~/.cache/vi-mcp/hook/hook.log`.

## User service (development)

```bash
cd ~/Dev/code/vi-mcp
deploy/install.sh            # instance $USER (with reflex permission), set up and start the service
```

`install.sh` is idempotent and does exactly this:

1. If the instance does not exist yet: `python3 -m vi_mcp instance $USER --reflexes` → configuration
   `~/.config/vi-mcp/config.json` (0600, only the SHA-256 of the token) and token file `~/.config/vi-mcp/token-$USER` (0600).
2. `deploy/vi-mcp.service` → `~/.config/systemd/user/vi-mcp.service`, `enable --now`, `restart`.
3. Checks `GET /health`.

The service keeps running without a login if lingering is enabled (`loginctl show-user $USER -p Linger`).

## Configuration

`$VI_MCP_CONFIG` or `~/.config/vi-mcp/config.json` (on Windows `%ProgramData%\vi-mcp\config.json`; English keys since 0.51.0 — the German keys of older files such as `instanzen`, `reflexe` are still read
and rewritten in English at the next package install, a copy of the old file stays next to it):

```json
{
  "bind": "127.0.0.1",
  "port": 8765,
  "db": "~/.local/share/vi-mcp/vi.db",
  "instances": {"anna": {"token_sha256": "…", "reflexes": true}},
  "ttl": {"netbox_get_devices": 600},
  "origins": ["http://localhost", "http://127.0.0.1"]
}
```

| Field | Meaning | Default |
|---|---|---|
| `bind`, `port` | where the server listens | `127.0.0.1`, `8765` |
| `db` | memory file (local file system, **no** NFS/SMB), or since 0.50.0 a `postgresql://` URL (see below) | `~/.local/share/vi-mcp/vi.db` |
| `instances` | who may access (instances); `reflexes: true` = may learn/switch reflexes | — (without an instance the server does not start) |
| `ttl` | validity of remembered answers per tool in s (max 3600) | 120 s |
| `origins` | allowed `Origin` headers (browser clients); requests without an Origin are allowed | localhost |

Every other key (`open`, `local`, `web`, `web_base`, `archive_days`, `p2p` with the networks, `reviewer_prompt`, `embed` …) and every
field of the network service's `/etc/vi-p2p/<network>.json` is listed with its meaning and default in the generated
[reference](REFERENCE.md).

Another instance (e.g. an agent on the same host, without reflex permission):

```bash
python3 -m vi_mcp instance agent-x          # prints the token ONCE
systemctl --user restart vi-mcp             # the configuration is read at startup
```

## Connecting Claude Code

```bash
claude mcp add --transport http -s user vi-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.config/vi-mcp/token-$USER)"
```

New sessions then see the tools `mcp__vi-mcp__vi_*`. Every Claude Code session is its own conversation.

## Checking

| Question | Command |
|---|---|
| Is it running? | `systemctl --user status vi-mcp` · `curl -s http://127.0.0.1:8765/health` |
| What does it say? | `journalctl --user -u vi-mcp -f` (one line per session start/end, errors, loop rules) |
| Exactly one process on the file? | `fuser -v ~/.local/share/vi-mcp/vi.db` |
| Memory status | tool `vi_status` (open conversations, objects, loop errors) |
| Does the search find what it should? | `vi_stats` section P (daily measurement); by hand against a copy: `python3 scripts/eval_recall.py --db COPY.db --questions recall.json [--embed-url URL]` |
| Tests | `python3 -m pytest -q tests` |

## Merging repeated findings (one-time)

Clients that learned the same recurring finding again and again before 0.23.0 (each time with a new text and a higher repetition
counter) can be cleaned up once. The key is taken from the text with a regular expression (group 1); per key, the oldest object stays,
gets the newest text and keeps every earlier state in `daten.history`; the others get mode `aufgegangen` with `daten.merged_into` and
drop out of searches — nothing is deleted. Afterwards the client should send `vi_learn(key=…)` so no new repetitions arise.

```bash
sudo systemctl stop vi-mcp                                                          # one writer
sudo -u vi-mcp vi-mcp merge-repeats <instance> '— Filter:\s*(.+)$'                 # dry run: counts only
sudo -u vi-mcp vi-mcp merge-repeats <instance> '— Filter:\s*(.+)$' --apply
sudo systemctl start vi-mcp
```

**Switch visibility afterwards** (0.30.0): `sudo vi-mcp visibility "art_wissen:handbuch" internal "company host names"` counts what would
change; add `--apply` to switch. It calls the running service with the release token (`/etc/vi-mcp/freigabe-token`), only `shared` ↔
`internal`, private objects never; each change is in the object's history. Copies already on the network: `vi_net_forget`.

## Own embedding service (vectors)

Semantic search, near-duplicate detection and the meaning features of the router need vectors. Until 0.27.0 they came only from an
external OpenAI-compatible service (`embed.url`). Since 0.28.0 vi-mcp brings its own, installable at any time, on Linux and Windows:

```bash
sudo vi-mcp embed setup                 # download, check, start the service vi-embed on 127.0.0.1:8767, switch embed.url, restart vi-mcp
sudo vi-mcp embed setup --no-switch     # install and start only — compare first:
sudo -u vi-mcp vi-mcp embed compare     # re-embeds 30 stored texts and compares (cosine); "same vectors" → switch with `embed setup`
vi-mcp embed status · sudo vi-mcp embed remove
```

- **What it installs** (0.60.0): llama.cpp `llama-server` (release b11938) in the build that fits the hardware — CUDA 13 / CUDA 12 with an
  NVIDIA driver ≥ 580 / ≥ 525 (with the CUDA runtime), Vulkan with another GPU, else the CPU; a build is accepted only if
  `--list-devices` names its device, the service answers and the speed is measured. Models: bge-m3 Q4_K_M (embedding, byte-identical with
  the file the existing vectors were made with, same parameters: mean pooling, context 8192 — stored vectors stay valid; CUDA and CPU
  vectors agree to cosine ≥ 0.9968) and bge-reranker-v2-m3 Q4_K_M (reranker, the file and parameters the search was measured with).
  All SHA256-checked. `--backend`, `--rerank auto|force|off`, `--model-file`, `--port`; the last report is kept in `embed/setup.json`.
- **Packages** (0.60.0): question `local_models` (`auto` default, `off`), run as `vi-mcp embed auto` — nothing happens when an external
  `embed.url` is configured (production setups keep their service), when everything is up to date, or with `off`; it runs again when the
  pinned llama.cpp or a model changes. Windows: checkbox in the setup dialog (`EMBED=1|0`, remembered in `install-options.json`).
- **Where**: Linux `/var/lib/vi-mcp/embed`, systemd units `vi-embed` (8767) and `vi-rerank` (8768) (user `vi-mcp`, groups `render video`
  for the GPU); Windows `%ProgramData%\vi-mcp\embed`, scheduled tasks `vi-embed` and `vi-rerank`.
- **Check**: `vi-mcp embed status` (URLs, both services, backend/device/speed of the last setup); `vi-mcp embed auto --dry-run`.
- **Why a process of its own**: embedding a backlog takes minutes; in the vi-mcp process it would block answers. An external service can
  still be used — set `embed.url` by hand.

## Indexes and code (0.61.0)

```bash
vi-mcp index list                                   # every index: kind, objects, experiences, knowledge, code pieces, own model
vi-mcp index describe cue-print --text "CUE print stack" --tags team:it,cue --kind projekt
vi-mcp index backfill                               # count: existing experiences/knowledge by the project their conversation recorded
vi-mcp index backfill --apply                       # … and move them
vi-mcp index rename repo cue-stack --reason "…"     # rename, or merge into an existing index
vi-mcp index move erkenntnis:… ansible --reason "…" # one object
vi-mcp index train vi-mcp                           # the own model of one index now (otherwise sleep step 8d)
vi-mcp index import-code ~/Dev/code/vi-mcp --index vi-mcp --url https://<host>/vi-mcp/mcp --token-file ~/.config/vi-mcp/token-…
```

- **Mapping in `config.json`:** `"indexes": {"map": {"repo": "cue-stack"}, "ignore": ["scratch"]}`. A working directory named `repo` lands in
  `cue-stack`, and one named `scratch` lands in `global`. Home, hidden and temporary directories are always global.
- **Keeping code current:** the import is idempotent and sends only changed files. Example `.git/hooks/post-commit` (and `post-merge`) in the
  repository:
  ```sh
  #!/bin/sh
  vi-mcp index import-code "$(git rev-parse --show-toplevel)" --index vi-mcp --url "$VI_MCP_URL" --token-file "$VI_MCP_TOKEN_FILE" >/dev/null 2>&1 &
  ```
- **Index files (0.62.0)** — compare the same knowledge on two servers of one organisation:
  ```bash
  vi-mcp index export vi-mcp /tmp/vi-mcp.json                    # on server A: signed, internal, 0600; report names what was skipped and why
  vi-mcp index import /tmp/vi-mcp.json --as vi-mcp-kopie         # on server B: quarantine → reviewer → release, like the network
  vi-mcp index export vi-mcp-kopie /tmp/back.json                # later on B, with B's measurements
  vi-mcp index import /tmp/back.json --as vi-mcp                 # on A: no copies, only B's measurements as ratings
  vi-mcp index compare vi-mcp [--dry-run]                        # per content: allgemein, nur_ursprung, nur_ziel, schwach, …
  ```
  The file carries company knowledge unanonymised: hand it only to servers of the same organisation. Without a configured reviewer the
  imported contents stay in quarantine until `vi_release`.
- **Hold-back:** `"hold_back": 0.05` is the share of actions whose hints are held back at random to measure their total effect; `0` switches
  it off. The result is in `vi_stats` C and in the daily measurement P.

## Changing the port

The server listens on `port` from its configuration (default 8765, bound to 127.0.0.1).

- At first installation: Linux `sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb` (also `dnf`), Windows `msiexec /i … PORT=9000`.
- Later, on both: `vi-mcp port` shows it, `vi-mcp port 9000` sets it (1024–65535) and restarts the service. On Linux the local network
  service follows (`mcp_url` in the p2p configuration). Clients keep their URL and a reverse proxy (nginx `proxy_pass`) keeps its target —
  adjust them by hand (`vi-mcp setup --claude --hook --url http://127.0.0.1:9000/mcp …`).

## Windows

Since 0.27.0 there is `vi-mcp-<version>-x64.msi` (built on Linux with `deploy/windows/build.sh`, wixl in a Fedora container).

- **Install**: `msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [WIKI=0|HOST] [PROXY=http://proxy:3128] /l*v install.log` in an elevated shell.
- **Setup dialog** (0.34.0, double-click on the MSI): **Install** with an optional proxy field; **Update** when an earlier vi-mcp is
  installed (configuration, database, tokens and port are kept); **Repair / Remove** when this version is installed. Silent installs
  (`/qn`) show none of it. Server mode and proxy of the previous installation are remembered (`%ProgramData%\vi-mcp\install-options.json`,
  administrators and SYSTEM only) and reused when not given, so an update keeps a client-only installation client-only and reaches PyPI
  behind the same proxy. The previous version is removed inside the installation transaction: a failed update rolls back to it.
  The MSI copies `vi_mcp`, the hook and the scripts to `%ProgramFiles%\vi-mcp` and runs `install.ps1` as SYSTEM: it uses an installed
  64-bit Python ≥ 3.11 or unpacks Python 3.13.9 from the official NuGet package of the Python Software Foundation into
  `%ProgramFiles%\vi-mcp\python` (used only if the pinned SHA256 matches and the Authenticode signature of `python.exe` is valid; the
  python.org installer cannot run inside an MSI — exit 1618), creates `%ProgramFiles%\vi-mcp\venv` with NumPy, scikit-learn, cryptography and PyYAML from PyPI, and puts
  `vi-mcp` on the machine PATH. Log: `%ProgramData%\vi-mcp\install.log`. A failure rolls the installation back.
- **Server** (`SERVER=1`, default): configuration and database in `%ProgramData%\vi-mcp` (only SYSTEM and administrators), first instance
  `admin` (token in `%ProgramData%\vi-mcp\token-admin`), scheduled task `vi-mcp` at system start as SYSTEM, restarted after a failure,
  output in `%ProgramData%\vi-mcp\server.log`. The command line finds that configuration by default (since 0.28.1; `VI_MCP_CONFIG` still overrides it).
- **Client**: `vi-mcp setup --claude --hook --url URL --token-file FILE` (no interactive menu on Windows). The hook entry is
  `"<venv python>" -I "<install dir>\hook\vi_hook.py"`; URL and token files are in `%USERPROFILE%\.config\vi-mcp\hook.json`.
- **Networks** (0.54.0): a new server installation joins the public wiki network vi-wiki.org, as the Linux packages do (`WIKI=0` skips
  it; the proxy given with `PROXY=` is also the network service's). The wiki server (0.54.1): the field in the setup dialog or
  `WIKI=HOST` (a host name or `https://HOST[:PORT][/PATH]`, no path = `/vi-p2p/wiki`; runs `vi-mcp net wiki on --start HOST` and replaces
  the start address). Empty = as before: remembered with the proxy in `install-options.json`, a new installation takes vi-wiki.org.
  `WIKI=0` on an update switches a joined wiki network off (`net wiki off`, configuration and logbook kept). Not a host name or https
  address: setup fails and rolls back, the reason in `install.log`. A reinstall after an uninstall (data kept) sets the wiki service up
  again with the remembered server. Peers the service already knows stay known after a server change (an earlier vi-wiki.org too):
  `vi-mcp net --network wiki block https://vi-wiki.org/vi-p2p/wiki` drops one. Each network service is a scheduled task `vi-p2p-<network>` (SYSTEM,
  at system start, restarted after a failure) running `vi-p2p.cmd <network>`; config, key and logbook in `%ProgramData%\vi-mcp\p2p`
  (`<network>.json`, `<network>\netz.db`, `<network>\schluessel`), output in `%ProgramData%\vi-mcp\p2p-<network>.log`. `vi-mcp net …`
  works as on Linux in an elevated shell (`net wiki on|off|status`, `--network NAME setup …`); an update restarts the services that are
  not switched off. Configuration files with German keys are rewritten in English at install, as on Linux.
- **Not on Windows**: reflex code never runs (no Landlock/seccomp sandbox — it is refused with that reason), no interactive setup menu.
- **Upgrade**: install the newer MSI over it; the venv stays and is updated. **Uninstall**: Apps & Features or `msiexec /x …` removes the
  tasks (`vi-mcp`, `vi-p2p-*`), the venv and the PATH entry; `%ProgramData%\vi-mcp` (data, configuration, network keys) stays.
  Some older MSIs cannot be uninstalled (error 1603; of the builds checked 0.27.0, 0.30.0–0.33.0, 0.38.2, 0.46.0 — CHANGELOG 0.54.0):
  update to 0.54.0 first, then uninstall.

## Backup

PostgreSQL: `pg_dump -Fc vi-mcp > vi-$(date +%F).dump` while running. SQLite: the database is a WAL file. For a consistent copy while running:

```bash
sqlite3 ~/.local/share/vi-mcp/vi.db ".backup '/path/vi-$(date +%F).db'"
```

On shutdown (SIGTERM) the server writes the WAL back (`wal_checkpoint(TRUNCATE)`) and saves open
conversations as `unterbrochen` (interrupted).

## Uninstalling

```bash
systemctl --user disable --now vi-mcp
rm ~/.config/systemd/user/vi-mcp.service && systemctl --user daemon-reload
claude mcp remove -s user vi-mcp
# memory and configuration remain: ~/.local/share/vi-mcp, ~/.config/vi-mcp
```
