# Claude-Code-Hook: jede Handlung an die VI melden

`hook/vi_hook.py` — eine Datei, nur Standardbibliothek. Meldeweg laut Entscheidung des Nutzers (08.11.2026):
**nur** dieser Hook meldet; kein Werkzeug-Server meldet zusätzlich (sonst doppelt).

## Was er tut

| Claude-Code-Ereignis | Hook ruft | Wirkung im Modell |
|---|---|---|
| `PreToolUse` | `vi_before` | gemerkte Antwort → Aufruf **verweigert** (`permissionDecision: deny`), die Antwort steht im Grund; sonst Hinweise als `additionalContext` |
| `PostToolUse` | `vi_after` (ok, Ergebnis, Dauer) | Nachher-Reflex-Hinweise als `additionalContext` |
| `PostToolUseFailure` | `vi_after` (ok=false, `error`, `is_interrupt`) | — |
| `SessionEnd` | `DELETE /mcp` | Gespräch `beendet` |

- **Eine Claude-Sitzung = ein Gespräch** in vi-mcp (Zustand in `~/.cache/vi-mcp/hook/sitzung/<session_id>.json`, 0600).
  Unbekannte Sitzung (Server neu gestartet) → der Hook meldet sich einmal neu an.
- **Werkzeugname**: `mcp__<server>__<werkzeug>` → `<werkzeug>` (so heißen die Reize `tool:`/`skill:` wie die Werkzeuge selbst).
- **Nie aus dem Gedächtnis**: eingebaute Werkzeuge (Bash, Read, Edit, Grep, …) melden `lesend: false` — Dateien und
  Systemzustand ändern sich. Nur MCP-Werkzeuge können eine gemerkte Antwort bekommen (und nur lesende, nach Namensmuster).
- **Werkzeuge des Gedächtnisses** (`vi_*` auf einem MCP-Server) werden nicht gemeldet.
- **Datensparsamkeit**: Passwörter, Tokens und Zugangsdaten in URLs werden vor dem Senden maskiert. Das Ergebnis geht nur bei
  MCP-Werkzeugen an den Server; eingebaute Werkzeuge und Werkzeuge für Zugangsdaten melden nur den Ausgang. Argumente
  eingebauter Werkzeuge werden auf 300 Zeichen gekürzt. Die Maskierung arbeitet mit Mustern und kann Geheimnisse übersehen.
- **Ausfall**: vi-mcp nicht erreichbar, Token fehlt, falsche Antwort → Exit 0 ohne Ausgabe, der Aufruf läuft ohne
  Gedächtnis; der Grund steht in `~/.cache/vi-mcp/hook/hook.log`. Ein Hook-Fehler hält nie eine Sitzung auf.

**Grenze (Doku):** Ein Hook kann einen Aufruf erlauben oder verweigern, aber nicht durch ein Ergebnis ersetzen.
Eine gemerkte Antwort erscheint dem Modell daher als „verweigert, Grund: …“.

## Korrektur und Note des Nutzers (`UserPromptSubmit`)

Der Hook erkennt lokal, ob eine Eingabe eine Korrektur ist (beginnt mit „nein“, „falsch“, „das stimmt nicht“ …) oder eine Note
enthält (`#gut`, `#schlecht`, `#note 0.8`). An den Server geht **nur dieses Ergebnis, nie der Text** (`POST /signal`).
Dafür braucht es eine eigene Instanz: `vi-mcp instanz nutzer --mensch`, ihr Token in `~/.config/vi-mcp/token-nutzer`
(oder `VI_MCP_SIGNAL_TOKEN_FILE`). Das Token der Sitzung genügt nicht (403), und es gibt kein MCP-Werkzeug zum Setzen einer Note.

**Grenze:** Das Token liegt beim Nutzer. Ein Modell mit Shell-Zugriff unter demselben Konto könnte die Datei lesen und `/signal`
selbst aufrufen. Das Fehlen des Werkzeugs verhindert ein versehentliches Selbstbewerten, keinen gezielten Missbrauch.

## Belege zur Schnittstelle

Claude Code Hooks, https://code.claude.com/docs/en/hooks.md (gelesen 08.11.2026, installiert: 2.1.319):
gemeinsame Felder `session_id`, `cwd`, `hook_event_name`; PreToolUse `tool_name`, `tool_input`, `tool_use_id`;
`permissionDecision: "deny"` → `permissionDecisionReason` wird Claude gezeigt; PostToolUse nur nach Erfolg,
`tool_response`, `additionalContext`; PostToolUseFailure `error`, `is_interrupt`, `duration_ms`; SessionEnd `reason`,
Standard-Budget 1,5 s (deshalb DELETE mit 1 s Timeout); Exit-Codes außer 0 und 2 sind nicht blockierend.
**Nicht bestätigt:** `additionalContext` bei **PreToolUse** (bestätigt nur für PostToolUse) — wird es ignoriert,
fehlen nur die Vorher-Hinweise, sonst nichts.

## Eintragen

Voraussetzung: vi-mcp läuft und ist erreichbar. Für einen entfernten Server die Umgebung setzen (z. B. im
`env`-Block von `~/.claude/settings.json`):
`VI_MCP_URL=https://<host>/vi-mcp/mcp`, `VI_MCP_TOKEN_FILE=~/.config/vi-mcp/token-anna-<host>`.
Ein HTTP-Proxy aus der Umgebung (`http_proxy`) gilt auch für den Hook — die Domain des Servers gehört in `no_proxy`.
In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse":         [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "PostToolUse":        [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "PostToolUseFailure": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py", "timeout": 5}]}],
    "SessionEnd":         [{"hooks": [{"type": "command", "command": "python3 -I ~/Dev/code/vi-mcp/hook/vi_hook.py"}]}]
  }
}
```

Kosten: je Werkzeugaufruf zwei HTTP-Anfragen an 127.0.0.1 (Timeout 3 s; gemessen werden sollte die Dauer nach
der Installation, siehe CHANGELOG „Was fehlt noch“).

## Prüfen

`python3 -m pytest -q tests/test_hook.py` — 7 Tests gegen einen echten vi-mcp-Server: Vorher/Nachher, gemerkte
Antwort sitzungsübergreifend, eingebaute Werkzeuge nie aus dem Gedächtnis, Fehler, Hinweise, eigene Werkzeuge,
Sitzungsende, Server-Neustart, Ausfall.
