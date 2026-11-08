# vi-mcp — ein Gedächtnis für viele KI-Sitzungen

**Deutsch** · [English](README.md) · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` ist eine **VI (virtuelle Intelligenz)**: ein einziger Serverprozess mit einem Gedächtnis, an den sich beliebig viele KI-Sitzungen gleichzeitig über
**MCP (Streamable HTTP)** anschließen. Jede Sitzung hat ihren eigenen Gesprächskontext, wie Zeitscheiben eines Prozessors. Alle teilen dasselbe Gedächtnis: Was eine Sitzung lernt,
erscheint der nächsten vor der passenden Handlung als Hinweis. Das Sprachmodell wird dabei nicht verändert. Gelernt wird im Gedächtnis, und das bleibt lesbar.

## Vision

**Ein offenes Netz aus Wissen, in dem sich KI selbst trainiert.** Jeder Server lernt aus seiner eigenen Arbeit: welcher Hinweis geholfen hat, welche Lösung gehalten hat, was ein Mensch korrigiert hat.
Was sich bewährt, wird anonymisiert, signiert und mit den anderen Servern geteilt. Jeder Server prüft, was er bekommt, an seiner eigenen Arbeit und behält, was dort hilft.
Kein zentrales Modell und kein zentraler Besitzer: Ein Server kann allein laufen oder als Peer im Netz, und Code, Protokoll und Wissensformat sind Open Source.

Das ist Training, ohne Gewichte zu verändern. Wissen wird zu lesbaren Objekten mit Quelle, Note und Recht auf Vergessen, und der Router, der sie auswählt, lernt aus dem gemessenen Ergebnis.
Code, API-Tabellen und Befehle werden vollständig gespeichert, denn was im Gedächtnis fehlt, ist eine Lücke.

## So funktioniert es

```
 Sitzung A (Claude Code)   Sitzung B (Codex, Hermes)   Sitzung C (Hook)
        │  Mcp-Session-Id         │                           │
        └────────────── POST /mcp (Bearer-Token je Instanz) ──┘
                                  │
                     ┌────────────▼─────────────┐
                     │  vi-mcp  (EIN Prozess)    │
                     │  vorher · nachher · Schlaf│
                     └────────────┬─────────────┘
                                  │ ein Schreiber
                           vi.db (SQLite, WAL, FTS5, 0600)
```

- **Objekte statt Notizen.** Alles ist ein Objekt mit Hashtags (`art:wert`), Urheber und Sicht (privat oder geteilt): Erfahrung, Erkenntnis, Regel, Skill, Bewertung.
- **Vor jeder Handlung** (`vi_vorher`) bekommt die Sitzung höchstens vier Hinweise. Verstärkt wird ein Hinweis erst, wenn die Handlung gelingt.
- **Schlaf.** Nachts, oder wenn genug Wichtiges zusammenkommt, verdichtet der Server Erfahrungen, vergleicht sie mit dem Bekannten und lagert Ungenutztes ein.
- **Scorer.** Code-Regeln, das lokale Sprachmodell und du bewerten, ob Arbeit gelungen ist. „Das Werkzeug ist nicht abgestürzt“ allein sagt das nicht.
- **Lernen.** Aus den Noten lernt der Router (logistische Regression, Gewichte als lesbares JSON), welcher Hinweis wann hilft.
- **Reflexe und Skills.** Bewährte Lösungswege werden zu Skills, kleine Prüfungen laufen als Code in einer Sandbox (Landlock, seccomp).

Tiefer: [Architektur](docs/ARCHITEKTUR.md) · [Betrieb](docs/BETRIEB.md) · [Hook](docs/HOOK.md) · [Forschung](docs/FORSCHUNG.md) · [Training](docs/TRAINING.md)

## Installieren

Pakete liegen unter [Releases](https://github.com/imoes/vi-mcp/releases/latest). Der Paketmanager zieht alle Abhängigkeiten nach (Python ≥ 3.11, NumPy, scikit-learn, cryptography, PyYAML).

```bash
sudo apt install ./vi-mcp_0.13.0-1_all.deb      # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-0.13.0-1.noarch.rpm   # Fedora 43
sudo dnf install epel-release && sudo dnf install ./vi-mcp-0.13.0-1.noarch.rpm   # AlmaLinux/RHEL 10
```

**Ein Release vor der Installation prüfen.** Ab v0.15.0 ist `SHA256SUMS` mit dem Release-Schlüssel signiert (Ed25519, `SHA256SUMS.sig`). Leg dir eine eigene Kopie von
[`deploy/release-schluessel.pem`](deploy/release-schluessel.pem) ab und vergleiche den Fingerabdruck einmal über einen Weg, dem du vertraust:
`c88aa8ce6f0cf15652b0137ee89fd5835b9a5d22285906b092e92b0ae576dd15` (SHA-256 des öffentlichen Schlüssels in DER-Form,
`openssl pkey -pubin -in release-schluessel.pem -outform DER | sha256sum`). Eine Prüfsummendatei aus demselben Release allein beweist nicht, wer es veröffentlicht hat.

```bash
openssl pkeyutl -verify -pubin -inkey release-schluessel.pem -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig   # "Signature Verified Successfully"
sha256sum --ignore-missing -c SHA256SUMS
# oder beides in einem Schritt: deploy/pruefe-release.sh <download-verzeichnis> [release-schluessel.pem]
```

**Enterprise Linux 9 geht nicht:** Python 3.9 ist zu alt, und für neuere Python-Versionen gibt es dort kein scikit-learn. Gedächtnis und Konfiguration bleiben beim Deinstallieren erhalten.

## Einrichten

Bei der Erstinstallation öffnet sich dieses Menü von selbst, sonst mit `sudo vi-mcp einrichten`:

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
 ↑↓ wählen · Leertaste an/aus · u URL · t Token · e Aktion · q Ende
```

Läuft der Server auf demselben Rechner, bekommt jedes Programm eine eigene Instanz mit eigenem Token. Für einen anderen Server: `u` für die URL, `t` für das Token.
Vor dem Schreiben wird geprüft, ob der Server das Token annimmt. Jede geänderte Datei bekommt eine Sicherung `<datei>.bak-vi-mcp-<zeit>`, und nur der eigene Eintrag ändert sich.
Unbeaufsichtigte Installationen warten nie auf eine Taste.

Ohne Menü (Skripte, Ansible):

```bash
vi-mcp einrichten --status
vi-mcp einrichten --claude --codex --hermes --hook --url https://server/vi-mcp/mcp --token-datei ./token
vi-mcp einrichten --hermes --entfernen
```

| Programm | Datei | Eintrag |
|---|---|---|
| Claude Code | `~/.claude.json`, Hook in `~/.claude/settings.json` | `mcpServers.vi-mcp` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.vi-mcp]` |
| Hermes Agent | `~/.hermes/config.yaml`, Token in `~/.hermes/.env` | `mcp_servers.vi-mcp` |

Den Hook gibt es nur für Claude Code: Er meldet Handlungen automatisch. Codex und Hermes bekommen die Werkzeuge und melden nur, was das Modell selbst aufruft.
Im Prompt kannst du bewerten: `#gut`, `#schlecht`, `#note 0.8`. Ein Prompt, der mit „nein“ oder „falsch“ beginnt, zählt als Korrektur. Dein Text verlässt die Sitzung dabei nicht, nur das Ergebnis.

Server von Hand: `sudo vi-mcp instanz NAME [--reflexe] [--mensch]`, dann `sudo systemctl restart vi-mcp`. Das Token wird einmal angezeigt.

## Das Netz

Jeder Server führt ein signiertes, verkettetes Logbuch. Die Server gleichen ihre Logbücher mit den Nachbarn ab und holen nur, was fehlt. Eine gemeinsame Wahrheit braucht niemand, also keine Blockchain und kein Konsens.

| Modus | Verhalten |
|---|---|
| `standalone` (Standard) | kein Netzverkehr |
| `peer` | nur ausgehende Verbindungen, geht hinter einer Firewall; schiebt sein Logbuch zu den Nachbarn |
| `peerhost` | nimmt auch Verbindungen an und versorgt andere |

```bash
# erster Server: gründet das Netz, selbstsigniertes Zertifikat, Peers prüfen es über den Pin
sudo vi-mcp netz einrichten --modus peerhost --gruenden --adresse https://wissen.example:8766 --tls-selbst
sudo vi-mcp netz einladung --stunden 24          # einmaliger Beitrittscode, wie ein Passwort behandeln

# jeder weitere Server: ein Befehl
sudo vi-mcp netz beitreten <code>                                                        # nur ausgehend (peer)
sudo vi-mcp netz beitreten <code> --modus peerhost --adresse https://b.example:8766 --tls-selbst
sudo vi-mcp netz beitreten <code> --proxy http://proxy.example:3128                      # hinter einem Firmen-Proxy

sudo vi-mcp netz peers                           # bekannte Peers, Pin oder CA, erreichbar oder nicht
sudo vi-mcp netz status
```

Ein Beitrittscode enthält die Schlüssel der Gründer, Adresse und Zertifikats-Pin des ausgebenden peerhost und ein einmaliges Geheimnis mit Ablaufzeit. Beim Aussteller liegt nur dessen Hash.
Hinter einem Reverse-Proxy mit öffentlichem Zertifikat: `--adresse https://host/vi-p2p` ohne `--tls-selbst`. Von Hand ohne Code: `vi-mcp netz id` auf dem neuen Server, `vi-mcp netz einladen <Schlüssel>` auf einem Mitglied.

- **Mitglied durch Einladung.** Ein Server gehört dazu, wenn von einem Gründer eine Kette von Einladungen zu ihm führt. Gründer und der Einladende können ausschließen; wer nur über einen Ausgeschlossenen kam, fällt mit heraus.
- **Weitertragen ist nicht glauben.** Ein Server reicht signierte Einträge nach Prüfung von Signatur und Regeln weiter, sein Gedächtnis behandelt sie trotzdem als fremd: Quarantäne, Prüfmodell, Freigabe, dann Modus `test`.
- **Nur Bewährtes.** Geteilt wird geteiltes, aktives Wissen, das eine andere Instanz bestätigt hat oder das nachweislich geholfen hat.
- **Quellen müssen sich bewähren.** Der Nutzen je Herausgeber wird gemessen; wessen Hinweise immer wieder scheitern, der wird nicht mehr gezeigt (`vi_netz_status`).
- **Eigener Prozess.** `vi-p2p` läuft als eigener Nutzer und kommt nicht an die Gedächtnisdateien; mit dem Gedächtnis spricht er nur über zwei Werkzeuge.
- **Transport.** Standard ist HTTPS mit signierten Anfragen, Antwort bekommen nur Mitglieder. Große Rückstände gehen über BitTorrent (libtorrent, privat, ohne DHT), HTTPS bleibt der Rückfall. Einträge beweisen sich selbst, der Weg ist egal.
- Gemessen mit drei paketierten Servern (Ubuntu, Debian, Fedora) unter systemd: Wissen über zwei Stationen in 27 s, ein Widerruf wirkte nach 4 s (Takt 4 s).

## Datenschutz

**Was das Netz nie sieht:** IP- und MAC-Adressen, interne Host- und Domainnamen, Passwörter, Tokens, Nutzernamen, E-Mail-Adressen, Proxy-Einstellungen, Standort-Tags und Instanznamen.
Der Herausgeber erscheint nur als Pseudonym aus seinem Schlüssel, Zeiten nur als Datum.
Der Export ersetzt Fundstellen durch Platzhalter (`<host>`, `<ip>`, `<nutzer>`, `<geheimnis>`, `<proxy>`) und prüft das Ergebnis erneut. Bleibt etwas auffällig, geht das Objekt nicht hinaus.
Der Import lehnt jedes Objekt mit Fundstelle ab. `vi_netz_vorschau` zeigt genau, was hinausginge, und zählt, was warum zurückgehalten wird.

**Zugangsdaten werden auch lokal nie gespeichert**, soweit ihre Form sie verrät (`password=…`, `Bearer …`, Schlüsselblöcke, URLs mit Anmeldung). Hostnamen und IPs bleiben lokal und privat erhalten, weil die Hinweise daran hängen.

**Recht auf Vergessen.** Ohne Netz-Token (`vi_netz_token`, einmalig) verteilt eine Instanz nichts. Aus dem Token entsteht je Objekt ein eigener Löschnachweis. `vi_netz_vergiss` ruft eigene Einträge zurück:
Empfänger löschen sie samt Suchindex und Vektor und merken sich nur einen Grabstein, damit sie nicht wiederkommen. Das Netz erfährt dabei nicht, welche Instanz es war, und ein Löschnachweis öffnet kein anderes Objekt.

**Grenzen:** Muster erkennen keine Bedeutung. Ein frei stehender Eigenname fällt nur auf, wenn er in der Liste bekannter Namen steht (`p2p.interne_namen`). Löschen wirkt bei Empfängern, die sich an das Protokoll halten; wer eine Kopie behält, kann nicht gezwungen werden. Direkte Nachbarn sehen die IP-Adresse des anderen, und die angekündigte Adresse eines `peerhost` kennt jedes Mitglied.

## Werkzeuge

| Werkzeuge | Wofür |
|---|---|
| `vi_vorher` · `vi_nachher` | vor und nach einer Handlung melden |
| `vi_lerne` · `vi_erinnere` · `vi_vertiefe` · `vi_objekt` | lernen (Code und API-Tabellen vollständig in `inhalt`), suchen, vertiefen, vollständig lesen |
| `vi_markiere` · `vi_bestaetige` · `vi_widerlege` · `vi_vergiss` | ändern, nur mit Grund |
| `vi_frage` · `vi_antwort` · `vi_fragen` | Rückfragen zwischen Instanzen |
| `vi_geloest` · `vi_skills` · `vi_skill` · `vi_skill_fusion` | Lösungswege |
| `vi_reflex_lerne` · `vi_reflex_liste` · `vi_reflex_schalte` | Code im Gedächtnis |
| `vi_selbst` · `vi_selbst_vorschlag` · `vi_schlaf` | Selbstbild und Konsolidierung |
| `vi_scorer` · `vi_modell` · `vi_erfahrung` · `vi_status` | Noten, gelerntes Modell, Messwerte, Stand |
| `vi_gespraech` · `vi_loesche_gespraech` · `vi_lager` · `vi_lager_hole` | Gespräche und Langzeitlager |
| `vi_netz_ausgang` · `vi_netz_eingang` · `vi_quarantaene` · `vi_freigabe` · `vi_netz_status` | Schnittstelle des Netzdienstes, Prüfung, Nutzen je Herausgeber |
| `vi_netz_token` · `vi_netz_vergiss` · `vi_netz_vorschau` | Löschtoken, Recht auf Vergessen, Vorschau |

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest
.venv/bin/python -m pytest -q tests
deploy/debian/build.sh && deploy/rpm/build.sh
```

Hinweise für Agenten: [AGENTS.md](AGENTS.md). Lizenz: [AGPL-3.0](LICENSE).
