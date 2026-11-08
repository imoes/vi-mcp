# vi-mcp — ein Gedächtnis für viele KI-Sitzungen

`vi-mcp` ist eine **VI (virtuelle Intelligenz)**: ein einziger Serverprozess mit einem Gedächtnis, an den sich
beliebig viele KI-Sitzungen gleichzeitig über **MCP (Streamable HTTP)** anschließen. Jede Sitzung hat ihren eigenen
Gesprächskontext — wie Zeitscheiben eines Prozessors —, alle teilen dasselbe Gedächtnis: was eine Sitzung lernt,
erscheint der nächsten vor der passenden Handlung als Hinweis.

> „Eine VI ist eine KI, die loopt.“ Die **Intuition** (ohne Modell, automatisch) sieht alles und filtert vor;
> das **Bewusstsein** (Mensch oder LLM) liest nur, was die Intuition vorgefiltert hat.

**Was ist neu?** → [CHANGELOG.md](CHANGELOG.md) · **Wie ist es gebaut?** → [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) ·
**Wie betreibe ich es?** → [docs/BETRIEB.md](docs/BETRIEB.md) ·
**Handlungen automatisch melden** → [docs/HOOK.md](docs/HOOK.md) ·
**Wie Menschen sich erinnern — und was daraus folgt** → [docs/FORSCHUNG.md](docs/FORSCHUNG.md) ·
**Wie eine KI trainiert wird — und wie wir Daten dafür ablegen** → [docs/TRAINING.md](docs/TRAINING.md) ·
**Technische Erläuterung im Stil von Data** → [docs/erzaehlung.html](docs/erzaehlung.html)

## In einem Bild

```
 Sitzung A (Claude Code)   Sitzung B (anderer Agent)   Sitzung C (Hook-Skript)
        │  Mcp-Session-Id         │                           │
        └────────────── POST /mcp (Bearer-Token je Instanz) ──┘
                                  │
                     ┌────────────▼─────────────┐
                     │  vi-mcp  (EIN Prozess)    │   Gespräch je Sitzung: Seriennummer YYYYMMDDNNN,
                     │  Intuition · Bewusstsein  │   Verlauf zlib-komprimiert, durchsuchbar
                     │  ein Loop alle 60 s       │
                     └────────────┬─────────────┘
                                  │ ein Schreiber
                           vi.db (SQLite, WAL, FTS5, 0600)
```

## Schnellstart

```bash
cd ~/Dev/code/vi-mcp
python3 -m pytest -q tests          # 80 Tests (Synthetik-Test braucht scikit-learn: .venv), nur Standardbibliothek + pytest
deploy/install.sh                   # Instanz $USER anlegen, systemd-User-Dienst starten
curl -s http://127.0.0.1:8765/gesund
claude mcp add --transport http -s user vi-mcp http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.config/vi-mcp/token-$USER)"
```

Voraussetzungen: Python ≥ 3.11 (getestet mit 3.12.3), SQLite mit FTS5 (getestet 3.45.1), scikit-learn 1.4 (`python3-sklearn`) fürs Lernen im Schlaf.

## Werkzeuge

| Werkzeug | Wofür |
|---|---|
| `vi_vorher` | **Hook**: vor einer Handlung melden (optional `kontext_hashtags`) → gemerkte Antwort (wenn lesend und frisch, nur eigene Instanz), Hinweise aller Instanzen, Rückfragen, ggf. geänderte Argumente, `vorher_id` |
| `vi_nachher` | **Hook**: nach der Handlung melden → Erfahrung, gemerkte Antwort, Nachher-Reflexe |
| `vi_frage` · `vi_antwort` · `vi_fragen` | **Kollektiv**: Rückfragen zwischen Instanzen (Antwort nur mit Belegen) |
| `vi_status` | Stand: Objekte je Art, geteiltes Wissen je Instanz, offene Rückfragen, Erfahrung 24 h, offene Gespräche, Loop |
| `vi_lerne` | Erkenntnis mit Hashtags und **Quelle (Pflicht)** |
| `vi_erinnere` | Suche: `art:wert`, `!art:wert`, `(a OR b)`, `art:wert*`, Freitext; gewichtet, verstärkt |
| `vi_vertiefe` | Trichter: auffälligsten Hashtag ergänzen, erneut suchen (bis 3 Stufen) |
| `vi_suche_lerne` | eine Suche als Eselsbrücke lernen; läuft automatisch vor Handlungen mit passenden Reizen |
| `vi_objekt` | ein Objekt mit Kanten und Änderungsgeschichte |
| `vi_markiere` · `vi_bestaetige` · `vi_widerlege` | Objekt ändern — **nur mit Grund** |
| `vi_vergiss` | gemerkte Antworten eines Werkzeugs verwerfen |
| `vi_erfahrung` | **Hinweis-Lift** (Erfolg mit vs. ohne Hinweis) + Statistik je Werkzeug |
| `vi_loesche_gespraech` | privaten Inhalt eines eigenen Gesprächs löschen — Grabstein mit Grund bleibt |
| `vi_selbst` · `vi_selbst_vorschlag` | **Selbst**: Erzählung, Soll/Ist, Versionen; Soll ändern nur mit Belegen + fremder vertrauter Bestätigung |
| `vi_schlaf` | letzter Konsolidierungslauf; `jetzt=true` (vertraut) schläft sofort; `id` holt aus dem Archiv |
| `vi_geloest` · `vi_skills` · `vi_skill` · `vi_skill_fusion` | **Skills**: Lösungswege melden, ansehen, zusammenführen |
| `vi_modell` | das gelernte Router-Modell: Zustand, Beobachtungen, Holdout-AUC, stärkste Gewichte |
| `vi_gespraech` | Gespräche: Liste, Verlauf einer Seriennummer, Volltextsuche |
| `vi_reflex_lerne` · `vi_reflex_liste` · `vi_reflex_schalte` | Reflexe (Code im Gedächtnis); lernen/schalten nur mit Reflex-Recht |
| `vi_reflex_<name>` | je Werkzeug-Reflex ein eigenes Werkzeug |

## Projekt

| | |
|---|---|
| Code | `vi_mcp/` — `gedaechtnis` (Objekte, Erinnern), `sitzung` (Gespräche), `intuition` (vorher/nachher), `reflexe`, `schleife` (Loop), `werkzeuge` (MCP-Werkzeuge), `server` (HTTP), `konfig` |
| Tests | `tests/` — Kern ohne Netz und Protokoll gegen echten HTTP-Server |
| Hook | `hook/vi_hook.py` — Claude-Code-Hook, eine Datei, nur Standardbibliothek |
| Betrieb | Debian-Paket `deploy/debian/` (Server, läuft auf <host>: `https://<host>/vi-mcp/mcp`), Benutzerdienst `deploy/vi-mcp.service` + `deploy/install.sh` (Entwicklung) |
| Herkunft | Herausgelöst aus dem VI-Teil eines stdio-Skill-Servers (v3.0.0, 08.11.2026); siehe [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md#herkunft) |
