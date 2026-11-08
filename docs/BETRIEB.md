# Betrieb

## Installieren

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
