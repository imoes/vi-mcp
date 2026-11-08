# Betrieb

Zwei Wege: **Debian-Paket** (Server, Systemdienst mit eigenem Nutzer — Produktion) oder **Benutzerdienst** aus dem
Arbeitsbaum (Entwicklung).

## Debian-Paket (Server)

```bash
deploy/debian/build.sh                         # → dist/vi-mcp_<version>-1_all.deb (nur dpkg-deb nötig)
scp dist/vi-mcp_0.1.0-1_all.deb host:/tmp/ && ssh host sudo dpkg -i /tmp/vi-mcp_0.1.0-1_all.deb
ssh host 'sudo vi-mcp instanz <name> [--reflexe]' > ~/.config/vi-mcp/token-<name>-<host>   # Token EINMAL, 0600 ablegen
ssh host sudo systemctl restart vi-mcp
```

| Was | Wo |
|---|---|
| Code | `/usr/lib/python3/dist-packages/vi_mcp/`, Aufruf `/usr/bin/vi-mcp` |
| Dienst | `vi-mcp.service` (System), Nutzer/Gruppe `vi-mcp`, gehärtet (`ProtectSystem=strict`, `ProtectHome`, keine Capabilities; `systemd-analyze security`: 3.6 OK) |
| Konfiguration | `/etc/vi-mcp/config.json` — `root:vi-mcp 0640`, Verzeichnis `0750`; `vi-mcp instanz` behält diese Rechte |
| Gedächtnis | `/var/lib/vi-mcp/vi.db` — `vi-mcp:vi-mcp 0600`, Verzeichnis `0700` |
| Protokoll | `journalctl -u vi-mcp` |
| Hook-Skript für Clients | `/usr/share/vi-mcp/hook/vi_hook.py` |

`dpkg -r vi-mcp` lässt Gedächtnis und Konfiguration stehen; `dpkg -P vi-mcp` löscht beides und den Nutzer.
Ohne Instanz bleibt der Dienst nach der Installation aus und `postinst` sagt, was zu tun ist.

**Installiert auf `<host>`** (08.11.2026, als `<admin>`): Ubuntu 24.04.5, Python 3.12.3, SQLite 3.45.1
mit FTS5; Instanz `anna` (Reflex-Recht), lauscht auf `127.0.0.1:8765`. Abnahme siehe CHANGELOG.

## Benutzerdienst (Entwicklung)

```bash
cd ~/Dev/code/vi-mcp
deploy/install.sh            # Instanz $USER (mit Reflex-Recht), Dienst einrichten und starten
```

`install.sh` ist idempotent und tut genau dies:

1. Gibt es die Instanz noch nicht: `python3 -m vi_mcp instanz $USER --reflexe` → Konfiguration
   `~/.config/vi-mcp/config.json` (0600, nur SHA-256 des Tokens) und Token-Datei `~/.config/vi-mcp/token-$USER` (0600).
2. `deploy/vi-mcp.service` → `~/.config/systemd/user/vi-mcp.service`, `enable --now`, `restart`.
3. Prüft `GET /gesund`.

Der Dienst läuft auch ohne Anmeldung weiter, wenn Linger aktiv ist (`loginctl show-user $USER -p Linger`).

## Konfiguration

`$VI_MCP_CONFIG` oder `~/.config/vi-mcp/config.json`:

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

| Feld | Bedeutung | Standard |
|---|---|---|
| `bind`, `port` | wo der Server lauscht | `127.0.0.1`, `8765` |
| `db` | Gedächtnisdatei (lokales Dateisystem, **kein** NFS/SMB) | `~/.local/share/vi-mcp/vi.db` |
| `instanzen` | wer zugreifen darf; `reflexe: true` = darf Reflexe lernen/schalten | — (ohne Instanz startet der Server nicht) |
| `ttl` | Gültigkeit gemerkter Antworten je Werkzeug in s (max 3600) | 120 s |
| `origins` | erlaubte `Origin`-Header (Browser-Clients); Anfragen ohne Origin sind erlaubt | localhost |

Weitere Instanz (z. B. ein Agent auf demselben Host, ohne Reflex-Recht):

```bash
python3 -m vi_mcp instanz agent-x          # gibt das Token EINMAL aus
systemctl --user restart vi-mcp            # Konfiguration wird beim Start gelesen
```

## An Claude Code anschließen

```bash
claude mcp add --transport http -s user vi-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.config/vi-mcp/token-$USER)"
```

Neue Sitzungen sehen dann die Werkzeuge `mcp__vi-mcp__vi_*`. Jede Claude-Code-Sitzung ist ein eigenes Gespräch.

## Prüfen

| Frage | Befehl |
|---|---|
| Läuft er? | `systemctl --user status vi-mcp` · `curl -s http://127.0.0.1:8765/gesund` |
| Was sagt er? | `journalctl --user -u vi-mcp -f` (eine Zeile je Sitzungsbeginn/-ende, Fehler, Loop-Regeln) |
| Genau ein Prozess auf der Datei? | `fuser -v ~/.local/share/vi-mcp/vi.db` |
| Gedächtnisstand | Werkzeug `vi_status` (offene Gespräche, Objekte, Loop-Fehler) |
| Tests | `python3 -m pytest -q tests` |

## Sichern

Die Datenbank ist eine WAL-Datei. Für eine konsistente Kopie während des Betriebs:

```bash
sqlite3 ~/.local/share/vi-mcp/vi.db ".backup '/pfad/vi-$(date +%F).db'"
```

Beim Beenden (SIGTERM) schreibt der Server das WAL zurück (`wal_checkpoint(TRUNCATE)`) und sichert offene
Gespräche als `unterbrochen`.

## Deinstallieren

```bash
systemctl --user disable --now vi-mcp
rm ~/.config/systemd/user/vi-mcp.service && systemctl --user daemon-reload
claude mcp remove -s user vi-mcp
# Gedächtnis und Konfiguration bleiben: ~/.local/share/vi-mcp, ~/.config/vi-mcp
```
