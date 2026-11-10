# Operations

Two ways: **Debian package** (server, system service with its own user — production) or **user service** from the
working tree (development).

## Debian package (server)

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
  (no restart). vi-mcp does the authentication itself; no API key from nginx.
- **Assumption with observation point:** the gateway stays `<docker-gateway>` as long as the Docker network `<docker-network>`
  is not recreated. If it changes, `https://<host>/vi-mcp/gesund` returns 502 — then
  `docker network inspect <docker-network>` and adjust `bind` in `/etc/vi-mcp/config.json` + `proxy_pass`.
- Check: `curl -s https://<host>/vi-mcp/gesund` → `ok vi-mcp <version>`.

### Connecting Claude Code (this server)

```bash
claude mcp add --transport http -s user vi-mcp https://<host>/vi-mcp/mcp \
  --header "Authorization: Bearer $(cat ~/.config/vi-mcp/token-anna-<host>)"
```

## User service (development)

```bash
cd ~/Dev/code/vi-mcp
deploy/install.sh            # instance $USER (with reflex permission), set up and start the service
```

`install.sh` is idempotent and does exactly this:

1. If the instance does not exist yet: `python3 -m vi_mcp instance $USER --reflexes` → configuration
   `~/.config/vi-mcp/config.json` (0600, only the SHA-256 of the token) and token file `~/.config/vi-mcp/token-$USER` (0600).
2. `deploy/vi-mcp.service` → `~/.config/systemd/user/vi-mcp.service`, `enable --now`, `restart`.
3. Checks `GET /gesund`.

The service keeps running without a login if lingering is enabled (`loginctl show-user $USER -p Linger`).

## Configuration

`$VI_MCP_CONFIG` or `~/.config/vi-mcp/config.json` (on Windows `%ProgramData%\vi-mcp\config.json`; the keys keep their German names, e.g. `instanzen`, `reflexe`):

```json
{
  "bind": "127.0.0.1",
  "port": 8765,
  "db": "~/.local/share/vi-mcp/vi.db",
  "instanzen": {"anna": {"token_sha256": "…", "reflexe": true}},
  "ttl": {"netbox_get_devices": 600},
  "origins": ["http://localhost", "http://127.0.0.1"]
}
```

| Field | Meaning | Default |
|---|---|---|
| `bind`, `port` | where the server listens | `127.0.0.1`, `8765` |
| `db` | memory file (local file system, **no** NFS/SMB) | `~/.local/share/vi-mcp/vi.db` |
| `instanzen` | who may access (instances); `reflexe: true` = may learn/switch reflexes | — (without an instance the server does not start) |
| `ttl` | validity of remembered answers per tool in s (max 3600) | 120 s |
| `origins` | allowed `Origin` headers (browser clients); requests without an Origin are allowed | localhost |

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
| Is it running? | `systemctl --user status vi-mcp` · `curl -s http://127.0.0.1:8765/gesund` |
| What does it say? | `journalctl --user -u vi-mcp -f` (one line per session start/end, errors, loop rules) |
| Exactly one process on the file? | `fuser -v ~/.local/share/vi-mcp/vi.db` |
| Memory status | tool `vi_status` (open conversations, objects, loop errors) |
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

- **What it installs**: llama.cpp `llama-server` (release b11938, Vulkan build; the CPU build if Vulkan does not start) and the model
  bge-m3 Q4_K_M from `gpustack/bge-m3-GGUF` — both checked by SHA256. The model file is byte-identical with the one the existing vectors
  were made with, and the server runs with the same parameters (mean pooling, context 8192), so stored vectors stay valid.
  `--model-file PATH` uses a local copy (accepted only with the same hash), `--cpu` skips Vulkan, `--port` chooses the port.
- **Where**: Linux `/var/lib/vi-mcp/embed`, systemd unit `vi-embed` (user `vi-mcp`, groups `render video` for the GPU);
  Windows `%ProgramData%\vi-mcp\embed`, scheduled task `vi-embed` (`msiexec … EMBED=1` sets it up during installation).
- **Why a process of its own**: embedding a backlog takes minutes; in the vi-mcp process it would block answers. An external service can
  still be used — set `embed.url` by hand.

## Changing the port

The server listens on `port` from its configuration (default 8765, bound to 127.0.0.1).

- At first installation: Linux `sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb` (also `dnf`), Windows `msiexec /i … PORT=9000`.
- Later, on both: `vi-mcp port` shows it, `vi-mcp port 9000` sets it (1024–65535) and restarts the service. On Linux the local network
  service follows (`mcp_url` in the p2p configuration). Clients keep their URL and a reverse proxy (nginx `proxy_pass`) keeps its target —
  adjust them by hand (`vi-mcp setup --claude --hook --url http://127.0.0.1:9000/mcp …`).

## Windows

Since 0.27.0 there is `vi-mcp-<version>-x64.msi` (built on Linux with `deploy/windows/build.sh`, wixl in a Fedora container).

- **Install**: `msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [PROXY=http://proxy:3128] /l*v install.log` in an elevated shell.
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
- **Not on Windows**: reflex code never runs (no Landlock/seccomp sandbox — it is refused with that reason), no network service
  (`vi-mcp net` says so), no interactive setup menu.
- **Upgrade**: install the newer MSI over it; the venv stays and is updated. **Uninstall**: Apps & Features or `msiexec /x …` removes the
  task, the venv and the PATH entry; `%ProgramData%\vi-mcp` (data, configuration) stays.

## Backup

The database is a WAL file. For a consistent copy while running:

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
