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

`$VI_MCP_CONFIG` or `~/.config/vi-mcp/config.json` (the keys keep their German names, e.g. `instanzen`, `reflexe`):

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
