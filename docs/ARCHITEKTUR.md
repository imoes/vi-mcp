# Architektur

## Zielbild

Eine **VI** ist eine KI, die loopt — mit zwei Schichten:

| Schicht | Was sie tut | Im Code |
|---|---|---|
| **Intuition** (Unterbewusstsein) | sieht jede gemeldete Handlung, urteilt ohne Modell, automatisch *vor* der Handlung: gemerkte Antworten, Reflexe, gelernte Suchen | `intuition.vorher`, `reflexe.vorher` |
| **Bewusstsein** | was ein Mensch oder LLM bewusst nachliest: Erkenntnisse, Regeln, Vertiefen | `gedaechtnis.erinnere`, `gedaechtnis.vertiefe`, Werkzeuge `vi_erinnere`/`vi_vertiefe` |

Drei Grundsätze des Auftraggebers:

1. *„Man gibt der KI eine Intuition, die automatisch analysiert; nur Vorgefiltertes analysiert das Bewusstsein.“*
2. *„Man merkt sich in erster Instanz die **Suche** (die Hashtag-Kombination, die Eselsbrücke), nicht das Faktum.“*
   → gelernte Suchen laufen vor passenden Handlungen automatisch; `vi_vertiefe` geht den Trichter weiter.
3. *„Vor einer Handlung greift man automatisch auf Gedächtnis, Bewusstsein und Unterbewusstsein zu — und das muss
   in der Datenbank liegen.“* → jede Erfahrung trägt in `daten.vorher` die Reize und alles, was vorher gefunden
   wurde, und ist mit diesen Objekten verknüpft.

Und das Bild für den Betrieb: **ein KI-Prozess, viele Gesprächskontexte — wie Zeitscheiben.** Daraus folgt
die wichtigste Entscheidung des Projekts:

## Ein Prozess

Es gibt **genau einen** Serverprozess. Alle Clients sprechen über HTTP mit ihm.

*Warum (gemessen am 08.11.2026):* Als stdio-Server startete jede KI-Sitzung ihren eigenen Prozess; auf einem Host
liefen 4 Prozesse gleichzeitig auf derselben Datenbankdatei (`/proc/<pid>/fd`, gleicher Inode), jeder mit eigenem
Loop. Folgen: N-fache Wartungsarbeit, Sperren nur innerhalb eines Prozesses (`threading.Lock`), verlorene
Updates durch Lesen-Ändern-Schreiben über Prozessgrenzen, Gesprächsnummern-Rennen. Acht unabhängige Gutachten
(Peer-Sitzungen, 08.11.) kamen zum selben Schluss: *das Problem sind die N Prozesse, nicht die Datenbank.*

Mit einem Prozess gilt: ein Schreiber, ein Loop, eine Verbindung, eine Sperre (`gedaechtnis.sperre`, RLock).

*Woran man merkt, dass die Annahme falsch ist:* wenn ein zweiter Prozess dieselbe `vi.db` öffnet. Beobachtungspunkt:
`fuser ~/.local/share/vi-mcp/vi.db` muss genau einen Prozess zeigen.

## Datenbank: SQLite, solange es ein Host ist

SQLite im WAL-Modus: viele Leser, ein Schreiber (https://www.sqlite.org/wal.html). Bei einem Prozess genügt das.
**Nicht** über NFS/SMB — WAL braucht gemeinsamen Speicher auf einem Host (ebd., „Disadvantages“).

Erst wenn mehrere Hosts schreiben sollen, ist ein Datenbankserver nötig; dann **PostgreSQL** (JSONB, tsvector,
Sequenzen, Zeilensperren). MongoDB wurde erwogen und verworfen: das Modell ist relational (Objekte, Tags, Kanten
mit Joins), die Volltextsuche wäre schwächer, und ein Dokument-Ersetzen verliert Updates genauso. Weil alle
Zugriffe durch einen Prozess gehen, ist ein späterer Wechsel eine Änderung in `gedaechtnis.py`, nicht im Protokoll.

## Datenmodell

**Alles ist ein Objekt** (`gedaechtnis.Objekt`, Tabelle `objekt`; Mapping ohne ORM): feste Felder `id`, `art`,
`zeit`; änderbar nur über Methoden — `markiere`, `bestaetige`, `widerlege`, `verknuepfe`, `zugriff` —, jede mit
Eintrag in `aenderungen` (wer, wann, **Grund — Pflicht**, vor der Änderung geprüft). Die Geschichte hält 50
Einträge; ältere werden **gezählt** gekürzt (`daten.aenderungen_gekuerzt`, in `vi_objekt` genannt).

| Art | Wozu | Entsteht durch |
|---|---|---|
| `erfahrung` | jede gemeldete Handlung: Werkzeug, Argumente, Dauer, `ok:ja`/`ok:nein`/`ok:unbekannt`; `daten.vorher` = Gedächtniszugriff davor; **Wichtigkeit aus Überraschung** (`ueberraschung:neu` 3 · `wiederholt`/`erholt` 2 · `chronisch` 1 · `keine` 0 — Vorhersagefehler als Lernsignal, docs/FORSCHUNG.md A7) | `vi_nachher`; `vi_vorher` mit gemerkter Antwort; vorher ohne nachher (Sitzungsende/1 h) |
| `antwort` | gemerktes Ergebnis eines **lesenden** Aufrufs (`frage:<hash>`), gilt 120 s (je Werkzeug konfigurierbar, max 1 h) | `vi_nachher` |
| `erkenntnis` | Gelerntes mit Quelle und Wichtigkeit 0–3 | `vi_lerne` |
| `regel` | verdichtet: gleicher Fehler ≥ 3× in 24 h, Modus `test` | Loop |
| `reflex` | Python-Code: `werkzeug`, `vorher`, `nachher` | `vi_reflex_lerne` |
| `suche` | Eselsbrücke: Name, Filter, **Reize**, Geschichte | `vi_suche_lerne` |
| `gespraech` | eine Sitzung, Seriennummer `YYYYMMDDNNN`, Zusammenfassung + Hashtags; Verlauf zlib in `gespraech_roh` | `initialize` |
| `frage` | Rückfrage einer Instanz an eine andere oder an alle; Zustände `offen`/`zugestellt`/`beantwortet`/`abgelaufen` | `vi_frage` |
| `selbst` | `selbst:kern` = das Selbst (Soll/Ist/Erzählung, versioniert); sonst Vorschläge fürs Soll (Modus `test`) | Start / `vi_selbst_vorschlag` |
| `schlaf` | Bericht eines Konsolidierungslaufs: Zähler je Schritt, Dauer, Fehler, neue/geänderte IDs | Loop (nachts oder ab Wichtigkeitssumme) |

**Hashtags** `art:wert` (Tabelle `tag`); `art:<art>` immer gesetzt. Verwaltungs-Hashtags (`art:`, `frage:`, `ok:`,
`serial:`, `tag:`) zählen nicht als Inhalt. **Kanten** (Tabelle `kante`, beidseitig, mit Grund): automatisch bei ≥ 2
gemeinsamen inhaltlichen Hashtags (Zettelkasten-Idee, A-Mem) und von jeder Erfahrung zu den vorher gefundenen Objekten.

**Modi** (erschöpfend): `aktiv`, `test`, `aus`, `defekt`, `strittig`, `widerlegt`, `archiviert`. Widerlegte Objekte
erscheinen in keiner Suche; strittige erscheinen mit Vermerk; archivierte nur, wenn der Filter `modus:archiviert`
enthält (Stummel: Text, Hashtags, Zeit; Inhalt komprimiert in Tabelle `archiv`, per `vi_schlaf(id)` abrufbar).

**Urheber und Sicht** (Spalten `instanz`, `sicht`): Jedes Objekt gehört der Instanz, deren Token die Anfrage trug
(Objekte des Loops: Instanz `vi`); das Hashtag `instanz:<name>` wird daraus gesetzt und ist nicht frei wählbar.
`sicht` folgt der Art: **privat** sind `erfahrung` und `antwort` (und der Rohverlauf eines Gesprächs) — Ergebnisse
können Zugangsdaten enthalten; **geteilt** ist alles andere. Eine Instanz liest Geteiltes und ihr Eigenes; private
Objekte anderer Instanzen gelten für sie als unbekannt. Der Server (Loop) sieht alles.

## Kollektiv: Instanzen lernen voneinander

Eine **Instanz** ist ein Agentensystem mit eigenem Token (z. B. `claude-code`, ein Leitstand, ein anderer Agent) —
benannt nach System, nicht nach Person. Alle Instanzen teilen ein Gedächtnis; was sie voneinander lernen, läuft über
fünf Wege:

1. **Vor der Handlung** liefert `vi_vorher` Erkenntnisse, Regeln und gelernte Suchen *aller* Instanzen, jeweils mit
   Urheber („von b, bestätigt von 2 weiteren Instanzen“). Mit `kontext_hashtags` meldet ein Client, woran er gerade
   arbeitet — mehr Reize, bessere Treffer.
2. **Bestätigen über Instanzen:** `bestaetigt_von` zählt je Instanz. Nur *fremde* Bestätigungen geben Gewicht
   (keine Selbstbestätigung, CLAUDE.md Regel 5).
3. **Widersprechen über Instanzen:** Eine fremde Instanz allein macht ein Objekt `strittig` (bleibt sichtbar, mit
   Vermerk) — sie kann nicht das Wissen einer anderen löschen. `widerlegt` wird es durch den Urheber selbst oder
   durch zwei verschiedene Instanzen; eine fremde Bestätigung hebt `strittig` wieder auf.
4. **Rückfragen:** `vi_frage(an, text)` → die Zielinstanz sieht die Frage bei ihrer nächsten Handlung (einmal je
   Instanz), antwortet mit `vi_antwort(id, text, belege)` (Belege Pflicht); der Fragesteller sieht die Antwort bei
   seiner nächsten Handlung oder über `vi_fragen`. Nach 7 Tagen ohne Antwort: `abgelaufen`.
5. **Der Loop verdichtet über Instanzen:** gleicher Fehler ≥ 3× in 24 h → Regel; trat er bei ≥ 2 Instanzen auf,
   trägt sie `kollektiv:ja` und nennt die Instanzen. Die Regel enthält nur Werkzeug und Fehlersignatur, nie Ergebnisse.

Gemerkte Antworten (`antwort`) gelten seit 0.2.0 **nur innerhalb einer Instanz**.

## Erinnern

Filtersprache: `art:wert` (UND), `(a OR b)`, `!art:wert`, Präfix `art:wert*`, Freiwörter → FTS5.
Gewicht = **Relevanz** (FTS-Rang normiert, sonst 1) + **Aktualität** `(1 + Stunden seit zuletzt)^−0,3` (Potenzgesetz,
Wixted & Ebbesen 1991 / ACT-R — docs/FORSCHUNG.md A9; bis 0.3.0 exponentiell, siehe Korrektur unten) + **Wichtigkeit**
`wichtigkeit/3·0,6 + log1p(2·bestätigt + zugriffe)/6 − 0,5·widerlegt` (gedeckelt bei 1) + **Kollektiv-Bonus**
0,2 je *fremder* bestätigender Instanz (höchstens 0,6). Nach Park et al. 2023, „Generative Agents“ (arXiv 2304.03442).
Jeder Treffer wird **verstärkt** (`zugriffe + 1` atomar, `zuletzt = jetzt`).

> **Korrektur 2 (0.4.0):** Der exponentielle Verfall ließ alles über zwei Wochen praktisch verschwinden (30 d: 0,03).
> Jetzt Potenzgesetz, `VERFALL_D = 0,3` ist ein Startwert: 1 h 0,81 · 1 d 0,38 · 7 d 0,21 · 30 d 0,14 · 1 a 0,07.
> *Beobachtungspunkt:* Rangfolge alt/neu auf denselben Anfragen vor/nach dem Wechsel; Hinweis-Lift.
>
> **Korrektur 1 (08.11.2026):** Hier stand, der Verfallsfaktor 0,995/h sei eine *ungeprüfte Annahme*. Geprüft
> (docs/FORSCHUNG.md, B1): Park et al. nennen 0,995 in Abschnitt 4.1 — aber **je Spielstunde**, und eine Spielstunde
> entspricht dort etwa einer Minute Echtzeit (Anhang A). vi-mcp wendet den Faktor **je Echtzeit-Stunde** an
> (Halbwertszeit ≈ 5,8 Tage). Der Faktor ist also belegt, die Zeiteinheit ist eine eigene Wahl. Außerdem normiert Park
> die drei Bestandteile per Min-Max auf [0,1]; vi-mcp nicht. Beides steht unter „Was fehlt noch“ im CHANGELOG.

**Vertiefen**: häufigster inhaltlicher Hashtag der Treffer, der nicht im Filter steht (≥ 2 Treffer), wird angehängt;
erneut suchen; höchstens 3 (max 5) Stufen.

## Handlung melden: vorher / nachher

Die VI **handelt nie selbst in der Welt** — kein Werkzeugaufruf, kein Schreiben außerhalb des Gedächtnisses. Im
Gedächtnis handelt sie (Loop: Regeln verdichten, Fragen ablaufen lassen), jede Änderung mit Grund und Urheber `vi`.
Ein Client meldet jede Handlung:

```
vi_vorher(tool, args, lesend?)  → {antwort, antwort_alter_s, antwort_ttl_s, args, hinweise, vorher_id, zugriff}
   1. Vorher-Reflexe (aktiv: dürfen args ändern; test: nur Hinweis)
   2. Reize: tool:, skill: (Präfix bis zum ersten _), host: (aus host/hostname/node/device), instanz:
   3. Erkenntnisse + Regeln zu den Reizen → Hinweise
   4. gelernte Suchen zu den Reizen → laufen, Treffer als Hinweis
      Höchstens **4 Hinweise** aus dem Gedächtnis (Arbeitsgedächtnis, Cowan 2001 — docs/FORSCHUNG.md A2); der Rest
      wird gezählt genannt und ist über `vi_vertiefe` abrufbar (Progressive Disclosure).
   5. lesend? → frische gemerkte Antwort → Client führt NICHT aus; Erfahrung wird sofort gespeichert
vi_nachher(tool, args, ok, dauer_ms, fehler?, ergebnis?, vorher_id) → {erfahrung, hinweise, vorher_gefunden, verstaerkt}
```

**Verstärkt wird erst beim Erfolg, nicht beim Zeigen.** Bis 0.2.0 zählte jeder angezeigte Hinweis als Zugriff —
Gezeigtes wurde allein durchs Zeigen wichtiger und deshalb wieder gezeigt (Selbstbestätigung, Matthäus-Effekt;
CLAUDE.md Regel 5). Seit 0.2.1 verstärkt `vi_nachher` mit `ok=true` die vorher gefundenen Objekte. Das ist eine
**Annahme** („der Hinweis hat genützt“, Testing-Effekt: nur erfolgreiches Abrufen stärkt, docs/FORSCHUNG.md A10).
*Beobachtungspunkt:* **Hinweis-Lift** (`messung.py`, in `vi_erfahrung` je Werkzeug und in `vi_status` gesamt):
Erfolgsquote der Handlungen mit Hinweis gegen ohne; unter 10 Fällen je Seite „zu wenig Daten“; Lift < −5 Punkte heißt
„Hinweise schaden — Annahme widerlegt“. Bewusstes Nachlesen (`vi_erinnere`, `vi_objekt`, `vi_vertiefe`) verstärkt weiterhin sofort.

**Lesend oder schreibend?** Gibt der Client `lesend` an, gilt seine Angabe; sonst das Namensmuster
`intuition.SCHREIBEND` (create, update, delete, send, …). Schreibende Werkzeuge werden **nie** aus dem Gedächtnis
beantwortet.

**Kein nachher?** Der Zugriff verschwindet nicht: beim Ende des Gesprächs oder nach 1 h wird er als Erfahrung
`ok:unbekannt` („kein Ergebnis gemeldet“) gespeichert.

## Gespräche — die Zeitscheiben

`initialize` → neue Sitzung (`Mcp-Session-Id`, zufällig) → Gesprächsobjekt mit Seriennummer
(höchste des Tages + 1, **numerisch** verglichen, `INSERT` als Sperre — eindeutig auch bei Gleichzeitigkeit,
auch über 999). Während einer Anfrage gehören neue Objekte zu diesem Gespräch (`contextvars`).

Zustände (erschöpfend): `offen` · `beendet` (DELETE) · `abgelaufen` (4 h ohne Anfrage) · `unterbrochen`
(Server beendet). Bei jedem Übergang aus `offen` wird gesichert; danach liefert die Sitzungs-Id 404.

## Löschen — nichts verschwindet still

`vi_loesche_gespraech(serial, grund)`: nur die Urheber-Instanz, nur beendete Gespräche. Entfernt Erfahrungen,
gemerkte Antworten, Rohverlauf und deren Kanten; das Gesprächsobjekt bleibt als **Grabstein** (`zustand:geloescht`,
Zeit, Urheber, Grund, Anzahl). Geteiltes Wissen aus dem Gespräch bleibt — es ist Wissen, kein Verlauf.
Instanzweit (Person): `vi-mcp loesche-instanz <name> "<grund>"` auf dem Host (Admin, nicht per Token).

## Selbst — die virtuelle Persönlichkeit als Objekt

`selbst:kern` (docs/FORSCHUNG.md A12, C1; Vorbild: Conways Self-Memory-System, Parks Steckbrief). **Intension und
Extension getrennt:** `soll` (Werte, Ziele, Stil, Grenzen — jeder Satz mit Herkunft und Datum) und `ist`
(Kompetenz je Skill, Schwächen, Beziehungen — vom Schlaf aus 30 Tagen Erfahrung berechnet, nie von Hand).
Die `erzaehlung` (≤ 150 Wörter, aus Vorlage, nie Quelle eigener Fakten) steht in `initialize.instructions` jeder
Sitzung und wird alle 25 Handlungen als Hinweis wiederholt (Persona-Drift nach wenigen Runden, Li et al. 2024).

**Änderung des Soll** nur über `vi_selbst_vorschlag` (≥ 3 Belege als Objekt-IDs aus ≥ 2 Tagen — Spacing statt
Burst) und Bestätigung durch eine **andere, vertraute** Instanz (`vi_bestaetige` auf den Vorschlag). „Vertraut“ ist
heute das Reflex-Recht — **Annahme:** hinter einer vertrauten Instanz steht ein Mensch, der freigibt. Jede Version
steht vollständig in `selbst_version` (nicht gekürzt). Version 1 stammt aus den Projektregeln (CLAUDE.md).

## Schlaf — Konsolidierung

Ein Lauf im Loop-Thread (`schlaf.py`), nachts um 03:00 UTC oder sobald die Wichtigkeitssumme neuer Erfahrungen
≥ 40 ist (Parks Reflexions-Trigger auf Skala 0–3). Sieben Schritte, jeder gezählt, alles im Bericht `schlaf:<zeit>`:
Triage (Überraschung + Wichtigkeit + Zukunftsrelevanz) → Replay nach (host, skill) mit älteren Erfahrungen
verschränkt (CLS: Neues gegen Altes lesen, nicht überschreiben) → Schema-Abgleich (**neue** Erfahrungen gegen
bestehende Erkenntnis: gleicher Ausgang = Belegkanten; anderer = `konflikt:offen`, keine stille Änderung) →
Abstraktion (Cluster ohne Schema, ≥ 3 Erfahrungen an ≥ 2 Tagen → Erkenntnis `test` aus Vorlage mit Belegkanten;
LLM-Variante nicht gebaut) → Archiv (Erfahrungen > 30 d, nie zugegriffen, ohne Belegkante) → Selbst-Ist → Bericht.
Erkenntnisse, Regeln, Suchen, Reflexe werden nie automatisch archiviert. Eine Bestätigung durch den Server zählt
nicht als fremde Instanz (kein Gewicht durch Automatik).

## Lernen — der Router lernt seine Gewichte

Bis 0.4.0 war die Reihenfolge der Hinweise eine gesetzte Formel (Aktualität + Wichtigkeit + Bonus). Seit 0.5.0
lernt eine **logistische Regression** (scikit-learn, im Schlaf) aus den eigenen Beobachtungen, welcher Hinweis in
welchem Kontext zum Erfolg führte — docs/TRAINING.md 4a/4b.

- **Beobachtung** = gemeldete Handlung mit Label `ok`; Merkmale = Reize (`tool:`, `skill:`, `host:`, `thema:`,
  `stunde:`) × gezeigte Hinweise (`hinweis:<id>`, `hinweisart:<art>`, `hinweis_n`). Liegt in `objekt`/`tag`/`daten`;
  die View `beobachtung` zeigt sie flach (keine Kopie — eine Quelle der Wahrheit).
- **Matrix**: beim Training aus der DB gebaut (`DictVectorizer`, dünn besetzt 0/1); sklearn hat kein DB-Format.
- **Modell** `modell:router`: Gewicht je Merkmal + Achsenabschnitt als **lesbares JSON** (kein Pickle); `vi_modell`
  zeigt die stärksten Gewichte. Vorhersage = Sigmoid-Summe in reiner Standardbibliothek.
- **Router-Score** = Lift = P(ok | Reize + Hinweis) − P(ok | Reize). Nur wenn das Modell `aktiv` ist; sonst Heuristik.
  Jede Beobachtung nennt `router` (`heuristik`|`modell`), `kandidaten`, `gezeigt`, `exploration`.
- **Mindestmengen** (Peduzzi 1996): Merkmale < 10 Vorkommen fallen weg; min(ok, nicht ok) < 50 oder Holdout-AUC
  ≤ 0,6 → Modus `test` (gespeichert, gezeigt, nicht benutzt). Holdout = die zeitlich letzten 20 %.
- **ε-Erkundung 10 %**: ein Platz des Budgets geht an einen zufälligen Kandidaten von weiter hinten, markiert
  „(Erkundung)“ — sonst lernt das Modell nur über das, was die Heuristik ohnehin zeigt (Off-Policy, Li et al. 2011).
- *Beobachtungspunkt:* Hinweis-Lift (`vi_erfahrung`) vor/nach `router: modell`. Steigt er nicht, ist das Modell nicht
  besser als die Heuristik → zurück auf `test`.

**Stufe 2 — Thompson Sampling (`bandit.py`)**, wirksam ab der ersten Handlung, ohne sklearn: jeder Hinweis führt
`daten.nuetzlich = {ja, nein}` (Handlungen nach dem Zeigen gelungen / gescheitert; atomar per `json_set`). Ist kein
Modell aktiv, aber mindestens ein Kandidat bewertet, zieht der Router je Kandidat eine Stichprobe aus Beta(1+ja, 1+nein)
und ordnet danach (`router: bandit`) — selten Gezeigtes bleibt im Spiel, oft Gescheitertes rückt nach hinten.
`vi_objekt` zeigt die Zähler („genützt 20 / nicht 1, Erwartung 91 %“). Rangordnung erschöpfend: `modell` > `bandit`
> `heuristik`. Quellen: Russo et al. 2017 (arXiv 1707.02038), Agrawal & Goyal 2012 (arXiv 1209.3352).

## Vektoren — Bedeutung statt Wortgleichheit (Stufe 3)

`vektor.py`: Embeddings (OpenAI-kompatibler Dienst, konfig `embed`) für geteilte Wissensobjekte, als float32-BLOB in
Tabelle `vektor` (TRAINING.md 4c). **Nur im Schlaf** (Schritt 7, Batch 16, höchstens 256 je Lauf) — der Dienst auf
dem Produktivhost braucht ≈ 1 s je Text (gemessen 08.11.2026), zu langsam für `vi_vorher`. Schritt 7b: Kosinus ≥ 0,85
→ Kante „semantisch ähnlich“; ≥ 0,95 zwischen **verschiedenen** Instanzen → `dublette:moeglich` (zusammenlegen
entscheidet eine Instanz, nicht der Server). `vi_erinnere(filter, semantisch=true)` bettet den Freitext ausdrücklich
jetzt ein und ordnet Kandidaten nach Nähe — die Dauer steht im Ergebnis. Ohne Konfiguration: Schritte benannt
übersprungen, Werkzeug lehnt mit Grund ab.

## Loop

Genau einer, alle 60 s: Antworten älter als 1 h löschen · wiederholte Fehler → Regel (test, idempotent) ·
offene Gespräche sichern · Leerlauf → `abgelaufen` · WAL-Checkpoint. Fehler werden gezählt und in `vi_status` genannt.

## Reflexe

Code im Gedächtnis, den die VI sich selbst schreibt. Prüfung per AST: Import-Whitelist
(`reflexe.REFLEX_MODULE`), kein `exec`/`eval`/`open`/`getattr`/…, keine Dunder-Attribute; Zeitlimit 10 s; nach 3
Fehlern `defekt` (benannt, entladen). **Grenze:** der Code läuft im Serverprozess — kein Prozess-Isolat. Deshalb
dürfen nur Instanzen mit `reflexe: true` Reflexe lernen oder schalten; ausführen (als Hook) tun sie für alle.

## Schutz

- Bind `127.0.0.1` (Standard). Andere Hosts nur über einen TLS-Proxy.
- **Bearer-Token je Instanz**; in der Konfiguration steht nur der SHA-256, Vergleich mit `hmac.compare_digest`.
  Die Instanz wird Urheber: Hashtag `instanz:<name>` an Gesprächen, Erfahrungen, Gelerntem; `wer = ki@<instanz>`.
- **Origin-Prüfung** (Schutz vor DNS-Rebinding, MCP-Spec): fremder Origin → 403.
- Eine Sitzung gehört ihrer Instanz: fremde Sitzungs-Id → 404.
- Datenbank, Konfiguration, Token-Datei: `0600`, Verzeichnisse `0700` — das Gedächtnis enthält Gesprächsverläufe
  und Werkzeugergebnisse, darin können Zugangsdaten stehen.

## Protokoll

MCP „Streamable HTTP“ (https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):
`POST /mcp` (einzeln oder Stapel; nur Notifications → 202), `GET /mcp` → 405 (kein Server-Push), `DELETE /mcp`
beendet die Sitzung. Antworten als `application/json`, kein SSE. Protokollversionen 2025-06-18, 2025-03-26,
2024-11-05 (die gewünschte wird zurückgegeben, sonst die neueste). Werkzeugfehler kommen als Ergebnis mit
`isError: true` und Grund („abgelehnt: …“), Protokollfehler als JSON-RPC-Fehler.

## Logik-Prüfung (nach CLAUDE.md)

| Regel | Umsetzung |
|---|---|
| Identität | ein Gedächtnis, ein Prozess, ein Loop; eine Seriennummer je Gespräch; Begriffe in Code = Doku = Werkzeugtexten |
| Widerspruchsfreiheit | Grund wird vor der Änderung geprüft (Ablehnung ändert nichts); Zähler atomar; schreibende Werkzeuge nie aus dem Gedächtnis |
| Ausgeschlossenes Drittes | `ok:ja/nein/unbekannt`; Gesprächszustände und Modi erschöpfend; vorher ohne nachher wird gespeichert, nicht verworfen |
| Zureichender Grund | jede Ablehnung nennt den Grund; jede Änderung trägt Grund und Urheber; Hinweise nennen Quelle; Loop-Fehler im Status |
| Intension/Extension | Regel/Suche/Reflex (Soll) getrennt von Erfahrung/Gespräch (Ist); Herkunft per `instanz:` und `aenderungen` |

## Herkunft

Der Kern stammt aus dem VI-Teil eines stdio-MCP-Skill-Servers (Version 3.0.0, 08.11.2026), dort in einen
Skill-Server eingebaut: die VI legte sich um jeden Werkzeugaufruf. Hier ist sie **eigenständig**: sie lädt keine
fremden Werkzeuge, sondern bekommt Handlungen über `vi_vorher`/`vi_nachher` gemeldet — von jedem Client, der das will.
Übernommene Ideen und Quellen: Generative Agents (Park et al. 2023), A-Mem (Zettelkasten-Verknüpfung),
Filtersprache `art:wert`. Geändert gegenüber dem Original: siehe [CHANGELOG.md](../CHANGELOG.md).
