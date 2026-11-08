# Changelog

Was ein Nutzer von vi-mcp merkt — gruppiert nach Wirkung, jeder Eintrag mit Nachweis.
Verlinkt aus [README.md](README.md).

## 0.4.0 — 2026-11-08

### Was ist neu

- **Selbst** (`selbst:kern`): Soll (Werte/Ziele/Stil/Grenzen mit Herkunft) getrennt vom Ist (vom Schlaf berechnet),
  Erzählung ≤ 150 Wörter in jeder `initialize`-Antwort und alle 25 Handlungen. Änderung des Soll nur per Vorschlag
  mit ≥ 3 Belegen aus ≥ 2 Tagen und Bestätigung einer **anderen vertrauten** Instanz; Versionen vollständig in
  `selbst_version`. *Nachweis:* `test_selbst_kern_und_erzaehlung`, `test_selbst_vorschlag_braucht_belege_und_fremde_vertraute_instanz`,
  `test_selbst_in_initialize_und_wiederholung`.
- **Schlaf** (Konsolidierungslauf, nachts 03:00 UTC oder ab Wichtigkeitssumme 40): Triage, verschränkter Replay,
  Schema-Abgleich mit `konflikt:offen` statt stiller Änderung, Abstraktion zu Erkenntnissen (test) mit Belegkanten,
  Archiv, Selbst-Ist, Bericht. *Nachweis:* `test_schlaf_abstraktion_schema_konflikt_und_bericht`, `test_schlaf_selbst_ist`.
- **Vergessen als Funktion:** Aktualität nach Potenzgesetz statt exponentiell; Erfahrungen > 30 d ohne Zugriff und
  Belegkante → `archiviert` (Stummel bleibt, Inhalt komprimiert, abrufbar). *Nachweis:* `test_verfall_potenzgesetz`,
  `test_schlaf_archiviert_alte_unbenutzte_erfahrungen`.
- 50/50 Tests grün.

### Was wurde behoben

- Zeitstempel sekundengenau: Erfahrungen aus derselben Sekunde wie der letzte Schlaf galten als „alt“ und wurden
  nie konsolidiert. Jetzt Millisekunden (gefunden durch `test_schlaf_abstraktion_…`: Konflikt 0 statt 1).
- Schema-Abgleich verglich Neues **und** Altes gegen das Schema → „gemischt“, nie Konflikt. Jetzt nur das Neue.

### Was fehlt noch

- Schlaf-Abstraktion formuliert aus Vorlagen; die LLM-Variante (Reflexion, Park 4.2) ist nicht gebaut.
- „Vertraut“ = Reflex-Recht ist ein Stellvertreter für menschliche Freigabe.
- Startwerte unkalibriert: `VERFALL_D` 0,3, Schlaf-Schwelle 40, Archiv 30 d — Beobachtungspunkte stehen in der Doku.

## 0.3.0 — 2026-11-08

### Was ist neu

- **Messpunkt Hinweis-Lift** (`vi_erfahrung`, `vi_status`): Erfolg mit vs. ohne Hinweis, je Werkzeug und gesamt, mit
  Urteil („nützen“ / „kein Unterschied“ / „schaden — Annahme widerlegt“ / „zu wenig Daten“). Damit ist der Nutzen der
  VI erstmals messbar statt behauptet. *Nachweis:* `test_hinweis_lift_messpunkt` (10/12 vs. 4/12 → +50 Punkte).
- **Wichtigkeit aus Überraschung** statt fest kodiert: erster Fehler einer Art = 3, wiederholt = 2, chronisch = 1,
  Erfolg nach Fehlern = 2, erwartet = 0; Grund steht in der Geschichte. *Nachweis:* `test_ueberraschung_bestimmt_wichtigkeit`.
- **Löschen nach Gespräch** (`vi_loesche_gespraech`) mit Grabstein; **nach Instanz** per CLI `vi-mcp loesche-instanz`.
  *Nachweis:* `test_gespraech_loeschen_grabstein` (privat weg, Rohverlauf weg, Kanten weg, geteiltes Wissen bleibt,
  fremde Instanz abgelehnt, offen abgelehnt, doppelt abgelehnt).

### Was wurde behoben

- `loesche()` ließ **Kanten auf gelöschte Objekte** stehen. Jetzt werden sie mit entfernt.

### Was fehlt noch

- Selbst-Objekt, Konsolidierungslauf, Vergessen mit Archiv (0.4.0, in Arbeit).
- 43/43 Tests grün.

## 0.2.1 — 2026-11-08 — Logik-Audit (`/logik`)

### Was wurde behoben

- **[Gültige Ableitung] Selbstbestätigung beim Zeigen:** jeder automatisch gezeigte Hinweis zählte als Zugriff und
  wurde dadurch wichtiger und wieder gezeigt. Jetzt verstärkt erst `vi_nachher` mit `ok=true` (Annahme mit
  Beobachtungspunkt, docs/ARCHITEKTUR.md). *Nachweis:* `test_verstaerkung_erst_bei_erfolg`.
- **[Parsimonie] Bis zu ~16 Hinweise je Handlung:** jetzt höchstens 4 aus dem Gedächtnis, Rest gezählt mit Verweis
  auf `vi_vertiefe`. *Nachweis:* `test_hinweisbudget`.
- **[Ausgeschlossenes Drittes] Änderungsgeschichte wurde still auf 50 gekürzt:** jetzt gezählt
  (`aenderungen_gekuerzt`) und in `vi_objekt` genannt. *Nachweis:* `test_geschichte_kuerzung_benannt`.
- **[Identität] Feste Hashtags an zwei Stellen geprüft** (`instanz:` nur im Werkzeug, `art:`/`tool:` nur im Objekt):
  jetzt eine Stelle, `Objekt.markiere`. *Nachweis:* `test_instanz_hashtag_ist_urheber_nicht_frei`.
- **[Parsimonie] Zwei Wege zur Sicht** (Parameter `sicht` und Tabelle `SICHT_JE_ART`): Parameter entfernt.
- **[Widerspruchsfreiheit] „Die VI handelt nie selbst“ vs. Loop legt Regeln an:** präzisiert — nie in der Welt, im
  Gedächtnis mit Grund und Urheber `vi`.

### Was fehlt noch (offene Audit-Befunde, Entscheidung des Nutzers)

- **[Zureichender Grund] Wichtigkeit fest kodiert** (`intuition.py`: Fehler = 2, sonst 0). Vorschlag: aus
  Überraschung ableiten (erster Fehler dieser Art wichtig, chronischer nicht) — docs/FORSCHUNG.md A7.
- **[Falsifizierbarkeit] Kein Messpunkt, ob Hinweise nützen.** `vi_erfahrung` zeigt Aufrufe/Fehler, aber nicht
  „Erfolg mit vs. ohne Hinweis“. Ohne diese Zahl ist der Nutzen der VI eine Behauptung.
- **[Ausgeschlossenes Drittes] Löschen nach Gespräch/Person fehlt** (Datenschutz); heute nur `vi_vergiss` für Antworten.
- Vorauswahl `ORDER BY zuletzt DESC LIMIT 400` bevorzugt Jüngstes vor der Gewichtung (ältere, wichtige Treffer
  können herausfallen) — docs/FORSCHUNG.md C, Punkt 8.
- 40/40 Tests grün.

## 0.2.0 — 2026-11-08

### Was ist neu

- **Kollektiv: Instanzen lernen voneinander** (docs/ARCHITEKTUR.md, „Kollektiv“).
  - Urheber je Objekt aus dem Token (`instanz`), Sicht `privat`/`geteilt` je Art — ein Gedächtnis, eine Datenbank.
    *Nachweis:* `test_privat_und_geteilt`, `test_instanz_hashtag_ist_urheber_nicht_frei`, `test_fremder_gespraechsverlauf_bleibt_privat`.
  - Bestätigen zählt je Instanz; Gewichtbonus nur für fremde Instanzen. *Nachweis:* `test_bestaetigung_ueber_instanzen`.
  - Widerspruch einer fremden Instanz → `strittig`, erst Urheber oder zwei Instanzen → `widerlegt`.
    *Nachweis:* `test_widerspruch_strittig_dann_widerlegt`.
  - Rückfragen `vi_frage`/`vi_antwort`/`vi_fragen`, Zustellung beim nächsten `vi_vorher`. *Nachweis:* `test_rueckfrage_zwischen_instanzen`, `test_rueckfrage_laeuft_ab`.
  - Loop: Regel mit `kollektiv:ja`, wenn der Fehler bei ≥ 2 Instanzen auftrat. *Nachweis:* `test_kollektive_regel`.
- **`kontext_hashtags` in `vi_vorher`**: woran der Client arbeitet, als zusätzliche Reize. *Nachweis:* `test_kontext_hashtags_als_reize`.
- **Forschungsbericht** docs/FORSCHUNG.md: menschliches Gedächtnis → vi-mcp, mit Belegstufen je Aussage und Top-5-Vorschlägen.
- 37/37 Tests grün.

### Was hat sich geändert

- **Gemerkte Antworten und Erfahrungen sind privat je Instanz** (vorher sah jede Instanz die Antworten jeder anderen).
  Eine neue Sitzung derselben Instanz bekommt sie weiter. *Nachweis:* `test_zwei_sitzungen_zwei_gespraeche`.
- Cache-Hashtag heißt `cache:<hash>` statt `frage:<hash>` (`frage` ist jetzt eine Art — ein Begriff, ein Ding).
- Datenbank wird beim Start migriert (Spalten `instanz`, `sicht`; Cache-Hashtags). *Nachweis:* `test_migration_von_0_1`.
- **Korrektur der Doku:** Der Verfallsfaktor 0,995 ist im Paper belegt, gilt dort aber je Spielstunde (≈ 1 min
  Echtzeit); vi-mcp nutzt Echtzeit-Stunden (docs/ARCHITEKTUR.md, „Erinnern“). Vorher stand dort „ungeprüfte Annahme“.

### Was fehlt noch

- Aus docs/FORSCHUNG.md (Top 5): nur verstärken, wenn ein Hinweis genützt hat (heute verstärkt jedes Zeigen — eine
  Form von Selbstbestätigung), höchstens ~4 Hinweise je Handlung; Wichtigkeit aus Überraschung; ein „Selbst“-Objekt;
  ein nächtlicher Konsolidierungslauf; Vergessen nach Potenzgesetz mit Archiv statt Löschen.
- Volle Ergebnisse teilen (`teilen=true`) — bewusst nicht gebaut, bis es jemand braucht.
- Löschen nach Gespräch/Person (Datenschutz) fehlt; die Änderungsgeschichte eines Objekts wird auf 50 Einträge gekürzt.

## 0.1.1 — 2026-11-08

### Was ist neu

- **Zugang über TLS: `https://<host>/vi-mcp/mcp`** (nginx-Location `/vi-mcp/`, nur `nginx -s reload`).
  *Nachweis (vom Arbeitsplatz über das Netz, 08.11.2026 11:54 UTC):* `/vi-mcp/gesund` 200 `ok vi-mcp 0.1.1`,
  `initialize` 200, `vi_erinnere` findet die Erkenntnis aus 0.1.0 (Gedächtnis hat das Upgrade überstanden),
  `DELETE` 204, ohne Token 401; bestehende Routen `/health/qwen35b`, `/health/embed` weiter 200.
- **Mehrere Bind-Adressen in einem Prozess** (`"bind": ["127.0.0.1", "<docker-gateway>"]`), mit `IP_FREEBIND` (Start vor dem
  Docker-Netz möglich). *Nachweis:* `test_mehrere_adressen_ein_gedaechtnis`; auf <host> `ss -ltnp`: beide Adressen, eine PID.

### Was hat sich geändert

- Listen-Backlog 64 statt 5 (`ss -ltn` auf <host>: `LISTEN 0 64`).
- Fehlerprotokoll nennt die echte Client-Adresse aus `X-Forwarded-For` („… für <client>“).

### Was fehlt noch

- Siehe 0.1.0; erledigt ist „von außen nicht erreichbar“ und „Listen-Backlog“.

## 0.1.0 — 2026-11-08

### Was ist neu

- **Eigenständiger Server, ein Prozess, MCP über Streamable HTTP** (`POST`/`DELETE /mcp`, `GET /gesund`).
  Viele Clients gleichzeitig, ein Gedächtnis, ein Loop.
  *Nachweis:* `tests/test_http.py` — echter Server auf Zufallsport, zwei Instanzen, zwei gleichzeitige Sitzungen;
  27/27 Tests grün (Stand 0.1.1) (`python3 -m pytest -q tests`, Python 3.12.3, SQLite 3.45.1, 08.11.2026).
- **Gespräch je Sitzung** (Zeitscheibe): `Mcp-Session-Id` → eigene Seriennummer, eigener Verlauf; Zustände
  `offen`/`beendet`/`abgelaufen`/`unterbrochen`. *Nachweis:* `test_zwei_sitzungen_zwei_gespraeche`,
  `test_sitzung_gespraech_und_sichern`.
- **Instanzen mit eigenem Token** (nur SHA-256 gespeichert), Urheber-Hashtag `instanz:<name>`, Reflex-Recht je
  Instanz. *Nachweis:* `test_schutz` (401/403/400/404/405), `test_fremde_sitzung_und_reflex_recht`.
- **Hook-Werkzeuge `vi_vorher`/`vi_nachher`**: jeder Client kann Handlungen melden — die VI ist nicht mehr in
  einen bestimmten Werkzeug-Server eingebaut. *Nachweis:* `test_gemerkte_antwort_nur_lesend`, `test_erkenntnis_als_hinweis_vorher`.
- **Claude-Code-Hook** `hook/vi_hook.py` ([docs/HOOK.md](docs/HOOK.md)): meldet jede Handlung jeder Sitzung
  (PreToolUse/PostToolUse/PostToolUseFailure/SessionEnd); gemerkte Antwort → Aufruf verweigert mit der Antwort als
  Grund; eingebaute Werkzeuge nie aus dem Gedächtnis; Ausfall läuft durch und wird protokolliert.
  *Nachweis:* `tests/test_hook.py`, 7 Tests gegen echten Server; Schnittstelle nach https://code.claude.com/docs/en/hooks.md.
- **Debian-Paket** `vi-mcp_0.1.0-1_all.deb` (`deploy/debian/build.sh`): Systemdienst mit eigenem Nutzer `vi-mcp`,
  `/etc/vi-mcp`, `/var/lib/vi-mcp`, gehärtete Unit. **Installiert auf <host>** (08.11.2026 11:50 UTC).
  *Nachweis (am echten Host, Python-Client auf 127.0.0.1:8765):* `initialize` 200 (Protokoll 2025-06-18),
  `vi_lerne` + `vi_status` ok, FTS5 aktiv, `DELETE` 204 → danach 404, ohne Token 401; `vi.db*` `vi-mcp:vi-mcp 0600`;
  `/etc/vi-mcp/config.json` nach `vi-mcp instanz` weiter `root:vi-mcp 0640`; `systemd-analyze security` 3.6 OK.
- **systemd-User-Dienst** `deploy/vi-mcp.service` + `deploy/install.sh`. *Nachweis:* noch keiner — siehe „Was fehlt noch“.

### Was hat sich geändert (gegenüber dem VI-Teil des stdio-Skill-Servers 3.0.0)

- Gesprächsnummer wird **numerisch** verglichen: das 1000. Gespräch eines Tages bekommt `…1000` statt eines
  Fehlers. *Nachweis:* `test_seriennummer_ueber_999`; Parallelität: `test_seriennummern_eindeutig_parallel` (20 Threads).
- Zugriffszähler wird **atomar** hochgezählt (`zugriffe = zugriffe + 1`), kein verlorener Zähler.
  *Nachweis:* `test_zugriff_zaehlt_relativ`.
- Datenbank, Konfiguration, Verzeichnisse nur für den Eigentümer (0600/0700); `busy_timeout` 30 s statt 5 s.
  *Nachweis:* `test_datei_nur_fuer_eigentuemer`.
- Client darf `lesend` ausdrücklich angeben; sonst gilt das Namensmuster.
- Reflex-Prüfung strenger (`getattr`, `setattr`, Dunder-Attribute, `remove`/`unlink` verboten); Modul `_common`
  entfällt (gehörte zum Skill-Server). Defekte Reflexe werden entladen und als `modus:defekt` getaggt.
  *Nachweis:* `test_reflex_pruefung`, `test_reflex_defekt_nach_drei_fehlern`.
- Loop-Fehler werden gezählt und in `vi_status` genannt statt nur ins Protokoll geschrieben.

### Was wurde behoben

- `bestaetige`/`widerlege` erhöhten den Zähler **vor** der Prüfung des Grundes; ein abgelehnter Aufruf zählte
  trotzdem, der nächste doppelt. Jetzt: erst prüfen, dann ändern.
  *Nachweis:* `test_objekt_grund_pflicht_und_geschichte` (schlug mit dem übernommenen Code fehl: `2 == 1`).
- Zwei gleiche Handlungen in derselben Sekunde ergaben dieselbe Objekt-ID; die zweite überschrieb die erste still.
  Jetzt mit Zufallsanteil in der ID. *Nachweis:* `test_eingebaute_werkzeuge_nie_aus_gedaechtnis` (schlug vorher fehl: `1 == 2`).
- Ein gemeldetes `vorher` ohne `nachher` verschwand spurlos. Jetzt: Erfahrung `ok:unbekannt` beim Sitzungsende
  bzw. nach 1 h. *Nachweis:* `test_vorher_ohne_nachher_verschwindet_nicht`, `test_zwei_sitzungen_zwei_gespraeche`.

### Was fehlt noch

- **Von außen nicht erreichbar**: auf <host> lauscht vi-mcp nur auf 127.0.0.1. Clients auf anderen Hosts
  brauchen eine TLS-Route (nginx dort) oder einen SSH-Tunnel — noch nicht entschieden.
- Warteschlange des Servers ist die Python-Vorgabe (Listen-Backlog 5, `ss -ltn` auf <host>) — bei vielen
  gleichzeitigen Clients erhöhen.
- Benutzerdienst-Variante (`deploy/install.sh`) lokal nicht ausgeführt (Persistenz braucht Freigabe).
- **Nicht bei Claude Code registriert**; solange der alte stdio-Skill-Server seine eingebaute VI weiterbetreibt,
  gäbe es zwei Gedächtnisse mit gleichnamigen Werkzeugen — erst dort entfernen, dann hier anschließen.
- **Altes Gedächtnis nicht übernommen** (`~/skills/vi.db`, Stand 08.11.: nur 4 Gesprächsobjekte, sonst leer).
- **Hook nicht eingetragen** (braucht Freigabe, siehe docs/HOOK.md); Laufzeit je Werkzeugaufruf noch nicht gemessen.
  `additionalContext` bei PreToolUse ist in der Doku nicht bestätigt.
- **Ein Host**: mehrere Hosts brauchen einen TLS-Proxy davor bzw. bei mehreren Schreibern PostgreSQL.
- **Reflexe ohne Prozess-Isolat** (laufen im Serverprozess, nur AST-Prüfung + Zeitlimit).
- Geplant: Reflexion per LLM im Loop (Erfahrungen → Erkenntnisse), gelernte Suchen aus wiederkehrenden Filtern,
  Vergessen/Archiv, weitere Reize (Wörter aus Filtern, Tageszeit).
