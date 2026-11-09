# vi-mcp — Hinweise für Agenten und Mitwirkende

Ein Serverprozess mit einem Gedächtnis für viele KI-Sitzungen über MCP (Streamable HTTP). Erklärung: [README.de.md](README.de.md) ·
[README.md](README.md) (Englisch) · Aufbau: [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) · Betrieb: [docs/BETRIEB.md](docs/BETRIEB.md).

## Wie es funktioniert

Vor jeder Handlung fragt die Sitzung `vi_before` und bekommt höchstens vier Hinweise aus dem Gedächtnis; danach meldet sie `vi_after`.
Wann eine KI die VI befragt und wann sie lernt, steht in `werkzeuge.REGELN` und geht mit den `instructions` an jeden Client (seit 0.20.7).
Der Schlaf (bei genug Wichtigem; nachts nur nach 24 h ohne Schlaf) verdichtet Erfahrungen zu Erkenntnissen und Skills und bewertet die Arbeit (Scorer). Router, Bandit und Vektoren
lernen bei Bedarf (`bedarf`), etwa eine Minute nach neuen Erfahrungen oder neuem Wissen. Sichten: privat, geteilt, intern (nur mit Token, nie im Netz).
Alles ist ein Objekt in SQLite mit Hashtags (`art:wert`), Urheber-Instanz und Sicht privat/geteilt. Trainiert wird nie das Sprachmodell.

## Installieren und einrichten

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb        # Debian 12+, Ubuntu 24.04+
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm     # Fedora, AlmaLinux/RHEL 10 mit EPEL
sudo vi-mcp einrichten                               # ANSI-Menü: Claude Code, Codex CLI, Hermes Agent
```

Bei der Erstinstallation öffnet sich das Menü von selbst, wenn ein Terminal da ist. Ohne Menü:
`vi-mcp einrichten --claude --codex --hermes --hook --url URL --token-datei DATEI`.

## Arbeiten am Code

| Aufgabe | Befehl |
|---|---|
| Tests | `.venv/bin/python -m pytest -q tests -p no:cacheprovider` (`.venv`: scikit-learn, cryptography, pyyaml, numpy) |
| Debian-Paket | `deploy/debian/build.sh` |
| RPM-Paket | `deploy/rpm/build.sh` (baut in einem Fedora-Container, wenn `rpmbuild` fehlt) |
| Release | `deploy/release.sh --gh`: baut beide Pakete, signiert `SHA256SUMS` (Schlüssel außerhalb des Repos, `VI_MCP_RELEASE_SCHLUESSEL`), prüft und veröffentlicht |
| Release prüfen | `deploy/pruefe-release.sh <verzeichnis>` |

Module: `gedaechtnis` (Objekte, Suche), `intuition` (vorher/nachher), `sitzung`, `schlaf`, `scorer`, `lernen`, `bandit`, `vektor`, `reflexion`, `skills`, `reflexe`, `sandbox`,
`inhalt` (Bedeutung als Router-Merkmal), `bedarf` (Training bei Bedarf), `statistik` (Nutzungsstatistik, `vi_stats`), `lager`, `p2p` (Gedächtnis am Netz), `logbuch`, `netzdienst` (eigener Prozess `vi-p2p`), `netz_torrent`, `netz_cli`, `anonym`, `pruefung`, `pruefer`, `einrichten`, `server`, `werkzeuge`.

## Regeln

- **Wissen vollständig ablegen.** Code, API-Tabellen, Befehle und Konfigurationen gehören unverkürzt ins Feld `inhalt` (bis 200.000 Zeichen), nicht als Zusammenfassung mit Verweis auf eine Datei. Was fehlt, ist eine Lücke im Gedächtnis.

- **Öffentliches Repository.** Keine Hostnamen, IPs, Nutzernamen, Tokens oder internen URLs in Code, Doku, Commits oder Paketen. Hostspezifisches gehört nach `docs/LOKAL*.md` (gitignored, nie in ein Paket).
- **Nichts Internes ins Netz.** Was das Netz verlässt, läuft durch `anonym.py`; was hereinkommt, wird dort abgelehnt. Eine neue Exportart braucht einen Test in `tests/test_anonym.py`.
- **Kein `max_tokens` / `n_predict`.** Wird eine Ausgabe abgeschnitten: Thinking abschalten (`chat_template_kwargs: {enable_thinking: false}`).
- **Sprachmodell-Urteile verschärfen nur.** Es kann durch den geprüften Text getäuscht werden; endgültig ablehnen dürfen nur feste Regeln.
- **Keine Instanz bewertet sich selbst.** Es gibt kein MCP-Werkzeug zum Setzen einer Note.
- **Nichts verschwindet still:** Zurückgehaltenes wird mit Grund gezählt, Gelöschtes hinterlässt einen Grabstein. Berichte nennen die Klasse eines Fundes, nie seinen Wert.
- Jede Änderung, die ein Nutzer merkt, steht mit Nachweis in `CHANGELOG.md`.
