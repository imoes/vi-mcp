# vi-mcp — ein Gedächtnis für viele KI-Sitzungen

**Deutsch** · [English](README.md) · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest) · [![Release](https://img.shields.io/github/v/release/imoes/vi-mcp?label=release)](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` ist eine **VI (virtuelle Intelligenz)**: ein einziger Serverprozess mit einem Gedächtnis, an den sich beliebig viele KI-Sitzungen gleichzeitig über
**MCP (Streamable HTTP)** anschließen. Jede Sitzung hat ihren eigenen Gesprächskontext, wie Zeitscheiben eines Prozessors. Alle teilen dasselbe Gedächtnis: Was eine Sitzung lernt,
erscheint der nächsten vor der passenden Handlung als Hinweis. Das Sprachmodell wird dabei nicht verändert. Gelernt wird im Gedächtnis, und das bleibt lesbar.

## Vision

**Ein offenes Netz aus Wissen, in dem sich KI selbst trainiert.** Jeder Server lernt aus seiner eigenen Arbeit: welcher Hinweis geholfen hat, welche Lösung gehalten hat, was ein Mensch korrigiert hat.
Was sich bewährt, wird anonymisiert, signiert und mit den anderen Servern geteilt. Jeder Server prüft, was er bekommt, an seiner eigenen Arbeit und behält, was dort hilft.
Kein zentrales Modell und kein zentraler Besitzer: Ein Server kann allein laufen oder als Peer im Netz, und Code, Protokoll und Wissensformat sind Open Source.

Das ist Training, ohne Gewichte zu verändern. Wissen wird zu lesbaren Objekten mit Quelle, Note und Recht auf Vergessen, und der Router, der sie auswählt, lernt aus dem gemessenen Ergebnis.
Code, API-Tabellen und Befehle werden vollständig gespeichert, denn was im Gedächtnis fehlt, ist eine Lücke.


## Werkzeugnamen

Seit 0.22.0 sind Werkzeuge, Parameter und feste Werte englisch. Die vorher genutzten deutschen Namen bleiben als Aliase gültig, bestehende Clients laufen weiter.

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

- **Objekte statt Notizen.** Alles ist ein Objekt mit Hashtags (`art:wert`), Urheber und Sicht (privat, geteilt oder intern: nur mit Token, nie im Netz): Erfahrung, Erkenntnis, Regel, Skill, Bewertung.
- **Vor jeder Handlung** (`vi_before`) bekommt die Sitzung höchstens vier Hinweise. Verstärkt wird ein Hinweis erst, wenn die Handlung gelingt.
- **Schlaf.** Sobald genug Wichtiges zusammenkommt (nachts nur, wenn seit 24 Stunden keiner lief), verdichtet der Server Erfahrungen, vergleicht sie mit dem Bekannten und lagert Ungenutztes ein.
- **Scorer.** Code-Regeln, das lokale Sprachmodell und du bewerten, ob Arbeit gelungen ist. „Das Werkzeug ist nicht abgestürzt“ allein sagt das nicht.
- **Lernen.** Aus den Noten lernt der Router (logistische Regression, Gewichte als lesbares JSON), welcher Hinweis wann hilft. Trainiert wird bei Bedarf, etwa eine Minute nach neuen Erfahrungen (ein Lauf dauert unter einer Sekunde), nicht erst nachts.
- **Reflexe und Skills.** Bewährte Lösungswege werden zu Skills, kleine Prüfungen laufen als Code in einer Sandbox (Landlock, seccomp).

Tiefer (englisch): [Architektur](docs/ARCHITECTURE.md) · [Betrieb](docs/OPERATIONS.md) · [Hook](docs/HOOK.md) · deutsch: [Forschung](docs/FORSCHUNG.md) · [Training](docs/TRAINING.md)

## Wie das Gedächtnis funktioniert — und warum es so gebaut ist

**Wie das menschliche Gedächtnis, nur hat jede Erinnerung eine Quelle.** vi-mcp hat die Gedächtnisarten, die auch Menschen haben:

| Menschliches Gedächtnis | vi-mcp | Woher es kommt |
|---|---|---|
| episodisch — „was passiert ist“ | `erfahrung`: jede gemeldete Handlung mit Werkzeug, Argumenten, Ergebnis, Dauer | der Hook, automatisch |
| semantisch — „was ich weiß“ | `erkenntnis`, `regel`: Kernaussage plus vollständiger Inhalt und Quelle | `vi_learn`, Importe, Schlaf |
| prozedural — „wie es geht“ | `skill`: Problem, Schritte, Anleitung, Versionen | `vi_solved`, Schlaf |
| Reize und Eselsbrücken | Hashtags `art:wert` (`tool:`, `host:`, `thema:` …) und gelernte Suchen | überall |

**Erinnern geht über Reize.** Vor jeder Handlung sagt die Sitzung der VI, was sie gleich tut (`vi_before`). Werkzeug, Host und Themen werden zu
*Reizen*, und die VI antwortet mit höchstens vier Hinweisen (das Arbeitsgedächtnis hält etwa vier Einheiten, Cowan 2001). Derselbe Hinweis
kommt im selben Gespräch höchstens einmal pro Stunde. Auch Doku (Confluence, Herstellerhandbücher) bekommt Reize: Eine Seite, die einen Host
nennt, erscheint vor einer Handlung auf diesem Host.

**Vergessen und Schlaf gehören dazu.** Ungenutztes Wissen verblasst nach einem Potenzgesetz und wandert später ins Langzeitlager (weiter
auffindbar, nie still weg). Ist genug passiert, *schläft* der Server: Er verdichtet Erfahrungen zu Erkenntnissen und Skills, vergleicht neue
Belege mit dem Bekannten, führt Wiederholungen zusammen und lagert aus, was niemand braucht. Überraschende Fehler zählen mehr als Routine —
wie beim Menschen.

**Warum das genial ist:**
- **Die KI lernt, ohne dass jemand ein Sprachmodell trainiert.** Wissen wird gelernt, sobald es entsteht (`vi_learn`), und steht vor der
  nächsten Handlung bereit — nicht erst nach dem nächsten Trainingslauf eines Modells.
- **Jede Erinnerung ist prüfbar.** Sie hat eine Quelle (Befehl, Host und Zeit oder URL), einen Urheber und eine Geschichte. Sie kann bestätigt,
  bestritten und widerlegt werden — von *anderen* Instanzen: Keine Instanz bestätigt sich selbst. Was falsch ist, wird markiert, nicht still
  behalten.
- **Es kann vergessen werden.** Ein Gespräch, eine Instanz oder ein Objekt gelöscht — und es ist weg (mit einem Grabstein, der das sagt).
  Wissen in Modellgewichten lässt sich so nicht entfernen.
- **Ein Gedächtnis für viele KIs.** Claude Code, Codex, Hermes und andere Clients teilen dasselbe Gedächtnis. Was eine Sitzung gelöst hat,
  hilft der nächsten — auch mit einem anderen Modell.
- **Nichts verschwindet still.** Zurückgehaltene Hinweise, gekürzte Verläufe, zusammengeführte Dubletten und widerlegtes Wissen werden gezählt
  und benannt.

## Woraus unsere Gewichte bestehen — und warum auch das genial ist

vi-mcp trainiert nie das Sprachmodell. Die einzigen Gewichte, die es lernt, entscheiden, **welche** Erinnerung gezeigt wird — nicht, **was**
wahr ist:

- **Der Router** ist eine logistische Regression (scikit-learn). Jede Handlung ist eine Beobachtung: die Reize der Lage × die gezeigten
  Hinweise, und das Label ist, ob die Handlung danach gelang. Die Gewichte sagen etwa: „Dieser Hinweis vor `tool:Bash` auf jenem Host erhöht
  die Erfolgschance.“ Sie liegen als lesbares JSON im Gedächtnisobjekt `modell:router` — jedes Gewicht gehört zu einem benannten Merkmal und
  ist mit `vi_model` einsehbar. `vi_why` zeigt für einen Hinweis, warum er gezeigt wurde: die gespeicherte Entscheidung und die Gewichte,
  die ihn getragen haben. Der Router lernt über die Labels (Urteile des Scorers, deine Rückmeldung zu einem Hinweis), nie dadurch, dass
  jemand Gewichte schreibt; nach jedem Training geht er nur live, wenn seine Reihenfolge auf zurückgehaltenen Daten mehr Erfolg bringt, und feste Regeln prüfen die Gewichte und benennen, was falsch aussieht (ein Merkmal dominiert,
  ein Gewicht gegen den gemessenen Nutzen, ein unbestätigter Hinweis aus dem Netz, die Uhrzeit als Ursache).
- **Der Bandit** zählt je Hinweis, wie oft eine Handlung danach gelang, verglichen mit der Grundrate (Thompson Sampling) — der Rückfall,
  solange der Router zu wenig Daten hat.
- **Bedeutung** kommt aus einem vortrainierten Embedding-Modell (bge-m3): Vektoren für die Bedeutungssuche und um ähnliches Wissen zu
  verknüpfen. vi-mcp nutzt es, trainiert es aber nicht.

**Warum das genial ist:**
- **Das Trainingssignal ist kostenlos und ehrlich.** Niemand beschriftet Daten: Das Label ist das Ergebnis echter Arbeit (gelang die Handlung,
  hat ein Mensch korrigiert, hat der Scorer sie angenommen).
- **Klein, schnell, erklärbar.** Das Modell sind Kilobytes JSON, es trainiert in unter einer Sekunde auf einer CPU, etwa eine Minute nach
  neuen Erfahrungen — und jede Entscheidung lässt sich über die Gewichte benannter Merkmale erklären.
- **Gewichte können keine Fakten erfinden.** Sie ordnen nur Erinnerungen, die es gibt und die eine Quelle haben. Ein falsches Gewicht zeigt
  einen weniger hilfreichen Hinweis — eine falsche Aussage kann es nicht erzeugen.
- **Es schaltet sich ab, wenn es nicht hilft.** Bei zu wenig Daten oder schwachem Ergebnis auf zurückgehaltenen Daten bleibt das Modell im
  Testmodus, und die Heuristik entscheidet; ein kleiner Teil der Hinweise ist Erkundung, damit das Modell auch über das lernt, was es selbst
  nicht gezeigt hätte.

## Installieren

Pakete liegen unter [Releases](https://github.com/imoes/vi-mcp/releases/latest). Der Paketmanager zieht alle Abhängigkeiten nach (Python ≥ 3.11, NumPy, scikit-learn, cryptography, PyYAML).

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb      # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm   # Fedora 43
sudo dnf install epel-release && sudo dnf install ./vi-mcp-<version>-1.noarch.rpm   # AlmaLinux/RHEL 10
sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb                       # anderer Port bei der Erstinstallation
```

**Windows** (seit 0.27.0, Client und Server): `vi-mcp-<version>-x64.msi` nimmt ein installiertes Python ≥ 3.11 oder ein privates Python
aus dem offiziellen NuGet-Paket der Python Software Foundation (SHA256 und Signatur geprüft), legt eine venv mit den PyPI-Paketen an, den
Befehl `vi-mcp` und — außer bei `SERVER=0` — den Server als geplante Aufgabe `vi-mcp` (Daten in `%ProgramData%\vi-mcp`). Während der
Installation braucht es Internetzugang:

```bat
msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [PROXY=http://proxy:3128] /l*v install.log
vi-mcp setup --claude --hook --url http://127.0.0.1:8765/mcp --token-file <datei>
```

Den Port ändert `vi-mcp port 9000` später unter Linux und Windows (startet den Dienst neu). Vektoren für die semantische Suche liefert der
eigene Embedding-Dienst, jederzeit nachinstallierbar: `sudo vi-mcp embed setup` (llama.cpp + bge-m3, Vulkan oder CPU; unter Windows
`EMBED=1`). Unter Windows gibt es kein interaktives Einrichtungsmenü, keine Reflex-Sandbox (Reflex-Code läuft nicht) und keinen
Netzdienst (P2P) — siehe [docs/OPERATIONS.md](docs/OPERATIONS.md#windows).

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

## Zwei Modi: Token und Open Wiki

| Modus | Wer | Was |
|---|---|---|
| **Token** (Standard) | jede Instanz hat ihr eigenes Token | volle Nutzung nach ihren Rechten |
| **Open Wiki** (`"offen": true` in `/etc/vi-mcp/config.json`) | jeder, der den Server erreicht, ohne Token | alles Geteilte lesen, Hinweise vor Handlungen, eigene Handlungen melden, Wissen **vorschlagen** |

Das Wissen ist offen, das Schreiben nicht. Im Open-Wiki-Modus landet ein Vorschlag aus `vi_learn` in der Quarantäne wie ein Import aus dem Netz: Regeln, Prüfmodell, dann Freigabe durch eine Instanz mit Recht.
Bestätigen, Widerlegen, Rückfragen an andere, Reflexe, Freigaben und das Netz brauchen ein Token. Sonst könnte jeder Rechner den KI-Sitzungen aller anderen Anweisungen unterschieben.
Clients ohne Token teilen sich eine Instanz (`offen`); sie bekommen keine gemerkten Werkzeug-Antworten, damit niemand das Ergebnis einer fremden Abfrage erhält. Ein falsches Token wird weiter abgelehnt (401) und nicht still zum Gast.

Einem offenen Server beitreten, ohne Token:

```bash
claude mcp add --transport http -s user vi-mcp https://<server>/vi-mcp/mcp
vi-mcp einrichten --claude --codex --hermes --hook --url https://<server>/vi-mcp/mcp     # erkennt den offenen Server selbst
```

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
- **Quellen müssen sich bewähren.** Der Nutzen je Herausgeber wird gemessen; wessen Hinweise immer wieder scheitern, der wird nicht mehr gezeigt (`vi_net_status`).
- **Eigener Prozess.** `vi-p2p` läuft als eigener Nutzer und kommt nicht an die Gedächtnisdateien; mit dem Gedächtnis spricht er nur über zwei Werkzeuge.
- **Transport.** Standard ist HTTPS mit signierten Anfragen, Antwort bekommen nur Mitglieder. Große Rückstände gehen über BitTorrent (libtorrent, privat, ohne DHT), HTTPS bleibt der Rückfall. Einträge beweisen sich selbst, der Weg ist egal.
- Gemessen mit drei paketierten Servern (Ubuntu, Debian, Fedora) unter systemd: Wissen über zwei Stationen in 27 s, ein Widerruf wirkte nach 4 s (Takt 4 s).

## Datenschutz

**Was das Netz nie sieht:** IP- und MAC-Adressen, interne Host- und Domainnamen, Passwörter, Tokens, Nutzernamen, E-Mail-Adressen, Proxy-Einstellungen, Standort-Tags und Instanznamen.
Der Herausgeber erscheint nur als Pseudonym aus seinem Schlüssel, Zeiten nur als Datum.
Der Export ersetzt Fundstellen durch Platzhalter (`<host>`, `<ip>`, `<nutzer>`, `<geheimnis>`, `<proxy>`) und prüft das Ergebnis erneut. Bleibt etwas auffällig, geht das Objekt nicht hinaus.
Der Import lehnt jedes Objekt mit Fundstelle ab. `vi_net_preview` zeigt genau, was hinausginge, und zählt, was warum zurückgehalten wird.

**Zugangsdaten werden auch lokal nie gespeichert**, soweit ihre Form sie verrät (`password=…`, `Bearer …`, Schlüsselblöcke, URLs mit Anmeldung). Hostnamen und IPs bleiben lokal und privat erhalten, weil die Hinweise daran hängen.

**Recht auf Vergessen.** Ohne Netz-Token (`vi_net_token`, einmalig) verteilt eine Instanz nichts. Aus dem Token entsteht je Objekt ein eigener Löschnachweis. `vi_net_forget` ruft eigene Einträge zurück:
Empfänger löschen sie samt Suchindex und Vektor und merken sich nur einen Grabstein, damit sie nicht wiederkommen. Das Netz erfährt dabei nicht, welche Instanz es war, und ein Löschnachweis öffnet kein anderes Objekt.

**Grenzen:** Muster erkennen keine Bedeutung. Ein frei stehender Eigenname fällt nur auf, wenn er in der Liste bekannter Namen steht (`p2p.interne_namen`). Löschen wirkt bei Empfängern, die sich an das Protokoll halten; wer eine Kopie behält, kann nicht gezwungen werden. Direkte Nachbarn sehen die IP-Adresse des anderen, und die angekündigte Adresse eines `peerhost` kennt jedes Mitglied.

## Werkzeuge

| Werkzeuge | Wofür |
|---|---|
| `vi_before` · `vi_after` | vor und nach einer Handlung melden |
| `vi_learn` · `vi_recall` · `vi_drilldown` · `vi_object` | lernen (Code und API-Tabellen vollständig in `inhalt`), suchen, vertiefen, vollständig lesen |
| `vi_tag` · `vi_confirm` · `vi_refute` · `vi_forget` | ändern, nur mit Grund |
| `vi_ask` · `vi_answer` · `vi_questions` | Rückfragen zwischen Instanzen |
| `vi_solved` · `vi_skills` · `vi_skill` · `vi_skill_merge` | Lösungswege |
| `vi_reflex_learn` · `vi_reflex_list` · `vi_reflex_switch` | Code im Gedächtnis |
| `vi_self` · `vi_self_propose` · `vi_sleep` | Selbstbild und Konsolidierung |
| `vi_scorer` · `vi_model` · `vi_why` · `vi_set_visibility` · `vi_experience` · `vi_status` | Noten, gelerntes Modell, warum ein Hinweis kam, geteilt/intern umstellen, Messwerte, Stand |
| `vi_conversation` · `vi_delete_conversation` · `vi_archive` · `vi_archive_restore` | Gespräche und Langzeitlager |
| `vi_net_outbox` · `vi_net_inbox` · `vi_quarantine` · `vi_release` · `vi_net_status` | Schnittstelle des Netzdienstes, Prüfung, Nutzen je Herausgeber |
| `vi_net_token` · `vi_net_forget` · `vi_net_preview` | Löschtoken, Recht auf Vergessen, Vorschau |

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest
.venv/bin/python -m pytest -q tests
deploy/debian/build.sh && deploy/rpm/build.sh
```

Hinweise für Agenten: [AGENTS.md](AGENTS.md). Lizenz: [AGPL-3.0](LICENSE).
