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
| `skill` | Lösungsweg: Problem (Reize), Schritte, Anleitung, Versionen, Belege; Modi `test`/`aktiv`/`strittig`/`aufgegangen` | `vi_geloest`; Schlaf (Erfolg nach Fehlern) |
| `selbst` | `selbst:kern` = das Selbst (Soll/Ist/Erzählung, versioniert); sonst Vorschläge fürs Soll (Modus `test`) | Start / `vi_selbst_vorschlag` |
| `schlaf` | Bericht eines Konsolidierungslaufs: Zähler je Schritt, Dauer, Fehler, neue/geänderte IDs | Loop (nachts oder ab Wichtigkeitssumme) |

**Hashtags** `art:wert` (Tabelle `tag`); `art:<art>` immer gesetzt. Verwaltungs-Hashtags (`art:`, `frage:`, `ok:`,
`serial:`, `tag:`) zählen nicht als Inhalt. **Kanten** (Tabelle `kante`, beidseitig, mit Grund): automatisch bei ≥ 2
gemeinsamen inhaltlichen Hashtags (Zettelkasten-Idee, A-Mem) und von jeder Erfahrung zu den vorher gefundenen Objekten.

**Modi** (erschöpfend): `aktiv`, `test`, `aus`, `defekt`, `strittig`, `widerlegt`, `archiviert`. Widerlegte Objekte
erscheinen in keiner Suche; strittige erscheinen mit Vermerk; archivierte nur, wenn der Filter `modus:archiviert`
enthält (Stummel: gekürzter Text, Hashtags, Zeit; der Inhalt liegt im Langzeitlager).

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


**Reize aus Kommandozeilen (seit 0.18.0).** Bei Shell-Werkzeugen (`Bash` u. a.) zerlegt `intuition.befehls_reize` die Kommandozeile in Teilbefehle (an `; & | ( )`, Backticks,
`$(` und Anführungszeichen), überspringt Variablenzuweisungen und `sudo`/`env` samt Optionen und nimmt das erste Wort. Bekannte Befehle werden zu `thema:<befehl>` und
`skill:<bereich>` (`BEFEHL_SKILL`: Proxmox, Ansible, Docker, PostgreSQL), `ssh [user@]host` zu `host:<host>`. Damit erscheint Wissen zu `vzdump` vor `ssh pve1 'vzdump 101'`.
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

## Skills — Lösungswege, die sich entwickeln

`skills.py` (prozedurales Gedächtnis). Ein Skill entsteht, wenn etwas als gelöst gilt: eine Instanz meldet es mit
`vi_geloest`, oder der Schlaf erkennt, dass eine Handlung nach Fehlern desselben Werkzeugs im selben Gespräch gelang
(`ueberraschung:erholt`; die Werkzeugfolge vom ersten Fehler bis zum Erfolg ist der Lösungsweg). Er erscheint als
Hinweis vor passenden Handlungen und ist **Text**: ausführbar wird Wissen nur über Reflexe in der Sandbox.

**Weiterentwicklung:** Gleicher Name bzw. gleiches Problem ergibt eine neue Version mit Grund und Belegen; fehlende
Schritte kommen hinzu, alte Fassungen bleiben in `daten.versionen`. Nützt ein Skill wiederholt nicht (≥ 3 Fehlschläge,
Erfolgsquote < 30 %), setzt der Schlaf ihn auf `strittig`. **Zusammenführen:** `vi_skill_fusion(a, b, name, grund)` erzeugt
einen neuen Skill aus beiden (Reize und Belege vereinigt, Schritte hintereinander); a und b werden `aufgegangen` mit
Verweis, erscheinen nicht mehr in Suchen, bleiben aber abrufbar. Der Schlaf schlägt Fusionen nur vor (`fusion:vorschlag`
bei gleichem Werkzeug + Fehlersignatur); entscheiden muss eine Instanz.

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
Abstraktion (Cluster ohne Schema, ≥ 3 Erfahrungen an ≥ 2 Tagen → Erkenntnis `test` aus Vorlage mit Belegkanten) →
Housekeeping (siehe „Langzeitlager“) → Selbst-Ist → Bericht. Eine Bestätigung durch den Server zählt
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
- **Nachschlagewerk höchstens einmal (seit 0.19.3)**: importierte Herstellerdoku (`art_wissen:doku-extern`) belegt vor einer Handlung höchstens
  einen Platz; weitere Absätze kommen nur über die Erkundung. In `vi_erinnere` bleibt alles auffindbar. Grund: Handbuch-Absätze passen über
  `skill:` zu fast jedem Befehl und drängten Erfahrungswissen (Warnungen, Fallstricke) aus dem Budget.
- *Beobachtungspunkt:* Hinweis-Lift (`vi_erfahrung`) vor/nach `router: modell`. Steigt er nicht, ist das Modell nicht
  besser als die Heuristik → zurück auf `test`.

**Stufe 2 — Thompson Sampling (`bandit.py`)**, wirksam ab der ersten Handlung, ohne sklearn: jeder Hinweis führt
`daten.nuetzlich = {ja, nein}` (Handlungen nach dem Zeigen gelungen / gescheitert; atomar per `json_set`). Ist kein
Modell aktiv, aber mindestens ein Kandidat bewertet, zieht der Router je Kandidat eine Stichprobe aus Beta(1+ja, 1+nein)
und ordnet danach (`router: bandit`) — selten Gezeigtes bleibt im Spiel, oft Gescheitertes rückt nach hinten.
`vi_objekt` zeigt die Zähler („genützt 20 / nicht 1, Erwartung 91 %“). Rangordnung erschöpfend: `modell` > `bandit`
> `heuristik`. Quellen: Russo et al. 2017 (arXiv 1707.02038), Agrawal & Goyal 2012 (arXiv 1209.3352).

## Scorer — ob Arbeit gelungen ist

„Das Werkzeug ist nicht abgestürzt“ war in 63 von 64 Fällen wahr und damit als Lernsignal fast wertlos. `scorer.py` bewertet in drei Stufen:

| Stufe | Wann | Ergebnis | Zählt fürs Lernen |
|---|---|---|---|
| Code | jeder Schlaf | `erfahrung.daten.score` = Note 0–1, Merkmale (`fehler`, `fehler_wiederholt`, `identisch_wiederholt`, `test_rot_danach`, `test_gruen_danach`, `korrektur`, `erholt`), Version | immer |
| Modell | jeder Schlaf, beendete Gespräche ab 5 Zügen | Objekt `bewertung`: Note nach festem Raster, Begründung, Zugnummern als Belege, Sicherheit | erst geeicht: mindestens 20 Gespräche mit menschlicher Note, davon 70 % innerhalb von 0,25 |
| Mensch | sofort über den Hook | Objekt `bewertung` | immer |

Router, Thompson-Zähler und Hinweis-Lift nutzen die Note statt `ok`, wo sie vorliegt. Die Thompson-Zähler messen seit 0.19.0 den Vorteil gegenüber der Grundrate des Werkzeugs (`bandit.py`). Stellt der Scorer fest, dass eine als gelungen gezählte
Handlung misslungen ist, bucht er das Ja des gezeigten Hinweises in ein Nein um. Eine Gesprächsnote unter 0,4 macht alle Handlungen des Gesprächs
für das Lernen zu Misserfolgen. Bewertungen sind privat. Das Protokoll für das Modell enthält nur Werkzeug, Ausgang, gekürzte Argumente und Fehler.
`tests/evals/router.json` ist ein fester Satz Prüffälle für die Hinweisauswahl, der bei jeder Version läuft.

## Vektoren — Bedeutung statt Wortgleichheit (Stufe 3)

`vektor.py`: Embeddings (OpenAI-kompatibler Dienst, konfig `embed`) für geteilte Wissensobjekte, als float32-BLOB in
Tabelle `vektor` (TRAINING.md 4c). **Nur im Schlaf** (Schritt 7, Batch 16, höchstens 256 je Lauf) — der Dienst auf
dem Produktivhost braucht ≈ 1 s je Text (gemessen 08.11.2026), zu langsam für `vi_vorher`. Schritt 7b: Kosinus ≥ 0,85
→ Kante „semantisch ähnlich“; ≥ 0,95 zwischen **verschiedenen** Instanzen → `dublette:moeglich` (zusammenlegen
entscheidet eine Instanz, nicht der Server). `vi_erinnere(filter, semantisch=true)` bettet den Freitext ausdrücklich
jetzt ein und ordnet Kandidaten nach Nähe — die Dauer steht im Ergebnis. Ohne Konfiguration: Schritte benannt
übersprungen, Werkzeug lehnt mit Grund ab.


**Inhalt als Merkmal des Routers (seit 0.16.0, `inhalt.py`).** Live wird nichts eingebettet. Der Schlaf (Schritt `7c_inhalt`) rechnet je Reiz-Hashtag mit mindestens 3 Wissensobjekten
den Mittelpunkt ihrer Vektoren und gruppiert alle Wissensobjekte mit K-Means (k = √(n/2), höchstens 40; Name einer Gruppe = ihre häufigsten Hashtags). `vi_vorher` gibt dem Modell je Kandidat
`naehe` = Kosinus zwischen Hinweis und dem Mittel der Mittelpunkte der aktuellen Reize (der Hinweis selbst herausgerechnet) und `inhalt:<gruppe>`. So gewichtet das Modell auch nach Inhalt,
und ein neuer Hinweis erbt das Gewicht seiner Gruppe. `lernen.INHALT = False` schaltet es zum Vergleich ab.
## P2P-Import — fremdes Wissen kommt nur geprüft herein

`p2p.py`, `pruefung.py`, `pruefer.py`. Fremdes Wissen kommt als signierter Logbuch-Eintrag über den Netzdienst (siehe „Netz — Logbücher statt Bundles“), nur Quelltext und Text als JSON. Ein Torrent-Hash
beweist, dass eine Datei unverändert ist, nicht, von wem sie stammt; das leistet die Ed25519-Signatur.

| Schicht | Wirkung |
|---|---|
| Logbuch | Kette, Signatur, Mitgliedschaft durch Einladung, Tageskontingent, Gabelung. Im Gedächtnis wird die Signatur erneut geprüft. |
| Feste Regeln | Nur sie lehnen endgültig ab: falsche Art, Form, Binärinhalt, unsichtbare Zeichen. Anweisungsmuster werden als Befund vermerkt. |
| Sprachmodell | Liest jedes Objekt, darf nur verschärfen. Vor jedem Lauf prüft ein Selbsttest mit einem bekannten Angriff, ob es standhält. Das Modell kann getäuscht werden und ist deshalb nie die letzte Instanz. |
| Quarantäne | Modus `quarantaene`: in keiner Suche, keinem Hinweis, keine Kanten, nicht zusammenführbar. |
| Freigabe | Unauffälliges durch eine Instanz mit Reflex-Recht. Reflexe, Schreibzugriffe, Regelbefunde und alles ohne positives Prüfurteil nur mit Freigabe-Recht (`vi-mcp freigeben` auf dem Server, Token nur für root lesbar). Danach Modus `test`. |
| Wirkung | Importiertes ist Text-Hinweis mit sichtbarer Herkunft, `herkunft:p2p` lässt sich nicht entfernen. Eigener Namensraum, keine Überschreibung lokaler Objekte, kein Gewicht aus fremden Zählern. Importierter Code läuft nur in der Sandbox, darf nur `vorher` sein und nie Argumente ändern. Importiertes wird nicht weiterexportiert. |

Grenzen: Muster und Modell erkennen nicht jeden Angriff. Wer root auf dem Server hat, kann freigeben. Die Prüfer-Anweisung liegt bewusst nicht im öffentlichen Repo (`pruefer_prompt`).

## Netz: anonym und löschbar

`anonym.py` ist die einzige Musterliste für IPs, MAC-Adressen, interne Domains, Nummern-Hostnamen, Zugangsdaten, Nutzernamen und Proxy-Angaben. Domains gelten als intern, solange sie nicht auf der Liste
öffentlicher Domains stehen (`OEFFENTLICH`, erweiterbar mit `p2p.oeffentliche_domains`). Der Export kennt zusätzlich alle Host-Tags, Instanzen, Systemkonten und `p2p.interne_namen`.

| Richtung | Verhalten |
|---|---|
| Export | Text und Quelle: ersetzen, erneut prüfen. Hashtags mit Orts- oder Personenbezug fallen weg. MCP-Servernamen werden aus Werkzeugen entfernt. Spricht ein Text von Zugangsdaten, bleibt er zu Hause. Das Ergebnis muss die eigenen Importregeln bestehen. |
| Import | Jede Fundstelle in Text, Quelle, Hashtags, Reizen, Schritten, Filter oder Code lehnt das Objekt ab. Der Bericht nennt nur die Klasse. |
| Lokal | Zugangsdaten mit eindeutiger Form werden in `neues_objekt` entfernt (ohne Reflex-Quelltext). Hostnamen und IPs bleiben lokal, der Router braucht sie. |

Einträge tragen weder Hostnamen noch Instanz. Der Herausgeber ist `vi-` + die ersten 12 Hexziffern des SHA-256 seines öffentlichen Schlüssels.

**Recht auf Vergessen.** Eine Instanz ohne Netz-Token verteilt nichts. Je Objekt gilt `netz_id = HMAC(Token, "id|"+oid)[:32]`, `objekt_token = HMAC(Token, "vergessen|"+oid)`, `loesch_hash = SHA-256(objekt_token)`.
Das Netz sieht `netz_id` und `loesch_hash`; beide sind untereinander nicht verknüpfbar. `vi_netz_vergiss` prüft das Instanz-Token und erlaubt nur eigene Objekte. Widerrufe sind eigene Logbuch-Einträge und beweisen sich selbst: Gelöscht wird nur, wenn `SHA-256(token)` zum `loesch_hash` passt. Der Empfänger löscht Objekt, Tags, Volltext, Kanten, Lager und Vektor und behält einen Grabstein ohne Inhalt. Trifft ein Widerruf vor dem Objekt ein, bleibt das Objekt weg.
Aus einem gelöschten Objekt abgeleitete Abstraktionen des Schlafs bleiben bestehen.

## Netz — Logbücher statt Bundles

Je Server ein Logbuch (`logbuch.py`): Einträge mit `seq`, Hash des Vorgängers, Typ (`objekt`, `widerruf`, `einladung`, `ausschluss`, `adresse`), Hash des Inhalts, Datum, Ed25519-Signatur.
Kopf und Inhalt liegen getrennt: Ein Widerruf löscht den Inhalt, die Kette bleibt prüfbar. Zwei verschiedene Einträge mit gleicher Nummer sind eine Gabelung, der Herausgeber wird danach nicht mehr angenommen.
Fremde Einträge werden nur angenommen, wenn Kette, Signatur, Mitgliedschaft, Tageskontingent (5.000) und für Objekte die festen Regeln samt `anonym.py` passen. Ein Objekt, das die Regeln verletzt, wird ohne Inhalt in die Kette übernommen und als Verstoß gezählt.

Der Netzdienst (`netzdienst.py`, systemd `vi-p2p`, eigener Nutzer, `InaccessiblePaths=/var/lib/vi-mcp`) macht je Runde: Ausgang des Gedächtnisses ins eigene Logbuch (`vi_netz_ausgang`), Abgleich mit bis zu 6 zufälligen Peers
(Köpfe tauschen, Fehlendes holen, Eigenes schieben), Neues ans Gedächtnis (`vi_netz_eingang`, Instanz `p2p`), Nachbarn anstoßen. Takt 300 s, ein Anstoß weckt sofort. Peers kommen aus der Startliste und aus `adresse`-Einträgen.
Jede Anfrage trägt `Authorization: VI-Netz <Schlüssel> <Zeit> <Signatur über Methode, Pfad, Zeit, SHA-256 des Körpers>`, gültig 300 s; nur Mitglieder bekommen Antwort, 240 Anfragen je Minute und Schlüssel.
Unverschlüsseltes HTTP nur zum eigenen Rechner oder mit `http_erlaubt`. TLS wird über die CA geprüft (`ca_datei`) oder, wenn für die Adresse ein Pin bekannt ist, über den SHA-256 des Zertifikats in DER-Form.
Ein Pin kommt nur aus signierter Quelle: dem `adresse`-Eintrag des Peers selbst (Feld `pin`, seit 0.15.0) oder einem Beitrittscode. Ein `proxy` wird für fremde Peers per CONNECT genutzt, `kein_proxy` nimmt Domains aus.
Beitritt: `einladung` legt auf einem peerhost den SHA-256 eines Zufallsgeheimnisses mit Ablaufzeit ab und gibt einen Code aus (`vinetz1.` + Base64 von Gründern, Adresse, Pin, Geheimnis, Ablauf).
`beitreten` richtet den Server ein und schickt das Geheimnis an `POST /netz/beitritt`, signiert mit dem neuen Schlüssel (Beweis des Besitzes, keine Mitgliedschaft nötig, 10 Versuche je Minute).
Passt es, wird es als benutzt markiert und der peerhost schreibt eine Einladung in sein Logbuch. Ab 1.000 fehlenden Einträgen eines Herausgebers holt der Dienst fertige Segmente (2.000 Einträge, JSON-Zeilen) per BitTorrent direkt vom Peer
(privat, ohne DHT, LSD, UPnP); ein Segment mit vergessenem Inhalt wird verworfen.

Im Gedächtnis (`p2p.py`) wird jede Signatur erneut geprüft, weil der Netzdienst fremde Daten liest. `glauben` in `/etc/vi-p2p/config.json` begrenzt, wessen Objekte überhaupt ins Gedächtnis gehen; Widerrufe gelten immer.
Nutzen je Herausgeber = Beta-Mittel seiner Hinweis-Zähler; ab 20 Urteilen und Mittel < 0,3 werden seine Objekte nicht mehr gezeigt. `p2p.auto_freigabe` gibt Unauffälliges im Schlaf vorläufig frei.

## Housekeeping — das Langzeitlager

`lager.py`, Schlaf-Schritt 5. Nicht mehr verwendete Einträge wandern in eine eigene Datei (`<db>-lager.db`, 0600), damit
der aktive Speicher klein bleibt. Im Gedächtnis bleibt ein Stummel.

| Was | Wann (Startwerte, konfig `lager_tage`) |
|---|---|
| Erfahrung | 30 Tage alt, nie abgerufen, kein Beleg |
| Schlaf-Bericht | 90 Tage alt |
| Erkenntnis, Regel, Suche, Skill | 180 Tage weder abgerufen, geändert noch als Hinweis gezeigt |
| Rohverlauf eines Gesprächs | 30 Tage nach der letzten Änderung, Gespräch nicht offen |

Nie automatisch: Selbst, Modell, Fragen, Reflexe (das würde ein Verhalten still abschalten), Gesprächs-Zusammenfassungen.
Passt gelagertes Wissen zu einer Handlung, nennt `vi_vorher` das in einer Zeile. `vi_lager` zeigt Stand und Inhalt,
`vi_lager_hole(id, grund)` holt einen Eintrag im alten Modus zurück. Die Löschwege für Gespräche und Instanzen gelten auch
im Lager. Die Hauptdatei wird neu geschrieben, wenn über 25 % frei sind. Die Fristen sind unkalibriert. *Beobachtungspunkt:*
wie oft `vi_lager_hole` nötig wird; häufiges Zurückholen heißt, die Frist ist zu kurz.

## Reflexion — das Sprachmodell denkt im Schlaf nach (Stufe 4)

`reflexion.py` (Park et al. 2023, 4.2): je Cluster ohne Schema fragt der Schlaf ein lokales Sprachmodell (konfig `llm`,
OpenAI-kompatibel, statischer Systemprompt, kein `max_tokens`, Thinking aus) nach **höchstens einer** Erkenntnis als
JSON (Satz ≤ 300 Zeichen, ≤ 5 Hashtags, ≥ 3 Belegnummern). Die Antwort wird **deterministisch geprüft** — Hashtags nach
TAG-Regel, Belege müssen Nummern des Clusters sein, Anweisungsmuster („ignoriere…“, „führe … aus“, „lösche“, Shell,
Base64, Passwort/Token) führen zur Verwerfung mit Grund im Bericht. Ergebnis: Erkenntnis im Modus `test`,
`herkunft:schlaf-llm`, Belegkanten zu jeder genannten Erfahrung; wirksam erst durch Bestätigung einer anderen Instanz.
Die Vorlagen-Abstraktion (Schritt 4) bleibt Rückfall für Cluster ohne Reflexion. Das Modell auf dem Produktivhost
antwortet in ≈ 1,7 s (gemessen 08.11.2026).

## Loop

Genau einer, alle 60 s: Antworten älter als 1 h löschen · wiederholte Fehler → Regel (test, idempotent) ·
offene Gespräche sichern · Leerlauf → `abgelaufen` · WAL-Checkpoint. Fehler werden gezählt und in `vi_status` genannt.

## Reflexe

Code im Gedächtnis, den die VI sich selbst schreibt. Prüfung per AST: Import-Whitelist
(`reflexe.REFLEX_MODULE`), kein `exec`/`eval`/`open`/`getattr`/…, keine Dunder-Attribute; Zeitlimit 10 s; nach 3
Fehlern `defekt` (benannt, entladen).

**Sandbox (`sandbox.py`, seit 0.9.0):** Jeder Lauf ist ein eigener Prozess (`python3 -I -S`), der sich vor dem Übersetzen
des fremden Codes unumkehrbar begrenzt: Landlock (lesbar nur `/usr`, `/lib`, `/lib64`, `/bin`; nichts schreib- oder
kürzbar; kein TCP), seccomp (kein `socket()`, damit auch kein UDP; kein `execve`, `fork`, `clone`, `ptrace`), Grenzen für CPU,
Speicher, Dateien; Wanduhr und Ausgabelimit erzwingt der Server. Die Sandbox setzt voraus, dass die AST-Prüfung
versagt hat, und schützt auch die `vi.db`, obwohl das Kind unter demselben Nutzer läuft. Ist sie nicht herstellbar
(kein Landlock ABI ≥ 4, nicht x86_64), läuft der Code **nicht** (`isolation: keine`). Kosten: ≈ 14 ms je Lauf
(gemessen 08.11.2026). Reflexe lernen oder schalten dürfen nur Instanzen mit `reflexe: true`.

## Open-Wiki-Modus

`"offen": true` ordnet Anfragen ohne `Authorization` der festen Instanz `offen` zu (`konfig.OFFEN`, als Name reserviert). Ein falsches Token bleibt 401.
`offen` sieht nur die Werkzeuge in `werkzeuge.OFFEN_ERLAUBT`: lesen, `vi_vorher`/`vi_nachher`, `vi_lerne`. Ein `vi_lerne` von `offen` wird ein Objekt in der Quarantäne mit
`herkunft:offen`, Regelbefund (`pruefung.anweisungen`) und ausstehendem Prüfer; es durchläuft denselben Weg wie ein Netz-Import (`p2p.heikel`, `p2p.freigeben`, `p2p.auto_freigeben`).
`offen` hat keinen Antwortspeicher: Alle Gäste teilen sich eine Instanz, gemerkte Antworten würden das Ergebnis eines Kollegen an alle geben.
Bleibende Grenze: Handlungen von Gästen fließen in die Hinweis-Zähler und das Router-Training ein. Ein Gast kann so die Reihenfolge geprüfter Hinweise beeinflussen, aber keinen Inhalt einbringen.

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
